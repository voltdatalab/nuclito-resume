"""Offline integration: real SQLAlchemy, synthetic posts, injected generation only."""
import asyncio
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from sqlalchemy import create_engine, select


def sync_module():
    assert importlib.util.find_spec('app.publication_sync') is not None, 'durable webhook boundary is missing'
    from app import publication_sync
    return publication_sync


def signature(raw, timestamp='1800000000000'):
    digest = hmac.new(b'offline-secret', raw + timestamp.encode(), hashlib.sha256).hexdigest()
    return f'sha256={digest}, t={timestamp}'


def event(revision='2026-10-20T12:00:00.000Z', **changes):
    current = dict(id='a' * 24, title='Título', url='https://nucleo.jor.br/post/',
                   plaintext='Texto sintético', html='<p>Texto sintético</p>',
                   published_at='2026-10-20T12:00:00.000Z', primary_tag=None, tags=[],
                   status='published', visibility='public', updated_at=revision)
    kind = changes.pop('event', 'post.edited')
    current.update(changes)
    return json.dumps({'event': kind, 'post': {'current': current}}, ensure_ascii=False).encode()


def test_normalization_public_policy_and_revision():
    sync = sync_module()
    assert hasattr(sync, 'normalize'), 'normalization missing'
    result = sync.normalize(event(event='post.published.edited'))
    assert result['eligible'] is True
    assert sync.normalize(event('2026-10-20T12:00:00+00:00'))['revision'] == sync.normalize(event())['revision']
    assert sync.normalize(event('2026-10-20T12:00:00Z'))['revision'] == sync.normalize(event())['revision']
    assert sync.normalize(event(event='post.published'))['eligible'] is True
    assert sync.normalize(event())['eligible'] is True
    assert result['id'] == 'a' * 24
    assert result['revision'] == 1792497600000000
    for changes in [dict(status='draft'), dict(visibility='members'),
                    dict(visibility='paid'), dict(primary_tag={'slug': 'newsletter-news'}),
                    dict(primary_tag='broken'), dict(tags=[None]), dict(tags='broken'),
                    dict(status=None), dict(visibility=None)]:
        assert sync.normalize(event(**changes))['eligible'] is False
    for raw in [b'{}', b'{bad', event(updated_at='bad'), event(id='x' * 33)]:
        with pytest.raises(sync.Rejected):
            sync.normalize(raw)


def database(tmp_path):
    from sqlalchemy import MetaData, Table, Column, String, Text, DateTime, func
    engine = create_engine('sqlite:///' + str(tmp_path / 'isolated.sqlite'))
    posts = Table('posts', MetaData(), Column('id', String(32), primary_key=True),
                  Column('title', Text), Column('title_en', Text), Column('link', String(256)),
                  Column('summary', Text), Column('summary_en', Text),
                  Column('timestamp', DateTime, server_default=func.now()))
    posts.create(engine)
    return engine, posts


def test_durable_enqueue_duplicate_edit_stale_and_schema_gate(tmp_path):
    sync = sync_module()
    assert hasattr(sync, 'Inbox'), 'durable inbox missing'
    engine, posts = database(tmp_path)
    inbox = sync.Inbox(engine, posts)
    first = sync.normalize(event())
    with pytest.raises(sync.Rejected) as failure:
        inbox.enqueue(first)
    assert failure.value.status == 503
    sync.provision(engine)
    assert inbox.enqueue(first) == 'queued'
    assert sync.Inbox(engine, posts).enqueue(first) == 'duplicate'
    edit = sync.normalize(event('2026-10-20T12:01:00Z', plaintext='Edição'))
    assert inbox.enqueue(edit) == 'queued'
    assert inbox.enqueue(first) == 'stale'
    with engine.connect() as connection:
        rows = connection.execute(select(sync.inbox_table)).mappings().all()
    assert len(rows) == 1
    assert json.loads(rows[0]['payload'])['plaintext'] == 'Edição'
    assert rows[0]['status'] == 'pending'
    with pytest.raises(sync.Rejected) as failure:
        inbox.enqueue(sync.normalize(event('2026-10-20T12:01:00Z', plaintext='Conflito')))
    assert failure.value.status == 409


async def generated(item):
    return {'summary': ['PT ' + item['plaintext']] * 3,
            'summary_en': ['EN ' + item['plaintext']] * 3, 'title_en': 'English title'}


def test_worker_updates_and_private_invalidates_without_generation(tmp_path):
    sync = sync_module()
    assert hasattr(sync, 'work_once'), 'worker missing'
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    first = sync.normalize(event())
    inbox.enqueue(first)
    assert asyncio.run(sync.work_once(inbox, generated, now=10)) is True
    with engine.connect() as connection:
        row = connection.execute(select(posts)).mappings().one()
    assert json.loads(row['summary']) == ['PT Texto sintético'] * 3
    assert json.loads(row['summary_en']) == ['EN Texto sintético'] * 3
    assert row['title_en'] == 'English title'
    assert asyncio.run(sync.work_once(inbox, generated, now=11)) is False
    inbox.enqueue(sync.normalize(event('2026-10-20T12:01:00Z', plaintext='Edição')))
    assert asyncio.run(sync.work_once(inbox, generated, now=12)) is True
    with engine.connect() as connection:
        assert 'Edição' in connection.execute(select(posts.c.summary)).scalar_one()
    inbox.enqueue(sync.normalize(event('2026-10-20T12:02:00Z', visibility='members')))
    with engine.connect() as connection:
        assert connection.execute(select(posts)).first() is None
    assert asyncio.run(sync.work_once(inbox, generated, now=13)) is False
    assert inbox.enqueue(first) == 'stale'


def test_restart_crash_recovery_and_bounded_retry(tmp_path, capsys):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    abandoned = inbox.claim(now=100, lease=30)
    engine.dispose()
    engine = create_engine(engine.url)
    restarted = sync.Inbox(engine, posts)
    assert restarted.claim(now=129) is None
    recovered = restarted.claim(now=130)
    assert recovered is not None, 'expired durable claim must survive restart'
    assert recovered['attempts'] == 2
    assert restarted.finish(abandoned, asyncio.run(generated(json.loads(abandoned['payload'])))) is False
    assert restarted.finish(recovered, asyncio.run(generated(json.loads(recovered['payload'])))) is True
    restarted.enqueue(sync.normalize(event('2026-10-20T12:01:00Z', plaintext='Falha')))

    async def failing(_):
        raise RuntimeError('SECRET-SYNTHETIC-CONTENT')

    for now, expected_attempts in [(200, 1), (210, 2), (230, 3)]:
        assert asyncio.run(sync.work_once(restarted, failing, now=now, max_attempts=3)) is True
        with engine.connect() as connection:
            row = connection.execute(select(sync.inbox_table)).mappings().one()
        assert row['attempts'] == expected_attempts
        if now < 230:
            assert asyncio.run(sync.work_once(restarted, failing, now=now + 1, max_attempts=3)) is False
    assert row['status'] == 'dead'
    assert asyncio.run(sync.work_once(restarted, failing, now=10000, max_attempts=3)) is False
    assert 'SECRET-SYNTHETIC-CONTENT' not in str(capsys.readouterr())


def test_http_auth_before_parse_durable_ack_and_legacy_contract(tmp_path, monkeypatch):
    import types
    import importlib
    from fastapi.testclient import TestClient
    calls = []

    async def legacy_create(*args):
        calls.append(args)

    # Only the external LLM boundary is replaced; use the actual HTTP app.
    fake_controller = types.SimpleNamespace(create=legacy_create)
    import app.controllers
    monkeypatch.setitem(sys.modules, 'app.controllers.post_controller', fake_controller)
    monkeypatch.setattr(app.controllers, 'post_controller', fake_controller, raising=False)
    main = importlib.import_module('main')
    monkeypatch.setenv('WEBHOOK_SECRET', 'offline-secret')
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    monkeypatch.setattr(sync_module().time, 'time', lambda: 1800000000)
    engine, posts = database(tmp_path)
    main.app.state.publication_inbox = sync_module().Inbox(engine, posts)
    with TestClient(main.app) as client:
        assert client.post('/post/', content=b'{bad').status_code == 401, 'authenticate before JSON parse'
        raw = event()
        headers = {'x-hook-signature': signature(raw)}
        assert client.post('/post/', content=raw, headers=headers).status_code == 503
        sync_module().provision(engine)
        assert client.post('/post/', content=raw, headers=headers).status_code == 204
        assert client.post('/post/', content=raw, headers=headers).status_code == 204
        assert calls == [], 'durable receiver must not invoke an LLM'
        assert client.post('/post/', content=b'x' * (256 * 1024 + 1)).status_code == 413
        assert client.post('/post/', content=b'{bad', headers={'x-hook-signature': signature(b'{bad')}).status_code == 400
        monkeypatch.delenv('PUBLICATION_SYNC_ENABLED')
        raw = event(updated_at=None)
        assert client.post('/post/', content=raw, headers={'x-hook-signature': signature(raw)}).status_code == 204
        assert len(calls) == 1
        assert calls[0] == ('a' * 24, 'Título', 'https://nucleo.jor.br/post/', 'Texto sintético')
        raw = event(visibility='members')
        assert client.post('/post/', content=raw, headers={'x-hook-signature': signature(raw)}).status_code == 204
        assert len(calls) == 1
    del main.app.state.publication_inbox


def test_shared_engine_never_echoes_content(monkeypatch):
    import importlib
    monkeypatch.setenv('DB_ENGINE', 'sqlite')
    monkeypatch.setenv('DB_DATABASE', ':memory:')
    for name in ('DB_HOST', 'DB_USERNAME', 'DB_PASSWORD', 'DB_PORT'):
        monkeypatch.delenv(name, raising=False)
    try:
        model = importlib.import_module('app.model')
    except TypeError:
        pytest.fail('shared engine must support isolated SQLite without incompatible pool options')
    assert model.engine.echo is False, 'SQL parameters must not log article content'
    with model.engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT 1').scalar() == 1


def test_worker_rejects_malformed_generation_and_fences_edit(tmp_path):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))

    async def malformed(_):
        return {'summary': 'not an array', 'summary_en': ['one'], 'title_en': ''}

    asyncio.run(sync.work_once(inbox, malformed, now=0))
    with engine.connect() as connection:
        assert connection.execute(select(posts)).first() is None, 'invalid output cannot enter GET contract'
    job = inbox.claim(now=10)
    inbox.enqueue(sync.normalize(event('2026-10-20T12:01:00Z', plaintext='Nova edição')))
    assert inbox.finish(job, asyncio.run(generated(json.loads(job['payload'])))) is False
    asyncio.run(sync.work_once(inbox, generated, now=20))
    with engine.connect() as connection:
        assert 'Nova edição' in connection.execute(select(posts.c.summary)).scalar_one()
    assert inbox.enqueue(sync.normalize(event('2026-10-20T12:02:00Z', plaintext='Nova edição'))) == 'queued'
    assert asyncio.run(sync.work_once(inbox, generated, now=21)) is False


def test_explicit_schema_cli_and_worker_opt_in(tmp_path):
    import os
    import subprocess
    sync = sync_module()
    assert importlib.util.find_spec('app.publication_cli') is not None, 'explicit CLI missing'
    from sqlalchemy import inspect
    engine, posts = database(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DB_', 'OPENAI_', 'PUBLICATION_'))}
    env.update(DB_ENGINE='sqlite', DB_DATABASE=engine.url.database, PYTHON_DOTENV_DISABLED='1')

    def cli(*arguments):
        return subprocess.run([sys.executable, '-m', 'app.publication_cli', *arguments],
                              cwd=Path(__file__).resolve().parents[1], env=env,
                              text=True, capture_output=True, timeout=10)

    assert cli('schema').returncode == 0
    assert inspect(engine).get_table_names() == ['posts']
    assert cli('schema', '--apply').returncode == 0
    assert inspect(engine).get_table_names() == ['posts', 'publication_inbox', 'publication_reconcile_cursor']
    assert cli('schema', '--apply').returncode == 0
    assert cli('worker', '--once').returncode != 0
    assert cli('worker', '--run', '--once').returncode != 0
    env['PUBLICATION_SYNC_ENABLED'] = '1'
    result = cli('worker', '--run', '--once')
    assert result.returncode == 0, result.stderr
    assert not result.stderr


def test_generation_adapter_translates_pt_en_without_llm(monkeypatch):
    sync = sync_module()
    assert importlib.util.find_spec('app.publication_generation') is not None, 'production generation adapter missing'
    import types
    prompts = []

    async def json_query(prompt, max_tries):
        assert max_tries == 1
        prompts.append(prompt)
        return json.dumps(['PT'] * 3 if len(prompts) == 1 else ['EN'] * 3)

    async def str_query(prompt):
        prompts.append(prompt)
        return 'English title'

    fake = types.SimpleNamespace(query_gpt_json=json_query, query_gpt_str=str_query)
    monkeypatch.setitem(sys.modules, 'app.controllers.post_controller', fake)
    from app.publication_generation import generate
    result = asyncio.run(generate(sync.normalize(event())))
    assert result == {'summary': ['PT'] * 3, 'summary_en': ['EN'] * 3, 'title_en': 'English title'}
    assert 'Texto sintético' in prompts[0]
    assert 'PT' in prompts[1]
    assert 'Título' in prompts[2]


def test_controller_lazy_client_bounded_calls_and_no_content_logs(monkeypatch, capsys):
    import types
    import importlib
    calls = []
    response = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content='["SYNTHETIC-CONTENT", "b", "c"]'))])

    def factory(**kwargs):
        calls.append(kwargs)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **kwargs: response)))

    monkeypatch.setitem(sys.modules, 'openai', types.SimpleNamespace(OpenAI=factory))
    controller = importlib.import_module('app.controllers.post_controller')
    assert calls == [], 'GET and startup must not initialize LLM clients'
    monkeypatch.setattr(controller, 'openai_client', None)
    asyncio.run(controller.query_gpt_json('SYNTHETIC-CONTENT', max_tries=1))
    assert calls == [{'api_key': None, 'timeout': 30.0, 'max_retries': 0}]
    assert 'SYNTHETIC-CONTENT' not in str(capsys.readouterr())


@pytest.mark.parametrize('transition', ['edit', 'private', 'unpublish', 'newsletter', 'bad-tags', 'tombstone'])
def test_signed_transition_immediately_hides_get_and_blocks_late_worker(tmp_path, monkeypatch, transition):
    import importlib
    from fastapi.testclient import TestClient
    sync = sync_module()
    main = importlib.import_module('main')
    model = importlib.import_module('app.model')
    controller = importlib.import_module('app.controllers.post_controller')
    import app.controllers
    monkeypatch.setattr(app.controllers, 'post_controller', controller, raising=False)
    engine, posts = database(tmp_path)
    monkeypatch.setattr(model, 'engine', engine)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    monkeypatch.setenv('WEBHOOK_SECRET', 'offline-secret')
    monkeypatch.setattr(sync.time, 'time', lambda: 1800000000)
    main.app.state.publication_inbox = inbox
    inbox.enqueue(sync.normalize(event()))
    # Original worker is still in flight; a recovered worker has published the ready summary.
    job = inbox.claim(now=1)
    recovered = inbox.claim(now=121)
    assert inbox.finish(recovered, asyncio.run(generated(json.loads(recovered['payload'])))) is True
    path = '/post/' + 'a' * 24
    with TestClient(main.app) as client:
        assert client.get(path).json() == {'summary': ['PT Texto sintético'] * 3, 'summary_en': ['EN Texto sintético'] * 3}
        assert set(client.get('/post/').json()[0]) == {'title', 'title_en', 'summary', 'summary_en', 'link', 'date'}
        changes = {'edit': {'plaintext': 'Atual'}, 'private': {'visibility': 'members'},
                   'unpublish': {'status': 'draft'}, 'newsletter': {'primary_tag': {'slug': 'daily-news'}},
                   'bad-tags': {'tags': [None]}}
        raw = event('2026-10-20T12:02:00Z', **changes.get(transition, {}))
        if transition == 'tombstone':
            # Ghost deletion envelope: no content remains; prior source revision is sufficient.
            raw = json.dumps({'event': 'post.deleted', 'post': {'current': None, 'previous': {
                'id': 'a' * 24, 'updated_at': '2026-10-20T12:01:00Z'}}}).encode()
        assert client.post('/post/', content=raw, headers={'x-ghost-signature': signature(raw)}).status_code == 204
        assert client.get(path).status_code == 404
        assert client.get('/post/').json() == []
        assert inbox.finish(job, asyncio.run(generated(json.loads(job['payload'])))) is False
        asyncio.run(sync.work_once(inbox, generated, now=3))
        assert client.get(path).status_code == (200 if transition == 'edit' else 404)
        assert inbox.enqueue(sync.normalize(event())) == 'stale'
    del main.app.state.publication_inbox


def test_retry_delay_starts_after_failed_generation(tmp_path, monkeypatch):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    clock = [100]
    monkeypatch.setattr(sync.time, 'time', lambda: clock[0])

    async def slow_failure(_):
        clock[0] = 160
        raise RuntimeError('synthetic')

    asyncio.run(sync.work_once(inbox, slow_failure))
    assert inbox.claim(now=169) is None, 'backoff must start at failure, not claim time'
    assert inbox.claim(now=170) is not None


def test_mysql_schema_and_transactional_rollback(tmp_path):
    sync = sync_module()
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects import mysql
    from sqlalchemy import inspect
    ddl = str(CreateTable(sync.inbox_table).compile(dialect=mysql.dialect()))
    assert 'LONGTEXT' in ddl and 'ENGINE=InnoDB' in ddl
    assert any(tuple(column.name for column in index.columns) == ('status', 'available_at')
               for index in sync.inbox_table.indexes), 'due-job scan needs a bounded-index access path'
    engine, posts = database(tmp_path)
    sync.provision(engine)
    posts.drop(engine)
    inbox = sync.Inbox(engine, posts)
    with pytest.raises(sync.Rejected):
        inbox.enqueue(sync.normalize(event()))
    with engine.connect() as connection:
        assert connection.execute(select(sync.inbox_table)).first() is None
    # The inbox is not registered in legacy Model.metadata.
    from app.model import Model
    assert 'publication_inbox' not in Model.metadata.tables
    assert inspect(engine).get_table_names() == ['publication_inbox', 'publication_reconcile_cursor']


def test_crash_retry_budget_and_equal_revision_tombstone_replay(tmp_path):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    first = sync.normalize(event())
    inbox.enqueue(first)
    assert inbox.claim(now=1, lease=1, max_attempts=2) is not None
    assert inbox.claim(now=2, lease=1, max_attempts=2) is not None
    assert inbox.claim(now=3, lease=1, max_attempts=2) is None
    with engine.connect() as connection:
        assert connection.execute(select(sync.inbox_table.c.status)).scalar_one() == 'dead'
    inbox.enqueue(sync.normalize(event(status='draft')))
    assert inbox.enqueue(first) == 'stale'
    assert inbox.claim(now=4) is None


def test_two_workers_cannot_claim_same_unexpired_job(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda _: inbox.claim(now=100), range(2)))
    assert sum(job is not None for job in jobs) == 1


def test_raw_hmac_fallback_and_timestamp_bounds():
    sync = sync_module()
    raw = b'{ "post": {} }'
    sync.authenticate(raw, {'x-hook-signature': signature(raw)}, 'offline-secret', now=1800000000)
    for headers, body, now in [
        ({'x-ghost-signature': signature(raw)}, raw.replace(b' ', b''), 1800000000),
        ({'x-ghost-signature': signature(raw)}, raw, 1800000400),
        ({'x-ghost-signature': signature(raw)}, raw, 1799999600),
        ({'x-ghost-signature': 'bad', 'x-hook-signature': signature(raw)}, raw, 1800000000),
        ({}, raw, 1800000000),
    ]:
        with pytest.raises(sync.Rejected):
            sync.authenticate(body, headers, 'offline-secret', now=now)
    for secret in ('', 'secret'):
        digest = hmac.new(secret.encode(), raw + b'1800000000000', hashlib.sha256).hexdigest()
        with pytest.raises(sync.Rejected) as failure:
            sync.authenticate(raw, {'x-hook-signature': f'sha256={digest}, t=1800000000000'}, secret, now=1800000000)
        assert failure.value.status == 503
