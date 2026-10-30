#!/usr/bin/env python3
"""Strict native-engine proof checks; no absence, string, or timeout means success."""
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);positive=json.loads((root/'ios-portal-smoke.json').read_text());negative=json.loads((root/'tls-rejection.json').read_text());state=json.loads((root/'service-state.json').read_text())
def require(condition,message):
 if condition is not True:raise SystemExit(message)
for r in (positive,negative):
 require(r.get('ok') is True and r.get('process_complete') is True,'Native app did not finalize successfully')
 require(r.get('engine')=='iOS Simulator WKWebView' and r.get('physical_device') is False and r.get('tls_bypass') is False,'Native engine / TLS boundary is not recorded')
require(isinstance(positive.get('simulator_device'),str) and positive['simulator_device'].startswith('iPhone'),'Missing actual simulator model identity')
require(negative.get('tls_rejected') is True,'Untrusted CA was not rejected')
for name in ('trusted_https_loaded','login_passed','admin_input_cleared','tool_connection_did_not_claim_automatic_capture','automatic_archive_ui_verified'):
 require(positive.get(name) is True,'Missing native portal proof: '+name)
config=positive.get('configuration',{})
require(config.get('https_only') is True and config.get('no_local_command') is True and config.get('stored_credentials') is False and config.get('http_only_admin_cookie_hidden') is True,'Credential/config boundary failed')
require(positive.get('mcp',{}).get('status_and_bootstrap') is True,'Native HTTPS MCP did not complete')
for name in ('saved','foreign_window_excluded','original_text_readback','agent_admin_isolation'):
 require(positive.get('host_hook',{}).get(name) is True,'Missing actual host-hook proof: '+name)
require(state.get('original_user_saved') is True and state.get('original_assistant_saved') is True and state.get('node_count')==1,'Actual backend did not retain exact synthetic dialogue')
require(any(c.get('archive_status')=='automatic_connected' and c.get('scope')=='ios-simulator-real-fixture-window' for c in state.get('connections',[])),'Actual host window was not bound')
print('Real iOS Simulator WKWebView: native TLS rejection/trust, portal, MCP, host hook, wording, scope and capability boundaries passed.')
