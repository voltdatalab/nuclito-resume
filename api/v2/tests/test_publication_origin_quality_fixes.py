"""Accidental wrong-database guards, not shared-database support; SQLite only."""
import asyncio
import json

import pytest
from sqlalchemy import select
from test_publication_sync import database, event, generated, sync_module

PRODUCTION = 'https://nucleo.jor.br'
STAGING = 'https://staging.nucleo.jor.br'


def snapshot(engine, *tables):
    with engine.connect() as conn:
        return [[dict(row) for row in conn.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                for table in tables]


def reject_or_return(sync, action):
    try:
        return action()
    except sync.Rejected:
        return None


@pytest.mark.parametrize('cursor_exists', [False, True])
@pytest.mark.parametrize('evidence', ['both', 'inbox', 'post'])
def test_reconcile_wrong_database_404_preserves_entire_state(tmp_path, monkeypatch, cursor_exists, evidence):
    from app.publication_reconcile import reconcile, cursor_table
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    asyncio.run(sync.work_once(inbox, generated, now=1))
    from sqlalchemy import delete, insert
    with engine.begin() as conn:
        if evidence == 'post':
            conn.execute(delete(sync.inbox_table))
        elif evidence == 'inbox':
            conn.execute(delete(posts))
        if cursor_exists:
            conn.execute(insert(cursor_table).values(name='ghost', page=2, after_id='', version=7))
    before = snapshot(engine, sync.inbox_table, posts, cursor_table)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)

    class EmptyStaging:
        def page(self, *args):
            return [], None
        def get(self, identity):
            return None

    reject_or_return(sync, lambda: reconcile(inbox, EmptyStaging()))
    assert snapshot(engine, sync.inbox_table, posts, cursor_table) == before
    engine.dispose()


@pytest.mark.parametrize('operation', ['tombstone', 'upsert', 'finish', 'fail', 'claim', 'expired'])
@pytest.mark.parametrize('evidence', ['inbox', 'post', 'both'])
def test_wrong_database_mutation_paths_preserve_every_column(tmp_path, monkeypatch, operation, evidence):
    from sqlalchemy import delete, update
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    job = inbox.claim(now=1)
    result = asyncio.run(generated(json.loads(job['payload'])))
    if operation not in ('finish', 'fail'):
        inbox.finish(job, result)
    with engine.begin() as conn:
        if operation in ('claim', 'expired'):
            conn.execute(update(sync.inbox_table).values(status='pending', attempts=5 if operation == 'expired' else 0,
                                                        token=None, available_at=0))
        if evidence == 'post':
            # A local-looking payload must never overwrite a foreign stored post.
            payload = json.loads(job['payload'])
            payload['url'] = STAGING + '/post/'
            conn.execute(update(sync.inbox_table).values(payload=json.dumps(payload)))
        elif evidence == 'inbox':
            conn.execute(delete(posts))
    before = snapshot(engine, sync.inbox_table, posts)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    actions = {
        'tombstone': lambda: inbox.enqueue(sync.normalize(event('2026-10-20T13:00:00Z', event='post.deleted', url=None))),
        'upsert': lambda: inbox.enqueue(sync.normalize(event('2026-10-20T13:00:00Z', url=STAGING + '/post/'))),
        'finish': lambda: inbox.finish(job, result),
        'fail': lambda: inbox.fail(job, now=2, max_attempts=5),
        'claim': lambda: inbox.claim(now=200),
        'expired': lambda: inbox.claim(now=200),
    }
    # For finish/fail a post-only conflict needs a real foreign stored post.
    if operation in ('finish', 'fail') and evidence == 'post':
        from sqlalchemy import insert
        with engine.begin() as conn:
            conn.execute(insert(posts).values(id='a' * 24, link=PRODUCTION + '/post/', title='foreign'))
        before = snapshot(engine, sync.inbox_table, posts)
    reject_or_return(sync, actions[operation])
    assert snapshot(engine, sync.inbox_table, posts) == before
    engine.dispose()


def test_foreign_worker_five_attempt_schedule_does_not_claim_or_mutate(tmp_path, monkeypatch):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    before = snapshot(engine, sync.inbox_table, posts)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    calls = []

    async def provider(item):
        calls.append(item)
        return await generated(item)

    observed = []
    for now in (1, 11, 31, 71, 151):
        reject_or_return(sync, lambda: asyncio.run(sync.work_once(inbox, provider, now=now)))
        observed.append(snapshot(engine, sync.inbox_table, posts))
    assert observed == [before] * 5
    assert calls == []
    engine.dispose()


@pytest.mark.parametrize('existing', ['missing', 'unknown', 'local', 'foreign'])
def test_urlless_tombstone_requires_verified_local_id(tmp_path, monkeypatch, existing):
    from sqlalchemy import insert
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    if existing != 'missing':
        link = {'unknown': None, 'local': STAGING + '/post/', 'foreign': PRODUCTION + '/post/'}[existing]
        with engine.begin() as conn:
            conn.execute(insert(posts).values(id='a' * 24, title='synthetic', link=link))
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    before = snapshot(engine, sync.inbox_table, posts)
    item = sync.normalize(event(event='post.deleted', url=None))
    if existing == 'local':
        assert inbox.enqueue(item) == 'queued'
        assert inbox.enqueue(item) == 'duplicate'
        assert snapshot(engine, posts) == [[]]
        # Retain verified evidence after deletion, including across config changes.
        after = snapshot(engine, sync.inbox_table, posts)
        monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', PRODUCTION)
        reject_or_return(sync, lambda: inbox.enqueue(sync.normalize(event())))
        assert snapshot(engine, sync.inbox_table, posts) == after
    else:
        with pytest.raises(sync.Rejected):
            inbox.enqueue(item)
        assert snapshot(engine, sync.inbox_table, posts) == before
    engine.dispose()


@pytest.mark.parametrize('shape', ['current', 'previous'])
def test_explicit_local_tombstone_retains_origin_without_prior_row(tmp_path, monkeypatch, shape):
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    body = json.loads(event(event='post.deleted', url=STAGING + '/post/'))
    if shape == 'previous':
        body['post'] = dict(current=None, previous=body['post']['current'])
    assert inbox.enqueue(sync.normalize(json.dumps(body).encode())) == 'queued'
    before = snapshot(engine, sync.inbox_table, posts)
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', PRODUCTION)
    reject_or_return(sync, lambda: inbox.enqueue(sync.normalize(event('2026-10-20T13:00:00Z'))))
    assert snapshot(engine, sync.inbox_table, posts) == before
    engine.dispose()


@pytest.mark.parametrize('status', ['pending', 'processing'])
def test_expiry_bulk_write_set_cannot_mutate_foreign_rows(tmp_path, monkeypatch, status):
    from sqlalchemy import update
    sync = sync_module()
    engine, posts = database(tmp_path)
    sync.provision(engine)
    inbox = sync.Inbox(engine, posts)
    inbox.enqueue(sync.normalize(event()))
    monkeypatch.setenv('PUBLICATION_SOURCE_ORIGIN', STAGING)
    inbox.enqueue(sync.normalize(event(id='b' * 24, url=STAGING + '/post/')))
    with engine.begin() as conn:
        conn.execute(update(sync.inbox_table).values(status=status, attempts=5,
                                                    token='synthetic-lease', available_at=1))
    before = snapshot(engine, sync.inbox_table, posts)
    with pytest.raises(sync.Rejected):
        inbox.claim(now=200)
    assert snapshot(engine, sync.inbox_table, posts) == before
    engine.dispose()
