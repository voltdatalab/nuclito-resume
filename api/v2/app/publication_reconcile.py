"""Bounded, resumable reconciliation through the same versioned inbox.

Import is inert. Only explicit schema provision creates the cursor table.
Absence from a list page NEVER implies withdrawal; only authoritative GET 404 does.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import Table, MetaData, Column, String, Integer, BigInteger, select, insert, update, union
from app.publication_sync import inbox_table, normalize, Rejected

cursor_table = Table(
    'publication_reconcile_cursor', MetaData(),
    Column('name', String(32), primary_key=True),
    Column('page', Integer, nullable=False),
    Column('after_id', String(32), nullable=False),
    Column('version', BigInteger, nullable=False),
    mysql_engine='InnoDB',
)


def state(inbox, identity):
    with inbox.engine.connect() as conn:
        row = conn.execute(select(inbox_table.c.revision, inbox_table.c.digest).where(
            inbox_table.c.id == identity)).first()
        return tuple(row) if row else (None, None)


def reconcile(inbox, source, *, pages=1, known=20, page_size=20):
    if not 1 <= pages <= 10 or not 1 <= known <= 100 or not 1 <= page_size <= 100:
        raise Rejected()
    # Missing schema fails BEFORE CMS I/O. No implicit DDL here.
    with inbox.engine.begin() as conn:
        inbox.check_database_origin(conn)
        cursor = conn.execute(select(cursor_table).where(cursor_table.c.name == 'ghost')).mappings().first()
        if cursor is None:
            conn.execute(insert(cursor_table).values(name='ghost', page=1, after_id='', version=0))
            cursor = dict(page=1, after_id='', version=0)
    page, after = cursor['page'], cursor['after_id']
    counts = dict(pages=0, checked=0)
    for _ in range(pages):
        posts, next_page = source.page(page, page_size)
        if not isinstance(posts, list) or len(posts) > page_size:
            raise Rejected()
        if next_page is not None and (type(next_page) is not int or next_page != page + 1):
            raise Rejected()
        for post in posts:
            inbox.enqueue(normalize(json.dumps({'event': 'post.edited', 'post': {'current': post}}).encode()))
        counts['pages'] += 1
        page = next_page or 1
        if next_page is None:
            break  # A cycle is bounded even for an empty CMS.
    identities = union(select(inbox.posts.c.id.label('id')), select(inbox_table.c.id.label('id'))).subquery()
    with inbox.engine.connect() as conn:
        ids = conn.execute(select(identities.c.id).where(identities.c.id > after).order_by(
            identities.c.id).limit(known + 1)).scalars().all()
    for identity in ids[:known]:
        after = identity
        if not re.fullmatch(r'[0-9a-f]{24}', identity):
            continue  # Legacy non-Ghost identities remain hidden in new-mode reads.
        expected = state(inbox, identity)  # Fence 404 against events admitted during the GET.
        post = source.get(identity)
        if post is None:
            revision = expected[0] if expected[0] is not None else 0
            # Preserve the captured integer watermark without a float round-trip.
            stamp = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                microseconds=revision)).isoformat().replace('+00:00', 'Z')
            item = normalize(json.dumps({'event': 'post.deleted', 'post': {'current': {
                'id': identity, 'updated_at': stamp}}}).encode())
            inbox.enqueue(item, expected=expected)
        else:
            if not isinstance(post, dict) or post.get('id') != identity:
                raise Rejected()
            inbox.enqueue(normalize(json.dumps({'event': 'post.edited', 'post': {'current': post}}).encode()))
        counts['checked'] += 1
    if len(ids) <= known:
        after = ''
    with inbox.engine.begin() as conn:
        inbox.check_database_origin(conn)
        changed = conn.execute(update(cursor_table).where(
            cursor_table.c.name == 'ghost', cursor_table.c.version == cursor['version']).values(
                page=page, after_id=after, version=cursor['version'] + 1))
        if changed.rowcount != 1:
            raise Rejected(409)  # Concurrent run: replay is safe, never advance past unseen work.
    return counts
