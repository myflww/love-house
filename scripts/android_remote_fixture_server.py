#!/usr/bin/env python3
"""Use the same real native-mobile Gateway/MemoryHost fixture with Android-only synthetic words.

Only test constants are replaced. The HTTP server, certificate verification,
authentication and memory implementation are the actual backend checkout.
"""
from pathlib import Path
import importlib.util
import json
import sys
import threading

ADMIN='ANDROID-WEBVIEW-SYNTHETIC-ADMIN-ONLY-000000000000'
USER='Synthetic Android host user: remember the silver compass.'
ASSISTANT='Synthetic Android host assistant: the silver compass is recorded.'


def main():
    # Diagnostic metadata only: retain the actual received Origin for this
    # synthetic native-engine fixture. Never record cookies, credentials,
    # payloads or query strings, and never change the Gateway's decision.
    from nkb.service import remote_gateway
    original_create=remote_gateway.create_server
    root=Path(sys.argv[sys.argv.index('--root')+1]).resolve()
    lock=threading.Lock()
    def diagnosed_create(gateway,**options):
        server=original_create(gateway,**options)
        base=server.RequestHandlerClass
        class DiagnosticHandler(base):
            def _check(self):
                if self.command=='POST':
                    record={'method':self.command,'path':self.path.split('?',1)[0][:200],
                            'origin':self.headers.get('Origin'),'expected_origin':gateway.origin,
                            'host':self.headers.get('Host')}
                    with lock:
                        with (root/'origin-diagnostics.jsonl').open('a',encoding='utf-8') as stream:
                            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
                return super()._check()
        server.RequestHandlerClass=DiagnosticHandler
        return server
    remote_gateway.create_server=diagnosed_create
    source=Path(__file__).resolve().parents[1]/'ios-smoke/fixture_server.py'
    spec=importlib.util.spec_from_file_location('shared_native_mobile_fixture',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.ADMIN=ADMIN;module.USER=USER;module.ASSISTANT=ASSISTANT
    module.main()


if __name__=='__main__':main()
