"""SPEC regression reproductions; signed HTTP and disposable SQLite only."""
import asyncio
import json

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from test_publication_sync import database, event, generated, signature, sync_module

PRODUCTION = 'https://nucleo.jor.br'
STAGING = 'https://staging.nucleo.jor.br'


@pytest.mark.parametrize('origin', [None, PRODUCTION, STAGING])
@pytest.mark.parametrize('enabled', [None, '0', '1', '', 'true', '2', '01', '1\n'])
def test_startup_origin_sync_matrix_before_application_imports(monkeypatch, origin, enabled):
    import builtins
    from pathlib import Path
    import runpy
    if origin is None:
        monkeypatch.delenv('PUBLICATION_SOURCE_ORIGIN', raising=False)
    else:
        monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', origin)
    if enabled is None:
        monkeypatch.delenv('PUBLICATION_SYNC_ENABLED', raising=False)
    else:
        monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', enabled)
    rejected = origin == STAGING and enabled != '1'
    original = builtins.__import__
    imports = []

    def guarded(name, *args, **kwargs):
        if name.startswith(('fastapi', 'starlette', 'app.publication_sync', 'app.model', 'app.controllers')):
            imports.append(name)
            if rejected:
                pytest.fail('staging OFF reached application import before rejection: ' + name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    path = str(Path(__file__).resolve().parents[1] / 'main.py')
    if rejected:
        with pytest.raises(ValueError) as error:
            runpy.run_path(path, run_name='startup_probe')
        assert str(error.value) == 'Invalid publication source configuration'
        assert imports == []
    else:
        namespace = runpy.run_path(path, run_name='startup_probe')
        assert namespace['app'] is not None


@pytest.mark.parametrize('configured,foreign', [(PRODUCTION, STAGING), (STAGING, PRODUCTION)])
@pytest.mark.parametrize('kind', ['post.deleted', 'post.unpublished'])
@pytest.mark.parametrize('shape', ['minimal', 'local_current', 'null_current'])
def test_foreign_previous_withdrawal_preserves_ready(tmp_path, monkeypatch, configured, foreign, kind, shape):
    import main
    sync = sync_module()
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    monkeypatch.setenv('WEBHOOK_SECRET', 'offline-secret')
    monkeypatch.setattr(sync.time, 'time', lambda: 1800000000)
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    monkeypatch.setattr(main.app.state, 'publication_inbox', inbox, raising=False)
    try:
        with TestClient(main.app) as client:
            raw = event(url=configured + '/post/')
            assert client.post('/post/', content=raw, headers={'x-ghost-signature': signature(raw)}).status_code == 204
            assert asyncio.run(sync.work_once(inbox, generated, now=1)) is True
            ready = client.get('/post/').json()
            assert ready[0]['link'] == configured + '/post/'
            with engine.connect() as conn:
                before_inbox = dict(conn.execute(select(sync.inbox_table)).mappings().one())
                before_post = dict(conn.execute(select(posts)).mappings().one())
            current = dict(id='a' * 24, updated_at='2026-10-20T12:01:00Z')
            if shape == 'local_current':
                current['url'] = configured + '/post/'
            previous = dict(current, url=foreign + '/post/')
            envelope = {'current': None if shape == 'null_current' else current, 'previous': previous}
            raw = json.dumps({'event': kind, 'post': envelope}).encode()
            response = client.post('/post/', content=raw, headers={'x-ghost-signature': signature(raw)})
            with engine.connect() as conn:
                after_inbox = dict(conn.execute(select(sync.inbox_table)).mappings().one())
                after_post = conn.execute(select(posts)).mappings().first()
            assert (response.status_code, after_inbox, dict(after_post) if after_post else None,
                    client.get('/post/').json()) == (400, before_inbox, before_post, ready)
            # A genuinely URL-less tombstone still removes the ready summary.
            envelope = {'current': None, 'previous': dict(id='a' * 24, updated_at='2026-10-20T12:01:00Z')}
            raw = json.dumps({'event': kind, 'post': envelope}).encode()
            assert client.post('/post/', content=raw, headers={'x-ghost-signature': signature(raw)}).status_code == 204
            assert client.get('/post/').json() == []
    finally:
        engine.dispose()
