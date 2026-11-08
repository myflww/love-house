"""Android lifecycle adapter for the unmodified desktop memory engine.

Only Java supplies the app-private directory and credential vault. No other
application's files, messages, keys or accessibility surfaces are inspected.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

_lock = threading.RLock()
_runtime = None
MAX_MIGRATION_BYTES = 32 * 1024 * 1024


def _credential_store(vault):
    from nkb.service.credentials import KeyStore, KeyStoreError, _account, _LOCK, _SESSION

    class AndroidKeyStore(KeyStore):
        def __init__(self):
            super().__init__(allow_source_build=False)

        def _call(self, op, account, value=None, **kwargs):
            try:
                result = json.loads(str(vault.call(op, account, value or "")))
                return result if isinstance(result, dict) else None
            except Exception:
                return None  # Never stringify exceptions containing credentials.

        @staticmethod
        def _metadata(storage="none", ready=False, saved=False):
            return KeyStore._metadata("android_keystore" if storage == "keychain" else storage, ready, saved)

        def delete(self, ref):
            account = _account(ref)
            with _LOCK:
                _SESSION.pop(account, None)
                result = self._call("delete", account)
                if not result or result.get("ok") is not True:
                    raise KeyStoreError("无法确认 Android 安全存储已删除；未宣称持久密钥已清除")
                return self._metadata()

    return AndroidKeyStore()


def start(data_dir, vault, port=8768):
    """Start exactly one private loopback controller per application process."""
    global _runtime
    with _lock:
        root = Path(str(data_dir)).resolve()
        if _runtime is not None:
            if _runtime["root"] != root:
                raise ValueError("Android memory directory cannot change during a process")
            return json.dumps({"url": _runtime["url"], "ui_session": _runtime['host'].management_token})
        from nkb.service.host import MemoryHost, make_controller
        from nkb.service.httpd import LoopbackHTTPServer
        from nkb.service.remote_gateway import RemoteGateway, make_gateway_handler, GatewayError
        from nkb.errors import ValidationError
        import secrets

        class AndroidHost(MemoryHost):
            def __init__(self, *args, **kwargs):
                self._graph_capability = secrets.token_urlsafe(40)
                super().__init__(*args, **kwargs)

            def graph_server(self, brain):
                from nkb.adapters.http import make_handler
                import hmac
                graph_base = make_handler(brain)
                owner = self

                class PrivateGraph(graph_base):
                    def _internal(self):
                        value = self.headers.get('X-LoveHouse-Android-Internal', '')
                        return bool(value and hmac.compare_digest(value, owner._graph_capability))

                    def do_GET(self):
                        if not self._internal():
                            return self._json({'error': 'Private application transport'}, 401)
                        return super().do_GET()

                    def do_POST(self):
                        if not self._internal():
                            return self._json({'error': 'Private application transport'}, 401)
                        return super().do_POST()

                return LoopbackHTTPServer(('127.0.0.1', 0), PrivateGraph)

            def library_json(self, library_id, path, body=None, timeout=20, *, headers=None):
                return super().library_json(library_id, path, body, timeout=timeout,
                    headers={**(headers or {}), 'X-LoveHouse-Android-Internal': self._graph_capability})

            def update_agent_config(self, cid):
                if self.connections.get(cid)['revoked']:
                    return {'connection': self.connections.get(cid), 'configuration_ready': False}
                return self.gateway.configuration(cid)

            def _connection_config(self, cid):
                if self.connections.get(cid)['host'] == 'agent' and not self.sources.for_connection(cid):
                    if (self.connections.get(cid)['revoked']
                            or self.connections.get(cid)['library_id'] in self._closing_libraries):
                        return {'connection': self.connections.get(cid), 'configuration_ready': False,
                                'supported': False, 'requires_apply': False, 'host_config': ''}
                    result = self.gateway.configuration(cid)
                    result['agent_setup_text'] = ('这是 Android 手机本机的 HTTP MCP 配置，只适用于运行在同一手机的宿主。'
                        '127.0.0.1 不能连接另一台电脑或云服务器。\n' + result['agent_setup_text'])
                    return result
                return super()._connection_config(cid)

            def new_connection(self, data):
                if data.get('host') == 'harness':
                    raise ValidationError('Harness 桌面插件须在运行 Harness 的电脑安装；手机不能安装到另一台设备')
                return super().new_connection(data)

            def register_agent_source(self, library_id, data):
                raise ValidationError('文件型活动来源须在实际宿主的电脑或服务器配置；手机请打开那台服务的 HTTPS 管理页')

            def drain_agent_outboxes(self):
                # Android hosts deliver real events by the authenticated HTTP
                # callback, not by executing desktop Python bridge commands.
                return

        host = AndroidHost(root / "memory", key_store=_credential_store(vault))
        gateway = RemoteGateway(host, origin='https://127.0.0.1', admin_token=secrets.token_urlsafe(40))
        host.gateway = gateway
        Rpc = make_gateway_handler(gateway)
        # Select Android APKs, never offer a Linux/desktop binary to this app.
        from nkb.service.updates import UpdateChecker
        import platform
        host.updates.stop()
        host.updates = UpdateChecker(host.root, system="Android", machine=platform.machine())
        Base = make_controller(host)

        class Controller(Base):
            # Reuse the existing protocol validation and fixed-connection tool
            # dispatcher. Only these two agent routes are added; the remote
            # admin surface and login routes are never mounted here.
            _agent = Rpc._agent
            _reply = Rpc._reply

            def do_POST(self):
                from urllib.parse import urlsplit
                parts = urlsplit(self.path).path.strip('/').split('/')
                is_mcp = len(parts) == 2 and parts[0] == 'mcp'
                is_hook = len(parts) == 5 and parts[:3] == ['api', 'remote', 'connections'] and parts[4] == 'events'
                if not (is_mcp or is_hook):
                    try:
                        # On Android, other apps may have loopback access.
                        # They are not part of this app's management trust zone.
                        # Bearer routes still pass the desktop scoped guard.
                        if not self._token():
                            self._require_management()
                    except Exception as exc:
                        return self._error(exc)
                    return super().do_POST()
                body = {}
                try:
                    self._check_request()
                    cid = parts[1] if is_mcp else parts[3]
                    token = self._agent(cid)
                    body = Rpc._body(self, limit=1024*1024 if is_mcp else 32*1024*1024)
                    if is_mcp:
                        return Rpc._mcp(self, cid, body)
                    from nkb.service.agent_client import event_from_hook
                    return self._reply(host.accept(cid, token, event_from_hook(body)))
                except Exception as exc:
                    if not isinstance(exc, (ValidationError, GatewayError)):
                        from nkb.adapters.http import RequestError
                        if not isinstance(exc, RequestError):
                            exc = GatewayError('手机记忆连接请求未完成', 400)
                    return Rpc._error(self, exc, body.get('id'), rpc=is_mcp)

            def do_GET(self):
                # Keep all desktop request, origin and credential checks. Only
                # the local shell receives Android-specific navigation hints.
                from urllib.parse import urlsplit
                path = urlsplit(self.path).path
                try:
                    self._check_request()
                    if path.startswith('/mcp/'):
                        parts = path.strip('/').split('/')
                        if len(parts) != 2:
                            raise GatewayError('MCP地址不存在', 404)
                        self._agent(parts[1])
                        return self._reply({'error': 'No standalone SSE stream'}, 405, headers={'Allow': 'POST'})
                    if path != '/api/health':
                        self._require_management()
                except Exception as exc:
                    return self._error(exc)
                if path in ("/", "/index.html"):
                    try:
                        self._check_request()
                        self._guard_connection_surface(path)
                        if self.headers.get("Authorization") or self.headers.get("X-NKB-Connection-Key"):
                            from nkb.adapters.http import RequestError
                            raise RequestError("记忆连接凭证不能打开管理页面", 403)
                        from nkb.viz.builder import html_for_serve
                        html = html_for_serve().replace('<head>', '<head><script>window.LoveHouseAndroid=true;</script>', 1)
                        # Android launcher, preserved offline view and full view
                        # use one exact approved pixel-heart master.
                        import base64, re
                        icon = Path(__file__).with_name('icon.png')
                        if icon.is_file():
                            data = 'data:image/png;base64,' + base64.b64encode(icon.read_bytes()).decode('ascii')
                            html = re.sub(r'(<img\b[^>]*\bid="houseBrandIcon"[^>]*\bsrc=")[^"]*(")',
                                          lambda match: match[1] + data + match[2], html, count=1)
                        extra = '<script src="/android-native.js"></script><link rel="stylesheet" href="/android-mobile.css">'
                        html = html.replace("</body>", extra + "</body>")
                        self._issue_management_cookie = True
                        return self._html(html)
                    except Exception as exc:
                        return self._error(exc)
                if path in ("/android-native.js", "/android-mobile.css"):
                    try:
                        self._check_request()
                        self._guard_connection_surface(path)
                        body = Path(__file__).with_name(path[1:]).read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception as exc:
                        return self._error(exc)
                    return
                return super().do_GET()

        try:
            # 8768 is the same stable local service endpoint as the desktop.
            # Fail visibly if occupied rather than silently attach another app.
            server = LoopbackHTTPServer(("127.0.0.1", port), Controller)
            server.daemon_threads = True
            host.controller_port = server.server_port
            gateway.origin = f'http://127.0.0.1:{server.server_port}'
            gateway.authority = f'127.0.0.1:{server.server_port}'
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
            thread.start()
        except Exception:
            host.stop()
            raise
        _runtime = {"root": root, "host": host, "server": server, "thread": thread,
                    "url": f"http://127.0.0.1:{server.server_port}/"}
        return json.dumps({"url": _runtime["url"], "ui_session": host.management_token})


def import_legacy(path):
    """Explicit, idempotent migration; the original IndexedDB stays untouched."""
    with _lock:
        if _runtime is None:
            raise ValueError("Memory engine has not started")
        candidate = Path(str(path))
        allowed = _runtime["root"].parent / "engine-imports"
        if candidate.is_symlink() or not candidate.is_file() or candidate.resolve().parent != allowed.resolve():
            raise ValueError("Migration file must be an app-private staged document")
        if candidate.stat().st_size > MAX_MIGRATION_BYTES:
            raise ValueError("Migration exceeds the mobile import limit")
        content = candidate.read_text("utf-8")
        value = json.loads(content)
        material = {key: value.get(key) for key in ("name", "memory", "archives")}
        digest = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        receipts_path = _runtime["root"] / "legacy-imports.json"
        try:
            receipts = json.loads(receipts_path.read_text("utf-8")) if receipts_path.exists() else {}
            if not isinstance(receipts, dict):
                receipts = {}
        except (OSError, ValueError, UnicodeError):
            # The graph carries the authoritative committed import mark.
            # A corrupt/missing auxiliary receipt must not cause another copy.
            receipts = {}
        host = _runtime["host"]
        prior = receipts.get(digest)
        libraries = [row for row in host.manager.list_libraries() if not row.get('is_demo')]
        # Check the previously indexed library first, then recover any graph
        # committed before the process could save its receipt. Never trust a
        # receipt's library ID without checking that graph's own fingerprint.
        libraries.sort(key=lambda row: row['id'] != prior)
        for row in libraries:
            if not row.get('available', True):
                continue
            try:
                imported = host.snapshot(row['id']).get('meta', {}).get('shared_import', {})
            except Exception:
                raise ValueError('无法核对已有完整记忆库，尚未再次迁移；原记录已保留') from None
            if isinstance(imported, dict) and imported.get('source_fingerprint') == digest:
                host.manager.select(row['id'])
                return json.dumps({"imported": False, "duplicate": True, "library_id": row['id']})
        result = host.sharing.import_file(content, source_fingerprint=digest)
        library_id = result["library"]["id"]
        receipts[digest] = library_id
        from nkb.storage.jsonfile import JsonFileStorage
        try:
            JsonFileStorage(receipts_path).save(receipts)
            recorded = True
        except Exception:
            # The graph is already safely committed. Do not report its success
            # as lost merely because this redundant lookup index could not save.
            recorded = False
        return json.dumps({"imported": True, "duplicate": False, "library_id": library_id,
                           "receipt_recorded": recorded})


def stop():
    global _runtime
    with _lock:
        runtime, _runtime = _runtime, None
        if runtime is not None:
            runtime["server"].shutdown()
            runtime["server"].server_close()
            runtime["thread"].join(timeout=3)
            runtime["host"].stop()
