"""Real local binding and memory startup survive an unavailable PTR resolver."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

from nkb.service.httpd import LoopbackHTTPServer
from nkb.service.host import MemoryHost
from nkb.service.credentials import KeyStore


class LoopbackHTTPServerTests(unittest.TestCase):
    def test_actual_loopback_http_works_when_reverse_dns_cannot_return(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'local-ready')
        with patch('socket.getfqdn',side_effect=AssertionError('PTR lookup must not be required')):
            server=LoopbackHTTPServer(('127.0.0.1',0),Handler)
            self.assertEqual(server.server_name,'127.0.0.1')
            self.assertEqual(server.server_port,server.server_address[1])
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
            try:
                with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{server.server_port}/',timeout=2) as response:
                    self.assertEqual(response.read(),b'local-ready')
            finally:server.shutdown();server.server_close();thread.join()

    def test_personal_graph_startup_does_not_wait_for_reverse_dns(self):
        with tempfile.TemporaryDirectory() as directory,patch('socket.getfqdn',side_effect=AssertionError('unexpected PTR')):
            host=MemoryHost(Path(directory),key_store=KeyStore(allow_keychain=False))
            try:self.assertEqual(host.snapshot('default')['nodes'],{})
            finally:host.stop()

    def test_named_bind_keeps_standard_httpserver_behavior(self):
        with patch.object(ThreadingHTTPServer,'server_bind') as standard:
            server=LoopbackHTTPServer.__new__(LoopbackHTTPServer);server.server_address=('localhost',0)
            server.server_bind();standard.assert_called_once()

if __name__=='__main__':unittest.main()
