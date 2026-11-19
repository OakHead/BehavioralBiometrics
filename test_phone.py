"""TLS phone API tests run on loopback and never lock Windows."""
import hashlib
import io
import json
from pathlib import Path
import ssl
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
from phone_bridge import PhoneBridge


class PhoneApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='phone-test-', dir=Path(__file__).resolve().parent/'data')
        self.addCleanup(self.temporary.cleanup)
        self.bridge = PhoneBridge(self.temporary.name, host='127.0.0.1', port=0)
        self.addCleanup(lambda: self.bridge.close())
        self.query = parse_qs(urlparse(self.bridge.begin_pairing('127.0.0.1')).query)
        self.context = ssl.create_default_context(cafile=str(Path(self.temporary.name)/'phone-cert.pem'))
        self.context.check_hostname = False

    def request(self, path, body=None, token=None, device='a'*32, authorized=True, context=None):
        headers = {'X-Guard-Device':device}
        if authorized:
            headers['Authorization'] = 'Bearer '+(token if token is not None else self.query['token'][0])
        payload = json.dumps(body).encode() if body is not None else None
        request = Request('https://127.0.0.1:'+str(self.bridge.port)+path, data=payload, headers=headers)
        try:
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context or self.context))
            with opener.open(request, timeout=25) as result:
                return result.status, json.load(result)
        except HTTPError as error:
            return error.code, json.load(error)

    def pair(self):
        code, result = self.request('/v1/pair', {'name':'Test phone'})
        self.assertEqual(code, 200)
        self.assertTrue(result['paired'])

    def test_pairing_pins_the_real_tls_certificate_and_does_not_store_the_secret(self):
        cert = ssl.PEM_cert_to_DER_cert((Path(self.temporary.name)/'phone-cert.pem').read_text())
        self.assertEqual(self.query['pin'][0], hashlib.sha256(cert).hexdigest())
        self.pair()
        content = (Path(self.temporary.name)/'phone.json').read_text()
        self.assertNotIn(self.query['token'][0], content)
        self.assertEqual(json.loads(content)['token_hash'], hashlib.sha256(self.query['token'][0].encode()).hexdigest())

    def test_unpaired_and_unauthenticated_clients_cannot_read_alerts(self):
        self.assertEqual(self.request('/v1/status')[0], 401)
        self.pair()
        self.assertEqual(self.request('/v1/status', authorized=False)[0], 401)
        self.assertEqual(self.request('/v1/status', token='wrong')[0], 401)

    def test_an_untrusted_tls_certificate_is_rejected(self):
        self.pair()
        with self.assertRaises(URLError):
            self.request('/v1/status', context=ssl.create_default_context())

    def test_pairing_code_cannot_be_reused_by_a_second_device(self):
        self.pair()
        self.assertEqual(self.request('/v1/pair', {'name':'Other phone'}, device='b'*32)[0], 401)

    def test_yes_is_accepted_once_and_a_late_no_cannot_replace_it(self):
        self.pair()
        identifier = self.bridge.publish('Typing is faster.', 'Test')
        code, state = self.request('/v1/poll')
        self.assertEqual(code, 200)
        self.assertEqual(state['alert']['id'], identifier)
        self.assertNotIn('_deadline', state['alert'])
        self.assertNotIn('_code', state['alert'])
        self.assertEqual(self.request('/v1/respond', {'id': identifier, 'answer': True,
            'code': self.bridge.approval_code(identifier)})[0], 200)
        self.assertEqual(self.request('/v1/respond', {'id':identifier,'answer':False})[0], 409)
        self.assertIs(self.bridge.result(identifier), True)
        self.assertEqual(self.bridge.result_source(identifier), 'phone')

    def test_no_is_a_completed_answer_not_an_unanswered_request(self):
        self.pair()
        identifier = self.bridge.publish('Mouse moved too fast.')
        self.assertEqual(self.request('/v1/respond', {'id':identifier,'answer':False})[0], 200)
        self.assertIs(self.bridge.result(identifier), False)
        self.assertIs(self.bridge.finish(identifier, True), False)

    def test_wrong_alert_ids_and_non_boolean_answers_are_rejected(self):
        self.pair()
        identifier = self.bridge.publish('Test')
        self.assertEqual(self.request('/v1/respond', {'id':'b'*32,'answer':True})[0], 409)
        self.assertEqual(self.request('/v1/respond', {'id':identifier,'answer':'yes'})[0], 400)
        self.assertIsNone(self.bridge.result(identifier))

    def test_expired_alerts_cannot_be_approved(self):
        self.pair()
        identifier = self.bridge.publish('Test')
        now = self.bridge.clock()
        self.bridge.clock = lambda: now+301
        self.assertEqual(self.request('/v1/respond', {'id':identifier,'answer':True})[0], 409)
        self.assertIsNone(self.bridge.result(identifier))

    def test_pairing_expiry_rejects_even_the_original_code(self):
        now = self.bridge.clock()
        self.bridge.clock = lambda: now+601
        self.assertEqual(self.request('/v1/pair', {'name':'Too late'})[0], 401)

    def test_new_pairing_revokes_the_old_token(self):
        self.pair()
        self.bridge.begin_pairing('127.0.0.1')
        self.assertEqual(self.request('/v1/status')[0], 401)

    def test_repairing_invalidates_an_already_open_long_poll(self):
        self.pair()
        self.bridge.last_seen = -1
        result = []
        worker = threading.Thread(target=lambda: result.append(self.request('/v1/poll')))
        worker.start()
        deadline = time.monotonic()+2
        while self.bridge.last_seen == -1 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertNotEqual(self.bridge.last_seen, -1)
        self.bridge.begin_pairing('127.0.0.1')
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0][0], 401)

    def test_reopening_restores_the_paired_phone_and_certificate(self):
        self.pair()
        original = self.bridge.fingerprint
        self.bridge.close()
        self.bridge = PhoneBridge(self.temporary.name, host='127.0.0.1', port=0)
        self.bridge.restore()
        self.assertEqual(self.bridge.fingerprint, original)
        self.assertEqual(self.request('/v1/status')[0], 200)

    def test_phone_and_pc_race_can_resolve_an_alert_only_once(self):
        identifier = self.bridge.publish('Test')
        barrier = threading.Barrier(3)
        accepted = []
        def answer(value, source):
            barrier.wait()
            accepted.append((self.bridge.answer(identifier,value,source),value))
        workers = [threading.Thread(target=answer,args=(True,'pc')), threading.Thread(target=answer,args=(False,'phone'))]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(2)
        winners = [value for won,value in accepted if won]
        self.assertEqual(len(winners),1)
        self.assertIs(self.bridge.result(identifier),winners[0])


class NumberMatchingTests(unittest.TestCase):
    """Exercise the HTTP handler without opening a client connection."""

    setUp = PhoneApiTests.setUp
    pair = PhoneApiTests.pair

    def request(self, path, body=None):
        payload = json.dumps(body).encode() if body is not None else b''
        method = 'GET' if body is None else 'POST'
        headers = (f'{method} {path} HTTP/1.0\r\nX-Guard-Device: {"a"*32}\r\n'
                   f'Content-Length: {len(payload)}\r\nAuthorization: Bearer {self.query["token"][0]}\r\n')
        incoming = io.BytesIO((headers+'\r\n').encode()+payload)
        outgoing = io.BytesIO()

        class Socket:
            def makefile(self, *_):
                return incoming

            def sendall(self, value):
                outgoing.write(value)

        self.bridge.server.RequestHandlerClass(Socket(), ('127.0.0.1', 10000), self.bridge.server)
        head, body = outgoing.getvalue().split(b'\r\n\r\n', 1)
        return int(head.split()[1]), json.loads(body)

    def test_phone_approval_requires_a_code_and_limits_wrong_attempts(self):
        self.pair()
        identifier = self.bridge.publish('Test')
        code = self.bridge.approval_code(identifier)
        body = {'id': identifier, 'answer': True}
        self.assertEqual(self.request('/v1/respond', body)[0], 400)
        wrong = '001' if code == '000' else '000'
        for _ in range(3):
            self.assertEqual(self.request('/v1/respond', dict(body, code=wrong))[0], 422)
        self.assertEqual(self.request('/v1/respond', dict(body, code=code))[0], 429)
        self.assertIsNone(self.bridge.result(identifier))
        self.assertEqual(self.request('/v1/respond', dict(body, answer=False))[0], 200)

    def test_correct_number_completes_the_request_and_is_absent_from_status(self):
        self.pair()
        identifier = self.bridge.publish('Test')
        status, state = self.request('/v1/status')
        self.assertEqual(status, 200)
        self.assertEqual(set(state['alert']), {'id', 'reason', 'profile', 'kind', 'created', 'expires_at'})
        body = {'id': identifier, 'answer': True, 'code': self.bridge.approval_code(identifier)}
        self.assertEqual(self.request('/v1/respond', body)[0], 200)
        self.assertIs(self.bridge.result(identifier), True)
        self.assertEqual(self.bridge.result_source(identifier), 'phone')


class PhoneDialogTests(unittest.TestCase):
    def test_a_real_phone_no_response_closes_the_pc_dialog_as_no(self):
        import tkinter as tk
        from ui_theme import configure
        from phone_ui import ask_with_phone
        with tempfile.TemporaryDirectory(prefix='phone-dialog-', dir=Path(__file__).resolve().parent/'data') as folder:
            bridge = PhoneBridge(folder, host='127.0.0.1', port=0)
            root = tk.Tk()
            root.withdraw()
            configure(root)
            failures, workers = [], []
            try:
                query = parse_qs(urlparse(bridge.begin_pairing('127.0.0.1')).query)
                context = ssl.create_default_context(cafile=str(Path(folder)/'phone-cert.pem'))
                context.check_hostname = False
                opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
                def post(path, data):
                    request = Request('https://127.0.0.1:'+str(bridge.port)+path, data=json.dumps(data).encode(),
                        headers={'Authorization':'Bearer '+query['token'][0], 'X-Guard-Device':'a'*32})
                    with opener.open(request, timeout=3) as result:
                        return json.load(result)
                post('/v1/pair', {'name':'Test phone'})
                def send():
                    try:
                        identifier = bridge.state()['alert']['id']
                        post('/v1/respond', {'id':identifier, 'answer':False})
                    except Exception as error:
                        failures.append(error)
                def start_worker():
                    worker = threading.Thread(target=send)
                    workers.append(worker)
                    worker.start()
                root.after(300, start_worker)
                def timeout():
                    from dialogs import Dialog
                    for child in root.winfo_children():
                        if isinstance(child, Dialog):
                            child.cancel()
                watchdog = root.after(5000, timeout)
                answer, source = ask_with_phone(root, bridge, 'Synthetic test alert.', kind='test')
                root.after_cancel(watchdog)
                for worker in workers:
                    worker.join(3)
                self.assertFalse(failures)
                self.assertIs(answer, False)
                self.assertEqual(source, 'phone')
            finally:
                bridge.close()
                root.destroy()


if __name__ == '__main__':
    unittest.main()
