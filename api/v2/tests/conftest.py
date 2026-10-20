"""Test process is always offline and never inherits production DB configuration."""
import socket
import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
    monkeypatch.setenv('DB_ENGINE', 'sqlite')
    monkeypatch.setenv('DB_DATABASE', ':memory:')
    for name in ('DB_HOST', 'DB_PORT', 'DB_USERNAME', 'DB_PASSWORD', 'OPENAI_API_KEY',
                 'PUBLICATION_SOURCE_ORIGIN', 'PUBLICATION_GHOST_ADMIN_ORIGIN', 'PUBLICATION_GHOST_ADMIN_KEY'):
        monkeypatch.delenv(name, raising=False)
    original = socket.socket.connect

    def offline(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError('network forbidden in offline integration')
        return original(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', offline)
