"""Real InnoDB gates; no CMS, provider, SQL/schema doubles or SQLite fallbacks."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import event, insert, inspect, select, text, update
from sqlalchemy.exc import OperationalError

from app.models.posts import Post
from app.publication_sync import Inbox, Rejected, inbox_table, normalize, provision

pytestmark = pytest.mark.timeout(30)
RESULT = {'title_en': 'Synthetic title', 'summary': ['a', 'b', 'c'],
          'summary_en': ['d', 'e', 'f']}


def item(minute=0, event_name='post.edited', **changes):
    current = dict(id='a' * 24, updated_at=f'2026-10-20T12:{minute:02d}:00Z',
                   published_at='2026-10-19T12:00:00Z', title='Synthetic title',
                   url='https://nucleo.jor.br/synthetic-fixture/', plaintext='Synthetic body',
                   status='published', visibility='public', tags=[], primary_tag=None)
    current.update(changes)
    return normalize(json.dumps({'event': event_name, 'post': {'current': current}}).encode())


def row(inbox):
    with inbox.engine.connect() as connection:
        return dict(connection.execute(select(inbox_table)).mappings().one())


def parallel(functions):
    barrier = threading.Barrier(len(functions), timeout=5)

    def run(function):
        barrier.wait()
        return function()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        futures = [pool.submit(run, function) for function in functions]
        return [future.result(timeout=12) for future in futures]


def test_production_schema_and_explicit_provision_are_idempotent(inbox):
    assert inbox.posts is Post.__table__
    assert set(inspect(inbox.engine).get_table_names()) == {
        'posts', 'publication_inbox', 'publication_reconcile_cursor'}
    provision(inbox.engine)
    Post.metadata.create_all(inbox.engine)
    with inbox.engine.connect() as connection:
        engines = connection.execute(text(
            'SELECT ENGINE FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE()')).scalars().all()
    assert set(engines) == {'InnoDB'}
    assert inbox.enqueue(item()) == 'queued'
    assert inbox.finish(inbox.claim(now=1), RESULT) is True
    assert inbox.read_verified(identity='a' * 24) == {
        'summary': RESULT['summary'], 'summary_en': RESULT['summary_en']}


def test_concurrent_duplicate_delivery_has_one_durable_revision(inbox):
    outcomes = parallel([lambda: inbox.enqueue(item()) for _ in range(2)])
    assert sorted(outcomes) == ['duplicate', 'queued']
    assert row(inbox)['attempts'] == 0
    with inbox.engine.connect() as connection:
        assert len(connection.execute(select(inbox_table)).all()) == 1


def test_concurrent_claims_have_exactly_one_owner(inbox):
    inbox.enqueue(item())
    jobs = parallel([lambda: inbox.claim(now=1) for _ in range(2)])
    owners = [job for job in jobs if job is not None]
    assert len(owners) == 1
    assert row(inbox)['token'] == owners[0]['token']
    assert row(inbox)['attempts'] == 1


@pytest.mark.parametrize('concurrent', [False, True])
def test_identical_digest_advances_watermark_preserving_final_claim(inbox, concurrent):
    first = item()
    later = item(1)
    assert first['digest'] == later['digest']
    inbox.enqueue(first)
    for now in range(1, 6):
        job = inbox.claim(now=now, lease=1)
    assert job['attempts'] == 5
    if concurrent:
        outcomes = parallel([lambda: inbox.enqueue(later), lambda: inbox.finish(job, RESULT)])
        assert outcomes == ['queued', True]
    else:
        assert inbox.enqueue(later) == 'queued'
        assert row(inbox)['token'] == job['token']
        assert inbox.finish(job, RESULT) is True
    assert row(inbox)['revision'] == later['revision']
    assert row(inbox)['status'] == 'done'
    assert inbox.enqueue(first) == 'stale'
    assert inbox.enqueue(later) == 'duplicate'


@pytest.mark.parametrize('changes', [{'plaintext': 'Changed body'},
                                      {'visibility': 'members'}, {'status': 'draft'},
                                      {'event_name': 'post.deleted'}, {'event_name': 'post.unpublished'}])
def test_edit_or_revoke_fences_late_finish_and_fail(inbox, changes):
    inbox.enqueue(item())
    old = inbox.claim(now=1)
    newer = item(1, **changes)
    inbox.enqueue(newer)
    assert inbox.finish(old, RESULT) is False
    before = row(inbox)
    inbox.fail(old, now=2, max_attempts=5)
    assert row(inbox) == before
    assert inbox.read_verified(identity='a' * 24) is None
    if newer['eligible']:
        fresh = inbox.claim(now=2)
        assert fresh['token'] != old['token']
        assert inbox.finish(fresh, RESULT) is True
    else:
        assert row(inbox)['status'] == 'suppressed'
        assert inbox.claim(now=500) is None
        assert inbox.enqueue(item()) == 'stale'


def test_restart_reclaims_expired_lease_and_fences_original_owner(inbox):
    inbox.enqueue(item())
    environment = dict(os.environ, NUCLITO_MYSQL_RESTART_URL=inbox.engine.url.render_as_string(hide_password=False))
    child = subprocess.run([sys.executable, '-c',
                            "import json,os; from sqlalchemy.engine import make_url; "
                            "from mysql_tests.conftest import bounded_engine; "
                            "from app.models.posts import Post; from app.publication_sync import Inbox; "
                            "engine=bounded_engine(make_url(os.environ['NUCLITO_MYSQL_RESTART_URL'])); "
                            "job=Inbox(engine,Post.__table__).claim(now=1,lease=2); "
                            "print(json.dumps(job),flush=True); os._exit(0)"],
                           env=environment, capture_output=True, text=True, timeout=10, check=True)
    old = json.loads(child.stdout)
    assert old is not None
    inbox.engine.dispose()  # The claiming process exited without graceful cleanup.
    restarted = Inbox(inbox.engine, Post.__table__)
    assert restarted.claim(now=2) is None
    fresh = restarted.claim(now=3, lease=2)
    assert fresh['attempts'] == 2
    assert fresh['token'] != old['token']
    assert restarted.finish(old, RESULT) is False
    assert restarted.finish(fresh, RESULT) is True
    restarted.fail(old, now=4, max_attempts=5)
    assert row(restarted)['status'] == 'done'


def test_finish_failure_rolls_back_delete_insert_and_ack(inbox):
    inbox.enqueue(item())
    job = inbox.claim(now=1)
    # A pre-existing materialized row proves DELETE and INSERT both roll back.
    original = dict(id='a' * 24, title='Before', title_en='Before',
                    link='https://nucleo.jor.br/before/', summary='["before"]',
                    summary_en='["before"]')
    with inbox.engine.begin() as connection:
        connection.execute(insert(Post.__table__).values(**original))
        before_post = dict(connection.execute(select(Post.__table__)).mappings().one())
    before_inbox = row(inbox)
    reached = []

    def abort_ack(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('UPDATE publication_inbox'):
            reached.append(True)
            raise OperationalError('synthetic rollback fault', {}, Exception('fixture'))

    event.listen(inbox.engine, 'before_cursor_execute', abort_ack)
    try:
        with pytest.raises(OperationalError):
            inbox.finish(job, RESULT)
    finally:
        event.remove(inbox.engine, 'before_cursor_execute', abort_ack)
    assert reached == [True]
    assert row(inbox) == before_inbox
    with inbox.engine.connect() as connection:
        assert dict(connection.execute(select(Post.__table__)).mappings().one()) == before_post
    assert inbox.finish(job, RESULT) is True


def test_missing_post_table_fails_closed_without_partial_enqueue(fixture_database):
    # A separate fresh database: never drop the shared happy-path Post table.
    provision(fixture_database)
    assert 'posts' not in inspect(fixture_database).get_table_names()
    inbox = Inbox(fixture_database, Post.__table__)
    with pytest.raises(Rejected) as failure:
        inbox.enqueue(item())
    assert failure.value.status == 503
    with fixture_database.connect() as connection:
        assert connection.execute(select(inbox_table)).all() == []
    with pytest.raises(Rejected) as failure:
        inbox.read_verified(identity='a' * 24)
    assert failure.value.status == 503


def test_real_lock_timeout_is_finite_sanitized_and_retryable(inbox):
    inbox.enqueue(item())
    before = row(inbox)
    with inbox.engine.connect() as blocker:
        transaction = blocker.begin()
        blocker.execute(select(inbox_table).with_for_update()).all()
        started = time.monotonic()
        try:
            with pytest.raises(Rejected) as failure:
                inbox.enqueue(item(1, plaintext='Timeout fixture'))
            elapsed = time.monotonic() - started
            assert failure.value.status == 503
            assert str(failure.value) == 'Publication request rejected'
            assert elapsed < 8
        finally:
            transaction.rollback()
    assert row(inbox) == before
    assert inbox.enqueue(item(1, plaintext='Timeout fixture')) == 'queued'


def test_real_deadlock_has_one_victim_and_no_partial_transaction(inbox):
    inbox.enqueue(item())
    inbox.enqueue(item(id='b' * 24))
    barrier = threading.Barrier(2, timeout=5)

    def contender(first, second):
        try:
            with inbox.engine.begin() as connection:
                connection.execute(update(inbox_table).where(inbox_table.c.id == first).values(attempts=1))
                barrier.wait()
                connection.execute(update(inbox_table).where(inbox_table.c.id == second).values(attempts=2))
            return 'committed'
        except OperationalError as error:
            assert error.orig.args[0] == 1213  # An actual InnoDB deadlock, not a stub/timeout.
            return 'deadlock'

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(contender, 'a' * 24, 'b' * 24),
                   pool.submit(contender, 'b' * 24, 'a' * 24)]
        outcomes = [future.result(timeout=12) for future in futures]
    assert sorted(outcomes) == ['committed', 'deadlock']
    assert time.monotonic() - started < 12
    with inbox.engine.connect() as connection:
        attempts = connection.execute(select(inbox_table.c.attempts)).scalars().all()
    assert sorted(attempts) == [1, 2]
    assert inbox.claim(now=1) is not None
