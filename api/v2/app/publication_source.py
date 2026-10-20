"""Read-only Ghost Admin source. No requests/proxy/netrc/redirect machinery.

TLS uses the OS CA trust store and hostname verification. DNS is resolved once,
all answers must be global, and the socket connects to that validated address
with the original hostname for TLS SNI/certificate checking (no rebinding gap).
"""
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urlencode, urlsplit
from app.publication_sync import Rejected
from app.publication_origin import source_origins

MAX_RESPONSE = 2 * 1024 * 1024


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if 'https://' + self.host not in source_origins() or self.port != 443:
            raise Rejected()
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise Rejected()
        # No automatic reconnect/redirect, HTTP proxy, tunnel or second DNS lookup.
        sock = socket.create_connection((addresses[0][4][0], 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class GhostAdmin:
    def __init__(self, origin, key):
        try:
            allowed = source_origins()
        except ValueError:
            raise Rejected() from None
        if origin not in allowed or not re.fullmatch(r'[0-9a-f]{24}:[0-9a-f]{64}', key):
            raise Rejected()
        self.host = urlsplit(origin).hostname
        self.kid, secret = key.split(':')
        self._secret = bytes.fromhex(secret)

    def _token(self):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
        now = int(time.time())
        data = encode(dict(alg='HS256', typ='JWT', kid=self.kid)) + b'.' + encode(
            dict(iat=now, exp=now + 300, aud='/admin/'))
        signature = base64.urlsafe_b64encode(hmac.new(self._secret, data, hashlib.sha256).digest()).rstrip(b'=')
        return (data + b'.' + signature).decode()

    def _request(self, path, *, missing=False):
        connection = None
        try:
            connection = PinnedHTTPSConnection(self.host, timeout=10, context=ssl.create_default_context())
            connection.request('GET', '/ghost/api/admin/posts/' + path, headers={
                'Authorization': 'Ghost ' + self._token(), 'Accept': 'application/json',
                'Accept-Version': 'v6.0', 'User-Agent': 'nuclito-publication-reconciler/1'})
            response = connection.getresponse()
            if missing and response.status == 404:
                return None
            if response.status != 200:
                raise Rejected(503)
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise Rejected(413)
            result = json.loads(raw)
            if not isinstance(result, dict) or not isinstance(result.get('posts'), list):
                raise Rejected()
            return result
        except Rejected:
            raise
        except Exception:
            raise Rejected(503) from None
        finally:
            if connection is not None:
                connection.close()

    def page(self, page, limit):
        if type(page) is not int or not 1 <= page <= 1000000 or type(limit) is not int or not 1 <= limit <= 100:
            raise Rejected()
        result = self._request('?' + urlencode(dict(filter='status:[published,draft,scheduled,sent]', formats='plaintext,html',
            include='tags', order='id asc', page=page, limit=limit)))
        try:
            next_page = result['meta']['pagination']['next']
            if next_page is not None and (type(next_page) is not int or next_page != page + 1):
                raise Rejected()
            if len(result['posts']) > limit:
                raise Rejected()
            return result['posts'], next_page
        except (KeyError, TypeError):
            raise Rejected() from None

    def get(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{24}', identity):
            raise Rejected()
        result = self._request(identity + '/?' + urlencode(dict(formats='plaintext,html', include='tags')), missing=True)
        if result is None:
            return None
        if len(result['posts']) != 1 or not isinstance(result['posts'][0], dict) or result['posts'][0].get('id') != identity:
            raise Rejected()
        return result['posts'][0]
