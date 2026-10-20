"""Review regressions; all payloads synthetic, no network or models."""
import asyncio
import json
import pytest
from sqlalchemy import select, insert
from test_publication_sync import event, database, generated, signature, sync_module


@pytest.mark.parametrize('kind', ['post.deleted', 'post.unpublished'])
def test_real_ghost_event_overrides_complete_published_current(kind, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    monkeypatch.setenv('WEBHOOK_SECRET', 'offline-secret')
    monkeypatch.setattr(sync.time, 'time', lambda: 1800000000)
    monkeypatch.setattr(main.app.state, 'publication_inbox', inbox, raising=False)
    inbox.enqueue(sync.normalize(event()))
    old = inbox.claim(now=1)
    ready = inbox.claim(now=121)
    inbox.finish(ready, asyncio.run(generated(json.loads(ready['payload']))))
    raw = event(event=kind)  # Ghost 6.61 deleted current can still be published/public.
    assert sync.normalize(raw)['eligible'] is False
    assert sync.normalize(event(event=kind, html=None, plaintext=None))['eligible'] is False
    with TestClient(main.app) as client:
        assert client.post('/post/', content=raw, headers={'x-ghost-signature': signature(raw)}).status_code == 204
        assert client.get('/post/' + 'a' * 24).status_code == 404
        assert client.get('/post/').json() == []
    assert inbox.finish(old, asyncio.run(generated(json.loads(old['payload'])))) is False


def test_body_event_allowlist_identity_date_origin_and_limits():
    sync = sync_module()
    body = json.loads(event())
    for kind in [None, '', 'post.added', 'post.scheduled', 'site.changed']:
        body['event'] = kind
        with pytest.raises(sync.Rejected):
            sync.normalize(json.dumps(body).encode())
    del body['event']
    with pytest.raises(sync.Rejected):
        sync.normalize(json.dumps(body).encode())
    for changes in [dict(id='A' * 24), dict(id='short'), dict(updated_at='2026-10-20T12:00:00+03:00'),
                    dict(url='http://nucleo.jor.br/a/'), dict(url='https://evil.test/a/'),
                    dict(url='https://nucleo.jor.br@evil.test/a/'), dict(url='https://nucleo.jor.br:443/a/'),
                    dict(url='https://nucleo.jor.br/a/?x=1'), dict(url='https://nucleo.jor.br/a/#x'),
                    dict(plaintext='x' * 200001), dict(html='x' * 200001), dict(title='x' * 1001)]:
        with pytest.raises(sync.Rejected):
            sync.normalize(event(**changes))
    with pytest.raises(sync.Rejected) as failure:
        sync.normalize(b' ' * (256 * 1024 + 1))
    assert failure.value.status == 413
    # Explicit compatibility is OFF-mode only, never the default strict path.
    assert sync.normalize(event(id='old_ID', updated_at=None, url='https://example.test/legacy'),
                          require_revision=False)['eligible'] is True


def test_same_digest_watermark_does_not_invalidate_final_valid_claim(tmp_path):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    for now in range(1, 5):
        job = inbox.claim(now=now, lease=1)
    job = inbox.claim(now=5, lease=1)
    assert job['attempts'] == 5
    inbox.enqueue(sync.normalize(event('2026-10-20T12:01:00Z')))
    assert inbox.finish(job, asyncio.run(generated(json.loads(job['payload'])))) is True
    with engine.connect() as conn:
        assert conn.execute(select(sync.inbox_table.c.status)).scalar_one() == 'done'
        assert conn.execute(select(sync.inbox_table.c.revision)).scalar_one() == sync.normalize(event('2026-10-20T12:01:00Z'))['revision']
    assert inbox.enqueue(sync.normalize(event())) == 'stale'
    # The failure path uses the same token+content-version fence as finish.
    inbox.enqueue(sync.normalize(event('2026-10-20T12:02:00Z', plaintext='retry')))
    retry = inbox.claim(now=7)
    inbox.enqueue(sync.normalize(event('2026-10-20T12:03:00Z', plaintext='retry')))
    inbox.fail(retry, now=8, max_attempts=5)
    assert inbox.claim(now=17) is None
    assert inbox.claim(now=18)['attempts'] == 2


@pytest.mark.parametrize('publication, expected', [('2026-09-01T01:02:03.000Z', '2026-09-01T01:02:03'),
                                                   (None, '2026-10-20T12:00:00')])
def test_public_date_is_publication_not_revision(tmp_path, publication, expected):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event(published_at=publication)))
    asyncio.run(sync.work_once(inbox, generated, now=1))
    with engine.connect() as conn:
        assert conn.execute(select(posts.c.timestamp)).scalar_one().isoformat() == expected


def test_new_mode_reads_fail_closed_for_unverified_legacy_rows(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    from app import model
    engine, posts = database(tmp_path)
    sync_module().provision(engine)
    monkeypatch.setattr(model, 'engine', engine)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    monkeypatch.setattr(main.app.state, 'publication_inbox', sync_module().Inbox(engine, posts), raising=False)
    with engine.begin() as conn:
        conn.execute(insert(posts).values(id='a' * 24, title='old', link='https://nucleo.jor.br/a/', summary='["old"]', summary_en='["old"]'))
    with TestClient(main.app) as client:
        assert client.get('/post/' + 'a' * 24).status_code == 404
        assert client.get('/post/').json() == []
        monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '0')
        assert client.get('/post/' + 'a' * 24).status_code == 200
        assert len(client.get('/post/').json()) == 1
