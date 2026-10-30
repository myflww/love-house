#!/usr/bin/env python3
"""Require actual Android-engine TLS, portal and durable backend evidence."""
import argparse
import json
from pathlib import Path


def check(directory, api_level):
    directory=Path(directory)
    positive=json.loads((directory/'android-remote-gateway.json').read_text())
    negative=json.loads((directory/'android-tls-rejection.json').read_text())
    state=json.loads((directory/'service-state.json').read_text())
    fixture=json.loads((directory/'fixture.json').read_text())
    permissions=(directory/'production-permissions.txt').read_text()
    apk_entries=(directory/'production-apk-entries.txt').read_text()
    def require(condition,message):
        if condition is not True:raise ValueError(message)
    for report in (positive,negative):
        require(report.get('ok') is True and report.get('engine')=='Android System WebView','No successful actual Android WebView report')
        require(report.get('api_level')==api_level and bool(report.get('webview_version')),'Wrong Android API or missing system engine version')
        require(report.get('tls_bypass') is False and report.get('production_app_modified') is False,'TLS or production boundary was weakened')
    require(negative.get('tls_rejected') is True,'Untrusted-domain CA was not rejected')
    require(negative.get('http_reached_after_tls_error') is False,'TLS rejection still reached an HTTP response')
    for key in ('trusted_https_loaded','same_origin_referrer_policy','portal_login','http_only_cookie_hidden','automatic_archive_ui_verified'):
        require(positive.get(key) is True,'Missing native portal proof: '+key)
    require(positive.get('ssl_errors')==0,'Trusted HTTPS had a native SSL error')
    config=positive.get('configuration',{})
    require(config.get('https_only') is True and config.get('no_local_command') is True and config.get('credentials_persisted') is False,'Remote configuration or browser credential isolation failed')
    result=positive.get('mcp_and_hook',{})
    for key in ('legacy_protocol','modern_protocol','bootstrap','tools_did_not_claim_auto','manual_did_not_claim_window',
                'host_hook_saved','foreign_window_excluded','original_user_readback','original_assistant_readback','agent_admin_isolation'):
        require(result.get(key) is True,'Missing real HTTPS interaction proof: '+key)
    require(state.get('node_count')==1 and state.get('original_user_saved') is True and state.get('original_assistant_saved') is True,'The actual MemoryHost did not retain exact synthetic dialogue')
    require(any(c.get('archive_status')=='automatic_connected' and c.get('scope')==result.get('actual_window') for c in state.get('connections',[])),'Actual service scope and capture state disagree')
    require(fixture.get('public_ca_only') is True and fixture.get('production_app_modified') is False,'Test trust entered the wrong package')
    require('io.github.myflww.lovehouse.preview' in permissions and 'android.permission.INTERNET' not in permissions,'Production APK gained network permission or its manifest was not checked')
    require(bool(apk_entries.strip()) and not any(name in apk_entries for name in ('remote_test_ca','remote_qa_network_security','remoteqa/RemoteGateway')),'Production APK contains test-only trust/host resources or its entries were not checked')
    print('Actual Android API '+str(api_level)+' WebView: TLS rejection/trust, portal, MCP, hook, exact roles, window and admin boundaries passed.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--api-level',type=int,required=True)
    args=parser.parse_args();check(args.directory,args.api_level)


if __name__=='__main__':main()
