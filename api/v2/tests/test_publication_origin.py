"""Trusted staging policy: synthetic events/HTTP/TLS only, no external I/O."""
import json
import pytest
from test_publication_sync import event, sync_module
from test_publication_source import KEY

PRODUCTION = 'https://nucleo.jor.br'
STAGING = 'https://staging.nucleo.jor.br'


def test_staging_opt_in_consumer(monkeypatch):
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    assert sync_module().normalize(event(url=STAGING + '/post/'))['eligible'] is True
    with pytest.raises(sync_module().Rejected):
        sync_module().normalize(event())


def test_staging_opt_in_reconcile(tmp_path, monkeypatch):
    from app.publication_reconcile import reconcile
    from test_publication_sync import database
    sync = sync_module()
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    engine, posts = database(tmp_path)
    sync.provision(engine)
    current = json.loads(event(url=STAGING + '/post/'))['post']['current']

    class Source:
        def page(self, page, limit):
            return [current], None
        def get(self, identity):
            return current

    assert reconcile(sync.Inbox(engine, posts), Source(), pages=1, known=1) == {'pages': 1, 'checked': 1}
    engine.dispose()


def test_staging_opt_in_admin(monkeypatch):
    from app.publication_source import GhostAdmin
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    assert GhostAdmin(STAGING, KEY).host == 'staging.nucleo.jor.br'
    with pytest.raises(sync_module().Rejected):
        GhostAdmin(PRODUCTION, KEY)


@pytest.mark.parametrize('configured,foreign', [(PRODUCTION, STAGING), (STAGING, PRODUCTION)])
@pytest.mark.parametrize('enabled', [False, True])
def test_foreign_url_rejected_including_legacy(monkeypatch, configured, foreign, enabled):
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    with pytest.raises(sync_module().Rejected):
        sync_module().normalize(event(url=foreign + '/post/'), require_revision=enabled)


@pytest.mark.parametrize('tail', ['?', '#', '?x=1', '#fragment'])
def test_no_query_or_fragment_even_empty(monkeypatch, tail):
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    with pytest.raises(sync_module().Rejected):
        sync_module().normalize(event(url=STAGING + '/post/' + tail))


def test_wrong_origin_withdrawal_is_not_admitted(monkeypatch):
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    with pytest.raises(sync_module().Rejected):
        sync_module().normalize(event(event='post.deleted'))


def test_wrong_origin_previous_tombstone_is_not_admitted(monkeypatch):
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    current = json.loads(event())['post']['current']
    raw = json.dumps({'event': 'post.deleted', 'post': {'current': None, 'previous': current}}).encode()
    with pytest.raises(sync_module().Rejected):
        sync_module().normalize(raw)


def test_default_legacy_contract_and_staging_denial(monkeypatch):
    monkeypatch.delenv('PUBLICATION_SOURCE_ORIGIN', raising=False)
    sync = sync_module()
    assert sync.normalize(event(id='old_ID', updated_at=None, url='https://example.test/legacy'),
                          require_revision=False)['eligible'] is True
    with pytest.raises(sync.Rejected):
        sync.normalize(event(url=STAGING + '/post/'), require_revision=False)


@pytest.mark.parametrize('configured,foreign', [(PRODUCTION, STAGING), (STAGING, PRODUCTION)])
def test_worker_checks_persisted_source_before_generation(tmp_path, monkeypatch, configured, foreign):
    import asyncio
    from test_publication_sync import database
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', foreign)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event(url=foreign + '/post/')))
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    calls = []

    async def forbidden(item):
        calls.append(item)
        raise AssertionError('provider must not be called')

    from test_publication_origin_quality_fixes import snapshot
    before = snapshot(engine, sync.inbox_table, posts)
    with pytest.raises(sync.Rejected):
        asyncio.run(sync.work_once(inbox, forbidden, now=1))
    assert snapshot(engine, sync.inbox_table, posts) == before
    assert calls == []
    engine.dispose()


@pytest.mark.parametrize('configured,foreign', [(PRODUCTION, STAGING), (STAGING, PRODUCTION)])
def test_generation_adapter_checks_origin_before_controller_import(monkeypatch, configured, foreign):
    import asyncio
    from app import publication_generation
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    monkeypatch.setattr(publication_generation.importlib, 'import_module', lambda *_: pytest.fail('controller import forbidden'))
    with pytest.raises((ValueError, sync_module().Rejected)):
        asyncio.run(publication_generation.generate(dict(url=foreign + '/post/')))


def test_staging_cors_ignores_legacy_wildcard(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')  # Required for staging startup.
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', '*')
    try:
        with TestClient(importlib.reload(main).app) as client:
            for origin, status in [(STAGING, 200), (PRODUCTION, 400), ('https://www.staging.nucleo.jor.br', 400)]:
                response = client.options('/post/', headers={'Origin': origin, 'Access-Control-Request-Method': 'GET'})
                assert response.status_code == status
                assert response.headers.get('access-control-allow-origin') == (origin if status == 200 else None)
    finally:
        monkeypatch.delenv('PUBLICATION_SOURCE_ORIGIN')
        importlib.reload(main)


@pytest.mark.parametrize('origin,expected', [(PRODUCTION, 200), ('https://www.nucleo.jor.br', 200), (STAGING, 400)])
def test_explicit_production_cors_excludes_staging(monkeypatch, origin, expected):
    import importlib
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', PRODUCTION)
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', '*')
    try:
        with TestClient(importlib.reload(main).app) as client:
            response = client.options('/post/', headers={'Origin': origin, 'Access-Control-Request-Method': 'GET'})
            assert response.status_code == expected
    finally:
        monkeypatch.delenv('PUBLICATION_SOURCE_ORIGIN')
        importlib.reload(main)


@pytest.mark.parametrize('command', [['reconcile', '--apply'], ['worker', '--run', '--once']])
def test_invalid_config_cli_preflight_before_model_import(monkeypatch, command):
    import builtins
    from app.publication_cli import main
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING + '/wrong')
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == 'app.model':
            pytest.fail('invalid origin must be rejected before engine import')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    assert main(command) == 1


def test_conflicting_admin_cli_preflight_before_model_import(monkeypatch):
    import builtins
    from app.publication_cli import main
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    monkeypatch.setenv('PUBLICATION_GHOST_ADMIN_ORIGIN', PRODUCTION)
    monkeypatch.setenv('PUBLICATION_GHOST_ADMIN_KEY', KEY)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == 'app.model':
            pytest.fail('conflicting admin origin must fail before engine import')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    assert main(['reconcile', '--apply']) == 1


@pytest.mark.parametrize('configured,foreign', [(PRODUCTION, STAGING), (STAGING, PRODUCTION)])
def test_signed_http_ingress_and_offline_worker_end_to_end(tmp_path, monkeypatch, configured, foreign):
    import asyncio
    import main
    from fastapi.testclient import TestClient
    from test_publication_sync import database, generated, signature
    sync = sync_module()
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    monkeypatch.setenv('WEBHOOK_SECRET', 'offline-secret')
    monkeypatch.setattr(sync.time, 'time', lambda: 1800000000)
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    monkeypatch.setattr(main.app.state, 'publication_inbox', inbox, raising=False)
    with TestClient(main.app) as client:
        raw = event(url=foreign + '/post/')
        assert client.post('/post/', content=raw, headers={'x-ghost-signature': signature(raw)}).status_code == 400
        assert client.get('/post/').json() == []
        raw = event(url=configured + '/post/')
        assert client.post('/post/', content=raw, headers={'x-ghost-signature': signature(raw)}).status_code == 204
        assert client.get('/post/').json() == []
        assert asyncio.run(sync.work_once(inbox, generated, now=1)) is True
        assert client.get('/post/').json()[0]['link'] == configured + '/post/'
        assert client.get('/post/' + 'a' * 24).status_code == 200
    engine.dispose()


def test_staging_cli_reconcile_and_single_worker_offline(tmp_path, monkeypatch):
    from app import model, publication_source, publication_cli
    from test_publication_sync import database, generated
    engine, posts = database(tmp_path)
    sync_module().provision(engine)
    monkeypatch.setattr(model, 'engine', engine)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    monkeypatch.setenv('PUBLICATION_GHOST_ADMIN_ORIGIN', STAGING)
    monkeypatch.setenv('PUBLICATION_GHOST_ADMIN_KEY', KEY)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    calls = []
    post = json.loads(event(url=STAGING + '/post/'))['post']['current']
    def request(self, path, *, missing=False):
        assert self.host == 'staging.nucleo.jor.br'
        calls.append((path, missing))
        return {'posts': [post], 'meta': {'pagination': {'next': None}}}
    monkeypatch.setattr(publication_source.GhostAdmin, '_request', request)
    assert publication_cli.main(['reconcile', '--apply', '--pages', '1', '--known', '1', '--page-size', '1']) == 0
    assert len(calls) == 2 and calls[0][1] is False and calls[1][1] is True
    monkeypatch.setattr(publication_cli, 'generate', generated)
    assert publication_cli.main(['worker', '--run', '--once']) == 0
    assert sync_module().Inbox(engine, posts).read_verified()[0]['link'] == STAGING + '/post/'
    engine.dispose()


@pytest.mark.parametrize('configured,foreign', [(PRODUCTION, STAGING), (STAGING, PRODUCTION)])
def test_persisted_foreign_summary_not_read_or_finished(tmp_path, monkeypatch, configured, foreign):
    import asyncio
    from test_publication_sync import database, generated
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', foreign)
    inbox.enqueue(sync.normalize(event(url=foreign + '/post/')))
    job = inbox.claim(now=1)
    result = asyncio.run(generated(json.loads(job['payload'])))
    assert inbox.finish(job, result) is True
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    for kwargs in [{}, {'identity': 'a' * 24}]:
        with pytest.raises(sync.Rejected):
            inbox.read_verified(**kwargs)
    # A previously admitted provider result must not be materialized after a config change.
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', foreign)
    inbox.enqueue(sync.normalize(event('2026-10-20T12:01:00Z', url=foreign + '/post/', plaintext='changed')))
    job = inbox.claim(now=2)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    with pytest.raises((sync.Rejected, ValueError)):
        inbox.finish(job, result)
    engine.dispose()


@pytest.mark.parametrize('configured', [None, PRODUCTION, STAGING])
def test_policy_exact_hosts_and_legacy_www(monkeypatch, configured):
    from app.publication_source import GhostAdmin
    if configured is None:
        monkeypatch.delenv('PUBLICATION_SOURCE_ORIGIN', raising=False)
    else:
        monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    accepted = [STAGING] if configured == STAGING else [PRODUCTION, 'https://www.nucleo.jor.br']
    for origin in [PRODUCTION, STAGING, 'https://www.nucleo.jor.br', 'https://www.staging.nucleo.jor.br']:
        if origin in accepted:
            assert sync_module().normalize(event(url=origin + '/post/'))['url'] == origin + '/post/'
            assert GhostAdmin(origin, KEY).host == origin.removeprefix('https://')
        else:
            with pytest.raises(sync_module().Rejected):
                sync_module().normalize(event(url=origin + '/post/'))
            with pytest.raises(sync_module().Rejected):
                GhostAdmin(origin, KEY)


BAD_ORIGINS = [
    '', 'https://www.nucleo.jor.br', 'http://staging.nucleo.jor.br',
    STAGING + '/', STAGING + '/ghost', STAGING + ':443', STAGING + '?', STAGING + '#',
    STAGING + '?x=1', STAGING + '#fragment', STAGING + '.evil.test',
    'https://user@staging.nucleo.jor.br', 'https://staging.nucleo.jor.br@evil.test',
    'https://www.staging.nucleo.jor.br', 'https://STAGING.nucleo.jor.br', STAGING + '\n',
]


@pytest.mark.parametrize('origin', BAD_ORIGINS)
def test_bad_trusted_configuration_fails_closed(monkeypatch, origin):
    from app.publication_source import GhostAdmin
    from app.publication_origin import source_origin
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', origin)
    with pytest.raises(ValueError, match='Invalid publication source configuration'):
        source_origin()
    with pytest.raises(sync_module().Rejected):
        sync_module().normalize(event())
    with pytest.raises(sync_module().Rejected):
        GhostAdmin(STAGING, KEY)


@pytest.mark.parametrize('url', [
    STAGING + '.evil.test/post/', 'https://user@staging.nucleo.jor.br/post/',
    'https://staging.nucleo.jor.br@evil.test/post/', STAGING + ':443/post/',
    STAGING + '/post/?x=1', STAGING + '/post/#x', STAGING + '/%2e%2e/post/',
    STAGING + '/./post/', STAGING + '/../post/', STAGING + '//post/',
    'http://staging.nucleo.jor.br/post/', 'https://www.staging.nucleo.jor.br/post/',
    STAGING + '/post/\n',
])
def test_bad_article_urls_rejected(monkeypatch, url):
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    with pytest.raises(sync_module().Rejected):
        sync_module().normalize(event(url=url))


@pytest.mark.parametrize('configured', [PRODUCTION, STAGING])
def test_admin_page_and_id_fetch_use_only_selected_host(monkeypatch, configured):
    import ssl
    from app import publication_source as source
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    requests, hosts, closes = [], [], []
    post = json.loads(event(url=configured + '/post/'))['post']['current']

    class Response:
        status = 200
        def read(self, limit):
            assert limit == source.MAX_RESPONSE + 1
            return json.dumps({'posts': [post], 'meta': {'pagination': {'next': None}}}).encode()

    class Connection:
        def __init__(self, host, *, timeout, context):
            hosts.append(host)
            assert timeout == 10
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        def request(self, method, path, headers):
            requests.append((method, path, headers))
        def getresponse(self):
            return Response()
        def close(self):
            closes.append(True)

    monkeypatch.setattr(source, 'PinnedHTTPSConnection', Connection)
    admin = source.GhostAdmin(configured, KEY)
    assert admin.page(1, 1) == ([post], None)
    assert admin.get('a' * 24) == post
    assert hosts == [configured.removeprefix('https://')] * 2
    assert len(closes) == 2
    assert all(r[0] == 'GET' and r[1].startswith('/ghost/api/admin/posts/') for r in requests)
    assert '/posts/' + 'a' * 24 + '/?' in requests[1][1]


@pytest.mark.parametrize('configured', [PRODUCTION, STAGING])
def test_pinned_tls_selected_host_and_foreign_denied_before_dns(monkeypatch, configured):
    import ssl
    from app import publication_source as source
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    host = configured.removeprefix('https://')
    seen = []
    sentinel = object()
    def dns(name, port, **kwargs):
        seen.append(('dns', name, port))
        return [(2, 1, 6, '', ('93.184.216.34', 443))]
    def connect(address, timeout):
        seen.append(('socket', address, timeout))
        return sentinel
    def tls(sock, *, server_hostname):
        assert sock is sentinel
        seen.append(('tls', server_hostname))
        return sentinel
    context = ssl.create_default_context()
    monkeypatch.setattr(source.socket, 'getaddrinfo', dns)
    monkeypatch.setattr(source.socket, 'create_connection', connect)
    monkeypatch.setattr(context, 'wrap_socket', tls)
    source.PinnedHTTPSConnection(host, context=context, timeout=10).connect()
    assert seen == [('dns', host, 443), ('socket', ('93.184.216.34', 443), 10), ('tls', host)]
    count = len(seen)
    foreign = 'nucleo.jor.br' if configured == STAGING else 'staging.nucleo.jor.br'
    with pytest.raises(sync_module().Rejected):
        source.PinnedHTTPSConnection(foreign, context=context, timeout=10).connect()
    assert len(seen) == count


@pytest.mark.parametrize('configured,foreign', [(PRODUCTION, STAGING), (STAGING, PRODUCTION)])
@pytest.mark.parametrize('path', ['page', 'known'])
def test_reconcile_rejects_foreign_page_and_id(tmp_path, monkeypatch, configured, foreign, path):
    from sqlalchemy import insert, select
    from app.publication_reconcile import reconcile, cursor_table
    from test_publication_sync import database
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', configured)
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    post = json.loads(event(url=foreign + '/post/'))['post']['current']
    with engine.begin() as conn:
        conn.execute(insert(posts).values(id='a' * 24, title='synthetic legacy'))
    class Source:
        def page(self, page, limit):
            return ([post] if path == 'page' else []), None
        def get(self, identity):
            return post
    with pytest.raises(sync.Rejected):
        reconcile(inbox, Source(), pages=1, known=1)
    with engine.connect() as conn:
        assert conn.execute(select(sync.inbox_table)).first() is None
        assert conn.execute(select(cursor_table.c.version)).scalar_one() == 0
        assert conn.execute(select(posts.c.id)).scalar_one() == 'a' * 24
    engine.dispose()
