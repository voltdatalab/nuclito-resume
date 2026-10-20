"""Transport/security tests: synthetic Admin API responses, never a real socket."""
import base64
import hashlib
import hmac
import json
import ssl
import pytest
from test_publication_sync import event, sync_module

KEY = 'a' * 24 + ':' + 'b' * 64


def test_admin_origin_and_key_fail_closed_without_io():
    from app.publication_source import GhostAdmin
    for origin in ['', 'http://nucleo.jor.br', 'https://evil.test', 'https://nucleo.jor.br:443',
                   'https://nucleo.jor.br/', 'https://nucleo.jor.br@127.0.0.1',
                   'https://nucleo.jor.br/ghost', 'https://127.0.0.1', 'https://nucleo.jor.br?x']:
        with pytest.raises(sync_module().Rejected):
            GhostAdmin(origin, KEY)
    for key in ['', 'not-a-key', 'a:b', 'A' * 24 + ':' + 'b' * 64]:
        with pytest.raises(sync_module().Rejected):
            GhostAdmin('https://nucleo.jor.br', key)


def test_real_admin_transport_jwt_bounded_response_and_no_redirects(monkeypatch):
    from app import publication_source as source
    calls = []
    body = json.dumps({'posts': [json.loads(event())['post']['current']],
                       'meta': {'pagination': {'next': 2}}}).encode()
    settings = dict(status=200, body=body)

    class Response:
        def __init__(self):
            self.status = settings['status']
        def read(self, limit):
            assert limit == source.MAX_RESPONSE + 1
            return settings['body'][:limit]
    class Connection:
        def __init__(self, host, *, timeout, context):
            assert host == 'nucleo.jor.br'
            assert timeout == 10
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        def request(self, method, path, headers):
            calls.append((method, path, headers))
        def getresponse(self):
            return Response()
        def close(self):
            pass
    monkeypatch.setenv('HTTPS_PROXY', 'https://attacker.invalid')
    monkeypatch.setenv('NETRC', '/never/read')
    monkeypatch.setattr(source, 'PinnedHTTPSConnection', Connection)
    monkeypatch.setattr(source.time, 'time', lambda: 1800000000)
    client = source.GhostAdmin('https://nucleo.jor.br', KEY)
    posts, next_page = client.page(1, 20)
    assert len(posts) == 1 and next_page == 2
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(calls[0][1]).query)
    assert query['filter'] == ['status:[published,draft,scheduled,sent]']
    assert query['formats'] == ['plaintext,html']
    token = calls[0][2]['Authorization'].removeprefix('Ghost ')
    header, claims, signature = token.split('.')
    decode = lambda x: json.loads(base64.urlsafe_b64decode(x + '=' * (-len(x) % 4)))
    assert decode(header) == {'alg': 'HS256', 'typ': 'JWT', 'kid': 'a' * 24}
    assert decode(claims) == {'iat': 1800000000, 'exp': 1800000300, 'aud': '/admin/'}
    assert hmac.compare_digest(base64.urlsafe_b64encode(hmac.new(bytes.fromhex('b' * 64),
        (header + '.' + claims).encode(), hashlib.sha256).digest()).rstrip(b'=').decode(), signature)
    settings['status'] = 404
    assert client.get('a' * 24) is None
    with pytest.raises(sync_module().Rejected):
        client.page(1, 20)
    for code in [301, 302, 307, 401, 403, 429, 500]:
        settings['status'] = code
        count = len(calls)
        with pytest.raises(sync_module().Rejected):
            client.get('a' * 24)
        assert len(calls) == count + 1
    settings.update(status=200, body=b'x' * (source.MAX_RESPONSE + 1))
    with pytest.raises(sync_module().Rejected):
        client.get('a' * 24)
    for identity in ['../x', 'a' * 23, 'A' * 24]:
        count = len(calls)
        with pytest.raises(sync_module().Rejected):
            client.get(identity)
        assert len(calls) == count


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fe80::1'])
def test_dns_private_addresses_rejected_before_connect(monkeypatch, ip):
    from app import publication_source as source
    monkeypatch.setattr(source.socket, 'getaddrinfo', lambda *args, **kw: [(2, 1, 6, '', (ip, 443))])
    def forbidden(*args, **kw):
        pytest.fail('private address must never be contacted')
    monkeypatch.setattr(source.socket, 'create_connection', forbidden)
    with pytest.raises(sync_module().Rejected):
        source.PinnedHTTPSConnection('nucleo.jor.br', context=ssl.create_default_context(), timeout=10).connect()


def test_public_dns_pins_socket_but_preserves_tls_hostname(monkeypatch):
    from app import publication_source as source
    resolutions, connections, handshakes = [], [], []
    def resolve(host, port, **kwargs):
        resolutions.append((host, port))
        return [(2, 1, 6, '', ('93.184.216.34', 443))]
    sentinel = object()
    def connect(address, timeout):
        connections.append((address, timeout))
        return sentinel
    context = ssl.create_default_context()
    def handshake(sock, *, server_hostname):
        handshakes.append((sock, server_hostname))
        return sentinel
    monkeypatch.setattr(source.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(source.socket, 'create_connection', connect)
    monkeypatch.setattr(context, 'wrap_socket', handshake)
    connection = source.PinnedHTTPSConnection('nucleo.jor.br', context=context, timeout=10)
    connection.connect()
    assert resolutions == [('nucleo.jor.br', 443)]
    assert connections == [(('93.184.216.34', 443), 10)]
    assert handshakes == [(sentinel, 'nucleo.jor.br')]
    assert connection.sock is sentinel
