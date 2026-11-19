"""Optional, pinned-TLS companion connection. Only alert text crosses the network."""
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import ssl
import threading
import time
from urllib.parse import urlencode, urlparse, parse_qs

ALERT_LIFETIME = 300
MAX_CODE_ATTEMPTS = 3


class PhoneBridge:
    def __init__(self, directory, port=8766, host='0.0.0.0', clock=time.monotonic):
        self.directory = Path(directory)
        self.path = self.directory/'phone.json'
        self.port, self.host, self.clock = port, host, clock
        self.condition = threading.Condition(threading.RLock())
        self.server = self.thread = None
        self.pending = None
        self.results = {}
        self.last_seen = 0
        self.failures = {}
        self.pair_token = None
        self.pair_until = 0
        try:
            self.config = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.config = {}

    @property
    def enabled(self):
        return self.server is not None

    @property
    def paired(self):
        return self.enabled and bool(self.config.get('device_id'))

    @property
    def connected(self):
        return self.paired and self.last_seen > 0 and self.clock()-self.last_seen < 50

    def _save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.config), encoding='utf-8')
        temporary.replace(self.path)

    def _certificate(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        cert_path, key_path = self.directory/'phone-cert.pem', self.directory/'phone-key.pem'
        if cert_path.exists() and key_path.exists():
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        else:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Behavioral Guard')])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3650))
                    .sign(key, hashes.SHA256()))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self.fingerprint = cert.fingerprint(hashes.SHA256()).hex()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert_path, key_path)
        return context

    def start(self):
        if self.enabled:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        context = self._certificate()
        bridge = self

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def get_request(self):
                connection, address = self.socket.accept()
                connection.settimeout(8)
                try:
                    return context.wrap_socket(connection, server_side=True), address
                except Exception:
                    connection.close()
                    raise

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                data = json.dumps(body, separators=(',', ':')).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(data)

            def authorized(self, pairing=False):
                peer = self.client_address[0]
                now = bridge.clock()
                with bridge.condition:
                    failures = bridge.failures.setdefault(peer, deque(maxlen=12))
                    while failures and failures[0] < now-60:
                        failures.popleft()
                    if len(failures) >= 10:
                        self.reply(429, {'error': 'Try again later.'})
                        return False
                    raw = self.headers.get('Authorization', '')
                    token = raw[7:] if raw.startswith('Bearer ') else ''
                    digest = hashlib.sha256(token.encode()).hexdigest()
                    device = self.headers.get('X-Guard-Device', '')
                    valid = len(token) <= 128 and hmac.compare_digest(digest, bridge.config.get('token_hash', ''))
                    if bridge.config.get('device_id'):
                        valid = valid and hmac.compare_digest(device, bridge.config['device_id'])
                    elif not pairing or now >= bridge.pair_until:
                        valid = False
                    if not valid:
                        failures.append(now)
                        self.reply(401, {'error': 'Pair this phone again.'})
                        return False
                    self.auth_generation = bridge.config.get('token_hash')
                    bridge.last_seen = now
                    return True

            def do_GET(self):
                path = urlparse(self.path)
                if path.path not in ('/v1/status', '/v1/poll'):
                    return self.reply(404, {'error': 'Not found.'})
                if not self.authorized():
                    return
                if path.path == '/v1/poll':
                    last = parse_qs(path.query).get('last', [''])[0][:64]
                    with bridge.condition:
                        bridge.condition.wait_for(lambda: not bridge.enabled or
                            self.auth_generation != bridge.config.get('token_hash') or
                            (bridge._active_pending() or {}).get('id', '') != last, timeout=20)
                        state = bridge.state()
                else:
                    state = bridge.state()
                with bridge.condition:
                    if self.auth_generation != bridge.config.get('token_hash'):
                        return self.reply(401, {'error': 'Pair this phone again.'})
                self.reply(200, state)

            def do_POST(self):
                path = urlparse(self.path).path
                if path not in ('/v1/pair', '/v1/respond'):
                    return self.reply(404, {'error': 'Not found.'})
                if not self.authorized(pairing=path == '/v1/pair'):
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= length <= 8192:
                        raise ValueError()
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError()
                    with bridge.condition:
                        if self.auth_generation != bridge.config.get('token_hash'):
                            return self.reply(401, {'error': 'Pair this phone again.'})
                    if path == '/v1/pair':
                        device = self.headers.get('X-Guard-Device', '')
                        if len(device) != 32 or any(char not in '0123456789abcdef' for char in device):
                            raise ValueError()
                        with bridge.condition:
                            if self.auth_generation != bridge.config.get('token_hash'):
                                return self.reply(401, {'error': 'Pair this phone again.'})
                            if not bridge.config.get('device_id') and bridge.clock() >= bridge.pair_until:
                                return self.reply(401, {'error': 'Pairing expired.'})
                            bridge.config['device_id'] = device
                            bridge.config['device_name'] = str(data.get('name', 'Phone'))[:60]
                            bridge._save()
                            bridge.pair_token = None
                        return self.reply(200, bridge.state())
                    identifier, answer = data.get('id'), data.get('answer')
                    if not isinstance(identifier, str) or type(answer) is not bool:
                        raise ValueError()
                    with bridge.condition:
                        if self.auth_generation != bridge.config.get('token_hash'):
                            return self.reply(401, {'error': 'Pair this phone again.'})
                        pending = bridge._active_pending()
                        if not pending or pending['id'] != identifier:
                            return self.reply(409, {'error': 'This approval request has ended.'})
                        if answer:
                            code = data.get('code')
                            if not isinstance(code, str) or len(code) != 3 or not code.isascii() or not code.isdecimal():
                                return self.reply(400, {'error': 'Enter the three-digit code shown on your PC.'})
                            if pending['_attempts'] >= MAX_CODE_ATTEMPTS:
                                return self.reply(429, {'error': 'Too many attempts. Approve on your PC or deny here.'})
                            if not hmac.compare_digest(code, pending['_code']):
                                pending['_attempts'] += 1
                                return self.reply(422, {'error': 'That code did not match. Check the code on your PC.'})
                        if not bridge.answer(identifier, answer, 'phone'):
                            return self.reply(409, {'error': 'This alert has already ended.'})
                    self.reply(200, {'accepted': True, 'answer': bridge.result(identifier)})
                except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
                    self.reply(400, {'error': 'Invalid request.'})

        server = Server((self.host, self.port), Handler)
        self.server = server
        self.port = server.server_address[1]
        self.thread = threading.Thread(target=server.serve_forever, daemon=True, name='BehavioralGuard-Phone')
        self.thread.start()

    def restore(self):
        if self.config.get('enabled') and self.config.get('token_hash') and self.config.get('device_id'):
            self.start()

    def addresses(self):
        addresses = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                address = info[4][0]
                if not address.startswith(('127.', '169.254.')):
                    addresses.add(address)
        except OSError:
            pass
        return sorted(addresses) or ['127.0.0.1']

    def begin_pairing(self, address=None):
        self.start()
        with self.condition:
            token = secrets.token_urlsafe(32)
            self.config = {'enabled': True, 'token_hash': hashlib.sha256(token.encode()).hexdigest()}
            self._save()
            self.pair_token, self.pair_until = token, self.clock()+600
            self.last_seen = 0
            self.pending = None
            self.condition.notify_all()
            return self.pairing_link(address or self.addresses()[0])

    def pairing_link(self, address):
        if not self.pair_token or self.clock() >= self.pair_until:
            return None
        return 'behavioralguard-v2://pair?'+urlencode({'host': address, 'port': self.port,
            'token': self.pair_token, 'pin': self.fingerprint})

    def _active_pending(self):
        if self.pending and self.clock() < self.pending['_deadline']:
            return self.pending
        return None

    def state(self):
        with self.condition:
            pending = self._active_pending()
            return {'protocol': 2, 'pc': socket.gethostname(), 'paired': bool(self.config.get('device_id')),
                    'alert': {key: value for key, value in pending.items() if not key.startswith('_')} if pending else None}

    def publish(self, description, profile_name='', kind='behavior'):
        with self.condition:
            identifier = secrets.token_hex(16)
            self.pending = {'id': identifier, 'reason': str(description)[:2000], 'profile': str(profile_name)[:80],
                            'kind': kind, 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                            'expires_at': int(time.time()+ALERT_LIFETIME), '_deadline': self.clock()+ALERT_LIFETIME,
                            '_code': f'{secrets.randbelow(1000):03d}', '_attempts': 0}
            self.condition.notify_all()
            return identifier

    def approval_code(self, identifier):
        with self.condition:
            pending = self._active_pending()
            if pending and pending['id'] == identifier:
                return pending['_code']

    def answer(self, identifier, answer, source='pc'):
        if type(answer) is not bool:
            return False
        with self.condition:
            current = self._active_pending()
            if not current or current['id'] != identifier or identifier in self.results:
                return False
            self.results[identifier] = (answer, source)
            if len(self.results) > 32:
                self.results.pop(next(iter(self.results)))
            self.pending = None
            self.condition.notify_all()
            return True

    def result(self, identifier):
        with self.condition:
            return self.results.get(identifier, (None, None))[0]

    def result_source(self, identifier):
        with self.condition:
            return self.results.get(identifier, (None, None))[1]

    def finish(self, identifier, local_answer):
        with self.condition:
            if self.result(identifier) is None:
                if not self.answer(identifier, bool(local_answer)):
                    # The remote request may expire while the local dialog remains open.
                    self.results[identifier] = (bool(local_answer), 'pc')
            return self.result(identifier)

    def close(self, disable=False):
        with self.condition:
            server, self.server = self.server, None
            self.pending = None
            if disable:
                self.config = {'enabled': False}
                self.pair_token = None
                self._save()
            self.condition.notify_all()
        if server is not None:
            server.shutdown()
            server.server_close()
