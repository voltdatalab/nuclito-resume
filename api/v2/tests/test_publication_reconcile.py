"""Offline authoritative reconciliation proofs (no real CMS, credentials or DB)."""
import json
import pytest
from sqlalchemy import insert, select, inspect
from test_publication_sync import database, event, sync_module


def test_reconcile_no_apply_has_no_import_or_io(monkeypatch, capsys):
    from app.publication_cli import main
    monkeypatch.delenv('PUBLICATION_SYNC_ENABLED', raising=False)
    assert main(['reconcile']) == 0
    assert 'No changes' in capsys.readouterr().out


def test_bounded_scan_persist_restart_and_cyclic_known_legacy_checks(tmp_path):
    from app.publication_reconcile import reconcile, cursor_table
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    assert 'publication_reconcile_cursor' in inspect(engine).get_table_names()
    inbox = sync.Inbox(engine, posts)
    legacy = 'b' * 24
    with engine.begin() as conn:
        conn.execute(insert(posts).values(id=legacy, title='legacy', link='https://nucleo.jor.br/legacy/'))
    current = json.loads(event())['post']['current']

    class Source:
        def __init__(self):
            self.calls = []
        def page(self, page, limit):
            self.calls.append(('page', page, limit))
            return ([current], 2) if page == 1 else ([], None)
        def get(self, identity):
            self.calls.append(('id', identity))
            return current if identity == current['id'] else None

    source = Source()
    assert reconcile(inbox, source, pages=1, known=1, page_size=10)['pages'] == 1
    with engine.connect() as conn:
        cursor = conn.execute(select(cursor_table)).mappings().one()
    assert cursor['page'] == 2
    assert cursor['after_id'] == current['id']
    # A new reconciler instance resumes both independent cursors.
    reconcile(sync.Inbox(engine, posts), source, pages=1, known=1, page_size=10)
    with engine.connect() as conn:
        cursor = conn.execute(select(cursor_table)).mappings().one()
        row = conn.execute(select(sync.inbox_table).where(sync.inbox_table.c.id == legacy)).mappings().one()
        assert conn.execute(select(posts).where(posts.c.id == legacy)).first() is None
    assert row['status'] == 'suppressed'
    assert cursor['page'] == 1
    assert ('id', legacy) in source.calls
    reconcile(inbox, source, pages=1, known=1)
    assert source.calls.count(('id', current['id'])) == 2


def test_404_race_stale_pages_and_partial_absence_never_revert(tmp_path):
    from app.publication_reconcile import reconcile, cursor_table
    from test_publication_sync import generated
    import asyncio
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    asyncio.run(sync.work_once(inbox, generated, now=1))
    second = 'b' * 24
    inbox.enqueue(sync.normalize(event(id=second)))
    asyncio.run(sync.work_once(inbox, generated, now=2))
    newer = sync.normalize(event('2026-10-20T13:00:00.000001Z', plaintext='Latest'))

    class Source:
        def page(self, page, limit):
            return [], None  # Missing here is NOT authoritative absence.
        def get(self, identity):
            assert identity == 'a' * 24
            inbox.enqueue(newer)  # Webhook races a slow authoritative 404.
            return None

    reconcile(inbox, Source(), pages=1, known=1)
    with engine.connect() as conn:
        row = conn.execute(select(sync.inbox_table).where(sync.inbox_table.c.id == 'a' * 24)).mappings().one()
        assert row['revision'] == newer['revision'] and row['status'] == 'pending'
        assert conn.execute(select(posts).where(posts.c.id == second)).first() is not None
    # Restart scan from beginning, but source now returns an obsolete public snapshot.
    with engine.begin() as conn:
        conn.execute(cursor_table.update().values(after_id=''))
    class Stale(Source):
        def page(self, page, limit):
            return [json.loads(event())['post']['current']], None
        def get(self, identity):
            return json.loads(event())['post']['current']
    reconcile(inbox, Stale(), pages=1, known=1)
    with engine.connect() as conn:
        assert conn.execute(select(sync.inbox_table.c.revision).where(
            sync.inbox_table.c.id == 'a' * 24)).scalar_one() == newer['revision']


@pytest.mark.parametrize('stamp', [
    '2300-01-01T00:00:00.000012Z',
    '2026-10-20T12:00:00.123457Z',
])
def test_authoritative_404_preserves_exact_revision_and_hides_ready_summary(tmp_path, stamp):
    from app.publication_reconcile import reconcile
    from test_publication_sync import generated
    import asyncio
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    item = sync.normalize(event(stamp, event='post.published'))
    assert inbox.enqueue(item) == 'queued'
    job = inbox.claim(now=1)
    assert job is not None
    assert inbox.finish(job, asyncio.run(generated(json.loads(job['payload'])))) is True
    assert inbox.read_verified(identity=item['id']) is not None

    class Source:
        def page(self, page, limit):
            return [], None
        def get(self, identity):
            assert identity == item['id']
            return None

    assert reconcile(inbox, Source()) == {'pages': 1, 'checked': 1}
    assert inbox.read_verified(identity=item['id']) is None
    with engine.connect() as conn:
        row = conn.execute(select(sync.inbox_table)).mappings().one()
        assert row['revision'] == item['revision']
        assert row['status'] == 'suppressed'
        assert conn.execute(select(posts)).first() is None
    assert inbox.enqueue(item) == 'stale'  # Equal-watermark replay cannot resurrect it.


def test_reconcile_schema_failure_and_source_errors_do_not_advance_or_suppress(tmp_path):
    from app.publication_reconcile import reconcile, cursor_table
    sync = sync_module()
    engine, posts = database(tmp_path)
    inbox = sync.Inbox(engine, posts)
    class Forbidden:
        def page(self, *args):
            pytest.fail('schema must fail before CMS access')
    with pytest.raises(Exception):
        reconcile(inbox, Forbidden())
    assert inspect(engine).get_table_names() == ['posts']
    sync.provision(engine)
    inbox.enqueue(sync.normalize(event()))
    class Unavailable:
        def page(self, *args):
            return [], None
        def get(self, identity):
            raise sync.Rejected(503)  # 401/timeout/invalid JSON never becomes 404.
    with pytest.raises(sync.Rejected):
        reconcile(inbox, Unavailable())
    with engine.connect() as conn:
        assert conn.execute(select(sync.inbox_table.c.status)).scalar_one() == 'pending'
        cursor = conn.execute(select(cursor_table)).mappings().one()
        assert cursor['version'] == 0 and cursor['after_id'] == '' and cursor['page'] == 1


def test_reconcile_suppression_fences_workers_and_newer_republish(tmp_path):
    from app.publication_reconcile import reconcile
    from test_publication_sync import generated
    import asyncio
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    job = inbox.claim(now=1)
    class Source:
        def page(self, *args):
            return [], None
        def get(self, identity):
            return None
    reconcile(inbox, Source())
    assert inbox.finish(job, asyncio.run(generated(json.loads(job['payload'])))) is False
    assert inbox.enqueue(sync.normalize(event())) == 'stale'
    assert inbox.enqueue(sync.normalize(event('2026-10-20T14:00:00Z'))) == 'queued'


def test_reconcile_enrolls_legacy_public_same_versioned_flow(tmp_path):
    from app.publication_reconcile import reconcile
    from test_publication_sync import generated
    import asyncio
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    with engine.begin() as conn:
        conn.execute(insert(posts).values(id='a' * 24, title='legacy'))
    class Source:
        def page(self, *args):
            return [], None
        def get(self, identity):
            return json.loads(event(published_at='2026-09-01T00:00:00Z'))['post']['current']
    reconcile(inbox, Source())
    assert inbox.read_verified(identity='a' * 24) is None
    asyncio.run(sync.work_once(inbox, generated, now=1))
    assert inbox.read_verified(identity='a' * 24)['summary'] == ['PT Texto sintético'] * 3


def test_apply_cli_offline_wiring_and_opt_in(tmp_path, monkeypatch, capsys):
    from app.publication_cli import main
    from app import model, publication_source
    engine, posts = database(tmp_path)
    sync_module().provision(engine)
    monkeypatch.setattr(model, 'engine', engine)
    with engine.begin() as conn:
        conn.execute(insert(posts).values(id='a' * 24, title='legacy', link='https://nucleo.jor.br/legacy/'))
    calls = []
    class Source:
        def __init__(self, origin, key):
            assert origin == 'https://nucleo.jor.br' and key == 'synthetic-test-key'
        def page(self, page, limit):
            calls.append(('page', page, limit))
            return [], None
        def get(self, identity):
            calls.append(('id', identity))
            return None
    monkeypatch.setattr(publication_source, 'GhostAdmin', Source)
    monkeypatch.setenv('PUBLICATION_GHOST_ADMIN_ORIGIN', 'https://nucleo.jor.br')
    monkeypatch.setenv('PUBLICATION_GHOST_ADMIN_KEY', 'synthetic-test-key')
    monkeypatch.delenv('PUBLICATION_SYNC_ENABLED', raising=False)
    with pytest.raises(SystemExit):
        main(['reconcile', '--apply'])
    assert calls == []
    monkeypatch.setenv('PUBLICATION_SYNC_ENABLED', '1')
    with pytest.raises(SystemExit):
        main(['reconcile', '--apply', '--pages', '11'])
    assert calls == []
    assert main(['reconcile', '--apply', '--pages', '1', '--known', '1', '--page-size', '2']) == 0
    assert calls == [('page', 1, 2), ('id', 'a' * 24)]
    with engine.connect() as conn:
        assert conn.execute(select(sync_module().inbox_table.c.status)).scalar_one() == 'suppressed'
        assert conn.execute(select(posts)).first() is None
    assert 'synthetic-test-key' not in str(capsys.readouterr())
