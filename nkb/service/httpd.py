"""HTTP servers bound to numeric loopback never require reverse DNS.

HTTPServer's standard bind resolves a display-only FQDN. A missing/slow local
resolver must not delay an otherwise ready local memory service. Named and
non-loopback binds retain the standard behavior; TLS and request validation
remain with the existing server/handler layers.
"""
from __future__ import annotations
from http.server import ThreadingHTTPServer
from ipaddress import ip_address
from socketserver import TCPServer


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        host=self.server_address[0]
        try:local=ip_address(host).is_loopback
        except ValueError:local=False
        if not local:
            return super().server_bind()
        TCPServer.server_bind(self)
        self.server_name=str(host)
        self.server_port=self.server_address[1]
