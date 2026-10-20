"""Destructive fixtures: ONLY the fixed disposable CI MySQL service is admitted.

Kept outside tests/ so the offline SQLite runner never imports this harness.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

# Never import ambient production configuration or .env, even during collection.
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_DATABASE'] = ':memory:'
for name in ('DB_HOST', 'DB_PORT', 'DB_USERNAME', 'DB_PASSWORD'):
    os.environ.pop(name, None)

FIXTURE_DSN = 'mysql+mysqldb://root:fixture-root-only@127.0.0.1:3306/nuclito_ci'


def admitted_url():
    value = os.environ.get('NUCLITO_MYSQL_TEST_DSN')
    if value != FIXTURE_DSN:
        raise pytest.UsageError('MySQL gate requires the exact synthetic CI fixture DSN; no skips')
    return make_url(value)


def bounded_engine(url):
    engine = create_engine(url, hide_parameters=True, pool_size=4, max_overflow=0,
                           pool_timeout=5, connect_args={
                               'connect_timeout': 5, 'read_timeout': 8, 'write_timeout': 8})

    @event.listens_for(engine, 'connect')
    def bounds(dbapi, _):
        with dbapi.cursor() as cursor:
            cursor.execute('SET SESSION innodb_lock_wait_timeout = 2')
            cursor.execute('SET SESSION max_execution_time = 5000')
    return engine


@pytest.fixture(scope='session')
def mysql_admin():
    engine = bounded_engine(admitted_url())
    with engine.connect() as connection:
        version = connection.execute(text('SELECT VERSION()')).scalar_one()
        assert version.startswith('8.'), 'Gate requires MySQL 8, not MariaDB/SQLite'
        assert connection.execute(text('SELECT @@innodb_deadlock_detect')).scalar_one() == 1
    yield engine
    engine.dispose()


@pytest.fixture
def fixture_database(mysql_admin):
    """Each invocation owns a new schema, including missing-post-table tests."""
    name = 'nuclito_fixture_' + uuid.uuid4().hex
    with mysql_admin.begin() as connection:
        connection.exec_driver_sql('CREATE DATABASE `' + name + '` CHARACTER SET utf8mb4')
    engine = bounded_engine(mysql_admin.url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with mysql_admin.begin() as connection:
            connection.exec_driver_sql('DROP DATABASE `' + name + '`')


@pytest.fixture
def inbox(fixture_database):
    from app.models.posts import Post
    from app.publication_sync import Inbox, provision
    # This is the real production schema, never a test-side near-duplicate.
    Post.metadata.create_all(fixture_database)
    provision(fixture_database)
    return Inbox(fixture_database, Post.__table__)
