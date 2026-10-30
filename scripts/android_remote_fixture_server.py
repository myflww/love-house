#!/usr/bin/env python3
"""Use the same real native-mobile Gateway/MemoryHost fixture with Android-only synthetic words.

Only test constants are replaced. The HTTP server, certificate verification,
authentication and memory implementation are the actual backend checkout.
"""
from pathlib import Path
import importlib.util

ADMIN='ANDROID-WEBVIEW-SYNTHETIC-ADMIN-ONLY-000000000000'
USER='Synthetic Android host user: remember the silver compass.'
ASSISTANT='Synthetic Android host assistant: the silver compass is recorded.'


def main():
    source=Path(__file__).resolve().parents[1]/'ios-smoke/fixture_server.py'
    spec=importlib.util.spec_from_file_location('shared_native_mobile_fixture',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.ADMIN=ADMIN;module.USER=USER;module.ASSISTANT=ASSISTANT
    module.main()


if __name__=='__main__':main()
