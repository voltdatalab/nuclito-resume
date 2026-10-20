"""Publication boundary and durable latest-revision inbox. No network at import."""
import hashlib
import hmac
import re
import time
import json
import os
from datetime import datetime, timezone
from app.publication_origin import source_origins
from sqlalchemy import (MetaData, Table, Column, String, Text, BigInteger, Integer, Index,
                        select, insert, update, delete)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.exc import SQLAlchemyError, IntegrityError


inbox_table = Table(
    'publication_inbox', MetaData(),
    Column('id', String(32), primary_key=True),
    Column('revision', BigInteger, nullable=False),
    Column('digest', String(64), nullable=False),
    Column('payload', Text().with_variant(LONGTEXT(), 'mysql'), nullable=False),
    Column('status', String(16), nullable=False),
    Column('attempts', Integer, nullable=False),
    Column('available_at', BigInteger, nullable=False),
    Column('token', String(32), nullable=True),
    Index('ix_publication_due', 'status', 'available_at'),
    mysql_engine='InnoDB',
)


def provision(engine):
    """Explicit CLI only. Never called by runtime or model metadata.create_all."""
    from app.publication_reconcile import cursor_table
    inbox_table.create(engine, checkfirst=True)
    cursor_table.create(engine, checkfirst=True)


class _Contended(Exception):
    pass


class Inbox:
    def __init__(self, engine, posts):
        self.engine = engine
        self.posts = posts

    def local_evidence(self, connection, identity):
        """Lock and validate every known URL for this ID before a mutation.

        Unknown legacy origin is not proof of membership. This is a wrong-DB
        tripwire, not a namespace or support for shared databases.
        """
        row = connection.execute(select(inbox_table).where(
            inbox_table.c.id == identity).with_for_update()).mappings().first()
        post = connection.execute(select(self.posts.c.link).where(
            self.posts.c.id == identity).with_for_update()).first()
        try:
            urls = [json.loads(row['payload']).get('url')] if row else []
            if post:
                urls.append(post.link)
            known = [canonical_url(url) for url in urls if url is not None]
            return known[0] if known else None
        except (ValueError, TypeError, AttributeError, KeyError):
            raise Rejected() from None

    def check_database_origin(self, connection):
        """Do not create/advance the unnamespaced cursor in a known wrong DB."""
        identities = set(connection.execute(select(inbox_table.c.id)).scalars())
        identities.update(connection.execute(select(self.posts.c.id)).scalars())
        for identity in sorted(identities):
            self.local_evidence(connection, identity)

    def read_verified(self, *, identity=None, page=0, amount=6):
        """Only completed current inbox versions are readable in the new mode."""
        query = select(self.posts).join(inbox_table, self.posts.c.id == inbox_table.c.id).where(
            inbox_table.c.status == 'done')
        if identity is not None:
            query = query.where(self.posts.c.id == identity)
        else:
            query = query.order_by(self.posts.c.timestamp.desc(), self.posts.c.id).limit(amount).offset(page * amount)
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(query).mappings().all()
            for row in rows:
                canonical_url(row['link'])
            if identity is not None:
                return ({'summary': json.loads(rows[0]['summary']),
                         'summary_en': json.loads(rows[0]['summary_en'])} if rows else None)
            return [dict(title=r['title'], title_en=r['title_en'], link=r['link'],
                         summary=json.loads(r['summary']), summary_en=json.loads(r['summary_en']),
                         date=r['timestamp'].strftime('%d.%b.%Y')) for r in rows]
        except (SQLAlchemyError, ValueError, TypeError):
            raise Rejected(503) from None

    def claim(self, *, now, lease=120, max_attempts=5):
        import uuid
        with self.engine.begin() as connection:
            # Validate the entire bulk-expiry write set before changing any row.
            expired = connection.execute(select(inbox_table.c.id).where(
                inbox_table.c.status.in_(['pending', 'processing']),
                inbox_table.c.available_at <= now,
                inbox_table.c.attempts >= max_attempts).with_for_update()).scalars().all()
            for identity in expired:
                if self.local_evidence(connection, identity) is None:
                    raise Rejected()
            connection.execute(update(inbox_table).where(
                inbox_table.c.id.in_(expired)).values(status='dead', token=None))
            row = connection.execute(select(inbox_table).where(
                inbox_table.c.status.in_(['pending', 'processing']),
                inbox_table.c.available_at <= now, inbox_table.c.attempts < max_attempts
            ).order_by(inbox_table.c.available_at, inbox_table.c.id).limit(1).with_for_update()).mappings().first()
            if not row:
                return None
            if self.local_evidence(connection, row['id']) is None:
                raise Rejected()
            token = uuid.uuid4().hex
            changed = connection.execute(update(inbox_table).where(
                inbox_table.c.id == row['id'], inbox_table.c.revision == row['revision'],
                inbox_table.c.status == row['status'], inbox_table.c.token == row['token']
            ).values(status='processing', token=token, attempts=row['attempts'] + 1,
                     available_at=now + lease))
            if changed.rowcount != 1:
                return None
            return dict(row, token=token, attempts=row['attempts'] + 1)

    def fail(self, job, *, now, max_attempts):
        with self.engine.begin() as connection:
            if self.local_evidence(connection, job['id']) is None:
                raise Rejected()
            connection.execute(update(inbox_table).where(
                inbox_table.c.id == job['id'], inbox_table.c.digest == job['digest'],
                inbox_table.c.token == job['token'], inbox_table.c.status == 'processing'
            ).values(status='dead' if job['attempts'] >= max_attempts else 'pending',
                     available_at=now + min(10 * 2 ** (job['attempts'] - 1), 3600), token=None))

    def finish(self, job, result):
        if not isinstance(result, dict) or not isinstance(result.get('title_en'), str) or not result['title_en'].strip():
            raise Rejected()
        for key in ('summary', 'summary_en'):
            points = result.get(key)
            if not isinstance(points, list) or len(points) != 3 or not all(
                    isinstance(point, str) and point.strip() for point in points):
                raise Rejected()
        with self.engine.begin() as connection:
            if self.local_evidence(connection, job['id']) is None:
                raise Rejected()
            row = connection.execute(select(inbox_table).where(
                inbox_table.c.id == job['id']).with_for_update()).mappings().one()
            if (row['status'] != 'processing' or row['token'] != job['token']
                    or row['digest'] != job['digest']):
                return False
            item = json.loads(row['payload'])
            canonical_url(item['url'])
            values = dict(title=item['title'], title_en=result['title_en'], link=item['url'],
                          summary=json.dumps(result['summary'], ensure_ascii=False),
                          summary_en=json.dumps(result['summary_en'], ensure_ascii=False),
                          timestamp=datetime.fromtimestamp(item.get('published_at', item['revision']) / 1000000, timezone.utc).replace(tzinfo=None))
            connection.execute(delete(self.posts).where(self.posts.c.id == job['id']))
            connection.execute(insert(self.posts).values(id=job['id'], **values))
            connection.execute(update(inbox_table).where(inbox_table.c.id == job['id']).values(
                status='done', token=None))
            return True

    def enqueue(self, item, *, expected=None):
        for _ in range(3):
            try:
                with self.engine.begin() as connection:
                    known_url = self.local_evidence(connection, item['id'])
                    item = dict(item)
                    if item.get('url') is None:
                        if known_url is None:
                            raise Rejected()
                        item['url'] = known_url
                    try:
                        canonical_url(item['url'])
                    except (ValueError, TypeError, AttributeError):
                        raise Rejected() from None
                    row = connection.execute(select(inbox_table).where(
                        inbox_table.c.id == item['id']).with_for_update()).mappings().first()
                    if expected is not None and (tuple((row['revision'], row['digest'])) if row else (None, None)) != expected:
                        return 'stale'
                    if row:
                        if item['revision'] < row['revision']:
                            return 'stale'
                        if item['revision'] == row['revision']:
                            if item['digest'] == row['digest']:
                                return 'duplicate'
                            if row['status'] == 'suppressed':
                                return 'stale'  # Same-revision public replay cannot resurrect a tombstone.
                            if item['eligible']:
                                raise Rejected(409)
                            # Privacy/deletion wins an ambiguous equal-revision tie.
                    values = dict(revision=item['revision'], digest=item['digest'],
                                  payload=json.dumps(item, ensure_ascii=False),
                                  status='pending' if item['eligible'] else 'suppressed',
                                  attempts=0, available_at=0, token=None)
                    if row:
                        if row['digest'] == item['digest']:
                            values.update(status=row['status'], attempts=row['attempts'],
                                          available_at=row['available_at'], token=row['token'])
                        changed = connection.execute(update(inbox_table).where(
                            inbox_table.c.id == item['id'],
                            inbox_table.c.revision == row['revision']).values(**values))
                        if changed.rowcount != 1:
                            raise _Contended()
                    else:
                        connection.execute(insert(inbox_table).values(id=item['id'], **values))
                    if not row or row['digest'] != item['digest']:
                        connection.execute(delete(self.posts).where(self.posts.c.id == item['id']))
                    return 'queued'
            except (IntegrityError, _Contended):
                continue
            except SQLAlchemyError:
                raise Rejected(503) from None
        raise Rejected(503)


async def work_once(inbox, generate, *, now=None, max_attempts=5):
    fixed_clock = now is not None
    now = int(time.time()) if now is None else now
    job = inbox.claim(now=now, max_attempts=max_attempts)
    if job is None:
        return False
    try:
        item = json.loads(job['payload'])
        canonical_url(item['url'])  # Check durable jobs again before any provider call.
        result = await generate(item)
        inbox.finish(job, result)
    except Exception:
        inbox.fail(job, now=now if fixed_clock else int(time.time()), max_attempts=max_attempts)
    return True


def utc_revision(value, *, strict=True):
    if strict and not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value):
        raise ValueError()
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError()
    delta = stamp.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def canonical_url(value):
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or 'https://' + parsed.netloc not in source_origins()
            or '?' in value or '#' in value or not parsed.path.startswith('/')
            or not parsed.path.endswith('/') or '\\' in value or '%' in value
            or any(ord(c) <= 32 for c in value) or '//' in parsed.path
            or any(part in {'.', '..'} for part in parsed.path.split('/'))):
        raise ValueError()
    return value


def normalize(raw, *, require_revision=True):
    if len(raw) > 256 * 1024:
        raise Rejected(413)
    try:
        source_origins()  # Reject invalid trusted config even for contentless tombstones.
        body = json.loads(raw)
        event = body.get('event')
        if require_revision and event not in {'post.published', 'post.published.edited', 'post.edited', 'post.unpublished', 'post.deleted'}:
            raise ValueError()
        envelope = body['post']
        current = envelope['current']
        if current is None:
            previous = envelope['previous']
            current = {'id': previous['id'],
                       'url': previous.get('url'),
                       'updated_at': previous.get('deleted_at') or previous['updated_at'],
                       'status': 'deleted', 'visibility': None}
        identity = current['id']
        if not isinstance(identity, str) or not re.fullmatch(
                r'[0-9a-f]{24}' if require_revision else r'[a-zA-Z0-9_-]{1,32}', identity):
            raise ValueError()
        stamp_value = current.get('updated_at')
        if not require_revision and stamp_value is None:
            revision = 0  # Legacy calls do not participate in revision ordering.
        else:
            revision = utc_revision(stamp_value, strict=require_revision)
        primary = current.get('primary_tag')
        tags = current.get('tags', [])
        valid_tags = isinstance(tags, list) and all(isinstance(t, dict) and isinstance(t.get('slug'), str) for t in tags)
        valid_primary = primary is None or (isinstance(primary, dict) and isinstance(primary.get('slug'), str))
        newsletter = valid_primary and primary is not None and primary['slug'].endswith('news')
        eligible = (event not in {'post.deleted', 'post.unpublished'}
                    and current.get('status') == 'published' and current.get('visibility') == 'public'
                    and valid_tags and valid_primary and not newsletter)
        payload = {'id': identity, 'revision': revision, 'eligible': eligible}
        strict_origin = require_revision or 'PUBLICATION_SOURCE_ORIGIN' in os.environ
        # Every supplied envelope URL is evidence of origin, even when a
        # minimal current tombstone has no URL of its own.
        for supplied in (envelope.get('current'), envelope.get('previous')):
            if supplied is None or supplied.get('url') is None:
                continue
            if strict_origin:
                canonical_url(supplied['url'])
                if not eligible:
                    payload['url'] = supplied['url']
            else:
                # Preserve the explicit OFF-mode arbitrary-URL legacy contract,
                # but never let that compatibility path ingest staging.
                from urllib.parse import urlsplit
                host = urlsplit(supplied['url']).hostname or ''
                if host == 'staging.nucleo.jor.br' or host.endswith('.staging.nucleo.jor.br'):
                    raise ValueError()
        if eligible:
            for key, limit in [('title', 1000), ('plaintext', 200000), ('html', 200000)]:
                if key in current and (not isinstance(current[key], str) or len(current[key]) > limit):
                    raise ValueError()
            for key in ('title', 'url', 'plaintext'):
                value = current[key]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError()
                payload[key] = value
            if len(payload['url']) > 256:
                raise ValueError()
            if current.get('published_at') is not None:
                payload['published_at'] = utc_revision(current['published_at'], strict=require_revision)
        payload['digest'] = hashlib.sha256(json.dumps(
            {k: v for k, v in payload.items() if k != 'revision'},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return payload
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Rejected() from None


class Rejected(Exception):
    """Sanitized boundary error; never attach body, headers or database errors."""
    def __init__(self, status=400):
        self.status = status
        super().__init__('Publication request rejected')


def authenticate(raw, headers, secret, *, now=None):
    if not secret or secret == 'secret':  # Reject the public Dockerfile placeholder.
        raise Rejected(503)
    header = headers.get('x-ghost-signature') or headers.get('x-hook-signature', '')
    match = re.fullmatch(r'sha256=([0-9a-fA-F]{64}),\s*t=([0-9]{13})', header)
    if not match:
        raise Rejected(401)
    digest, timestamp = match.groups()
    now = time.time() if now is None else now
    if abs(now - int(timestamp) / 1000) > 300:
        raise Rejected(401)
    expected = hmac.new(secret.encode(), raw + timestamp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest.lower()):
        raise Rejected(401)
