#!/usr/bin/env python3
"""Require actual Android-engine TLS, portal and durable backend evidence."""
import argparse
import json
from pathlib import Path
import re

from verify_android_release import APP_ID, ENGINE_ABIS, ENGINE_LIBRARIES


def check_production_boundary(permissions, apk_entries, proof):
    package=re.findall(r'^package: (\S+)\s*$',permissions,re.M)
    declared=re.findall(r"^uses-permission(?:-sdk-\d+)?: name='([^']+)'",permissions,re.M)
    lines=[line for line in permissions.splitlines() if line.startswith('uses-permission')]
    if package!=[APP_ID] or declared!=['android.permission.INTERNET'] or len(lines)!=1:
        raise ValueError('Production APK must request exactly the engine network permission')
    entries=apk_entries.splitlines()
    native={name for name in entries if name.startswith('lib/') and not name.endswith('/')}
    expected={'lib/'+abi+'/'+name for abi in ENGINE_ABIS for name in ENGINE_LIBRARIES}
    if (not entries or len(entries)!=len(set(entries)) or native!=expected
            or 'assets/chaquopy/app.imy' not in entries or 'assets/web/index.html' not in entries
            or any(marker in apk_entries for marker in ('remote_test_ca','remote_qa_network_security','remoteqa/RemoteGateway'))):
        raise ValueError('Production APK contains unexpected code, test trust, or missing engine assets')
    if (not isinstance(proof,dict) or proof.get('schema')!='love-house-production-apk-boundary/v1'
            or proof.get('package_validated') is not True or proof.get('engine') is not True
            or proof.get('entry_count')!=len(entries)
            or not re.fullmatch(r'[0-9a-f]{64}',str(proof.get('sha256','')))):
        raise ValueError('Exact full-engine production package validation evidence is missing')


def check(directory, api_level):
    directory=Path(directory)
    positive=json.loads((directory/'android-remote-gateway.json').read_text())
    negative=json.loads((directory/'android-tls-rejection.json').read_text())
    state=json.loads((directory/'service-state.json').read_text())
    fixture=json.loads((directory/'fixture.json').read_text())
    permissions=(directory/'production-permissions.txt').read_text()
    apk_entries=(directory/'production-apk-entries.txt').read_text()
    package_proof=json.loads((directory/'production-package-verification.json').read_text())
    def require(condition,message):
        if condition is not True:raise ValueError(message)
    for report in (positive,negative):
        require(report.get('ok') is True and report.get('engine')=='Android System WebView','No successful actual Android WebView report')
        require(report.get('api_level')==api_level and bool(report.get('webview_version')),'Wrong Android API or missing system engine version')
        require(report.get('tls_bypass') is False and report.get('production_app_modified') is False,'TLS or production boundary was weakened')
    require(negative.get('tls_rejected') is True,'Untrusted-domain CA was not rejected')
    require(negative.get('http_reached_after_tls_error') is False,'TLS rejection still reached an HTTP response')
    for key in ('trusted_https_loaded','same_origin_referrer_policy','portal_login','http_only_cookie_hidden','conditional_host_receipt_ui_verified'):
        require(positive.get(key) is True,'Missing native portal proof: '+key)
    require(positive.get('ssl_errors')==0,'Trusted HTTPS had a native SSL error')
    config=positive.get('configuration',{})
    require(config.get('https_only') is True and config.get('no_local_command') is True and config.get('credentials_persisted') is False,'Remote configuration or browser credential isolation failed')
    result=positive.get('mcp_and_hook',{})
    for key in ('legacy_protocol','modern_protocol','bootstrap','tools_did_not_claim_auto','manual_did_not_claim_window',
                'host_hook_saved','foreign_window_excluded','original_user_readback','original_assistant_readback','agent_admin_isolation'):
        require(result.get(key) is True,'Missing real HTTPS interaction proof: '+key)
    require(state.get('node_count')==1 and state.get('original_user_saved') is True and state.get('original_assistant_saved') is True,'The actual MemoryHost did not retain exact synthetic dialogue')
    require(isinstance(result.get('actual_window'),str) and bool(result['actual_window']),'Actual host window identity is missing')
    require(any(c.get('archive_status')=='host_reported' and c.get('scope')=='next_session'
                and c.get('bound_session_id')==result['actual_window'] and c.get('automatic_memory') is False
                for c in state.get('connections',[])),'Actual service scope and conditional capture state disagree')
    require(fixture.get('public_ca_only') is True and fixture.get('production_app_modified') is False,'Test trust entered the wrong package')
    check_production_boundary(permissions,apk_entries,package_proof)
    print('Actual Android API '+str(api_level)+' WebView: TLS rejection/trust, portal, MCP, hook, exact roles, window and admin boundaries passed.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--api-level',type=int,required=True)
    args=parser.parse_args();check(args.directory,args.api_level)


if __name__=='__main__':main()
