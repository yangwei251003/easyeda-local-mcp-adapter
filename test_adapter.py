import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
import unittest

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from server import Bridge, BridgeError


class Tests(unittest.TestCase):
    def setUp(self):
        self.state = {'windows': [], 'posts': [], 'mode': 'ok', 'service': 'easyeda-bridge'}
        state = self.state
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def reply(self, data, status=200):
                self.send_response(status)
                self.end_headers()
                try:
                    self.wfile.write(json.dumps(data).encode())
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            def do_GET(self):
                if state['mode'] == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', 'http://127.0.0.1:1/not-followed')
                    self.end_headers()
                    return
                if self.path == '/health':
                    self.reply({'service': state['service'], 'edaConnected': bool(state['windows'])})
                else:
                    self.reply({'windows': state['windows'], 'activeWindowId': 'a'})
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                state['posts'].append(payload)
                if state['mode'] == 'timeout':
                    time.sleep(0.15)
                if state['mode'] == 'error':
                    self.reply({'success': False, 'error': 'EDA error'}, 500)
                else:
                    self.reply({'success': True, 'result': payload['windowId']})
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.handler = Handler
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.bridge = Bridge([self.http.server_port], execute_timeout=0.05)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()

    def test_disconnected(self):
        self.assertFalse(self.bridge.status()['health']['edaConnected'])
        with self.assertRaises(BridgeError):
            self.bridge.execute('return 1;', 'a')
        self.assertEqual(self.state['posts'], [])

    def test_identity(self):
        self.state['service'] = 'unrelated'
        self.assertFalse(self.bridge.status()['bridgeConnected'])

    def test_multiwindow_explicit_routing(self):
        self.state['windows'] = [{'windowId': w, 'connected': True} for w in ['a', 'b']]
        self.assertEqual(len(self.bridge.windows()['windows']), 2)
        with self.assertRaises(BridgeError):
            self.bridge.execute('return 1;', '')
        self.assertEqual(self.bridge.execute('return 1;', 'b')['result'], 'b')
        self.assertEqual(self.state['posts'], [{'code': 'return 1;', 'windowId': 'b'}])

    def test_error_and_no_retry(self):
        self.state['windows'] = [{'windowId': 'a', 'connected': True}]
        self.state['mode'] = 'error'
        with self.assertRaises(BridgeError) as result:
            self.bridge.execute('throw Error();', 'a')
        self.assertTrue(result.exception.uncertain)
        self.assertEqual(len(self.state['posts']), 1)

    def test_timeout_and_no_retry(self):
        self.state['windows'] = [{'windowId': 'a', 'connected': True}]
        self.state['mode'] = 'timeout'
        with self.assertRaises(BridgeError) as result:
            self.bridge.execute('return 1;', 'a')
        self.assertTrue(result.exception.uncertain)
        self.assertEqual(len(self.state['posts']), 1)

    def test_multiple_bridges_are_rejected(self):
        second = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        threading.Thread(target=second.serve_forever, daemon=True).start()
        try:
            bridge = Bridge([self.http.server_port, second.server_port])
            with self.assertRaises(BridgeError) as result:
                bridge.discover()
            self.assertEqual(set(result.exception.details['ports']), {self.http.server_port, second.server_port})
            self.assertEqual(self.state['posts'], [])
        finally:
            second.shutdown()
            second.server_close()

    def test_redirect_is_not_followed(self):
        self.state['mode'] = 'redirect'
        self.assertFalse(self.bridge.status()['bridgeConnected'])
        self.assertEqual(self.state['posts'], [])

    def test_bad_execute_inputs_send_nothing(self):
        for code, window in [('', 'a'), (None, 'a'), ('return 1;', None)]:
            with self.assertRaises(BridgeError):
                self.bridge.execute(code, window)
        self.assertEqual(self.state['posts'], [])

    def test_stdio_protocol_uses_only_fake_bridge(self):
        asyncio.run(smoke(self.http.server_port))
        self.assertEqual(self.state['posts'], [])


async def smoke(fake_port):
    fixture = Path(__file__).with_name('test_support') / 'stdio_fake_bridge.py'
    params = StdioServerParameters(command=sys.executable, args=[str(fixture), str(fake_port)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            initialized = await client.initialize()
            assert initialized.server_info.name == 'easyeda-local'
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {'easyeda_status', 'easyeda_windows', 'easyeda_execute'}
            result = await client.call_tool('easyeda_status', {})
            assert not result.is_error
            data = json.loads(result.content[0].text)
            assert data['port'] == fake_port
            assert data['bridgeConnected'] is True
            print('MCP INITIALIZE/LIST/STATUS: PASS (fake bridge only)')
            missing = await client.call_tool('easyeda_execute', {'code': 'return 1;'})
            assert missing.is_error
            print('MISSING WINDOW ID CORRECTLY REJECTED')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        sys.exit(1)
