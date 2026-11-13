#!/usr/bin/env python3
"""Verify a frozen original-signed release on a fresh disposable emulator.

Preserves real synthetic legacy memories through public 0.10.6 -> new APK
replacement and two process restarts, then runs the frozen packaged tests.
No private key, model call, physical device, uninstall or data clear is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile

from sign_android_release import (APP_ID, ORIGINAL_CERT, archive_payload,
                                 load_manifest, REPORT as SIGNING_REPORT)
from verify_android_release import (badging_identity, instrumentation_identity,
                                    signer_digest, validate_package_contents)
from run_android_0106_smoke import scope_for, verified_test_names, webview_identity

OLD = {'version_name': '0.10.6rc1', 'version_code': 4, 'bytes': 48430105,
       'sha256': '4d27f0a732c6edc53fbfcdcaac43f573b91327b703e10396e5d0c8435390f018',
       'url': 'https://github.com/myflww/love-house/releases/download/v0.10.6rc1/LoveHouse-0.10.6rc1-Android.apk'}
QA_RUNNER = 'io.github.myflww.lovehouse.upgradeqa/io.github.myflww.lovehouse.upgradeqa.UpgradeProbeInstrumentation'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def command(parts, timeout=120):
    result = subprocess.run([str(p) for p in parts], capture_output=True, timeout=timeout)
    require(result.returncode == 0 and len(result.stdout) < 20 * 1024 * 1024,
            'Android verification command failed or exceeded its evidence budget')
    return result.stdout.decode('utf-8', errors='replace')


def validate_receipt(receipt, manifest, paths):
    require(receipt.get('schema') == 'love-house-android-original-signing/v1', 'Unknown signing receipt')
    for key in ('source_commit', 'application_id', 'version_name', 'version_code', 'certificate_sha256'):
        require(receipt.get(key) == manifest[key], 'Signing receipt identity differs from the frozen handoff')
    require(receipt.get('same_original_signer') is True and receipt.get('payload_preserved') is True
            and receipt.get('signature_and_metadata') == 'passed', 'Signing receipt is incomplete')
    require(receipt.get('source_archive') == manifest['source_archive'], 'Signing receipt uses another source archive')
    for key in ('apk', 'test_apk'):
        require(receipt.get('inputs', {}).get(key) == manifest[key], 'Signing receipt uses another unsigned input')
        entry = receipt.get('signed', {}).get(key, {})
        path = paths[key]
        require(path.is_file() and not path.is_symlink() and entry.get('path') == path.name,
                'Signed APK path differs from its frozen receipt')
        require(entry.get('bytes') == path.stat().st_size and entry.get('sha256') == sha(path)
                and entry.get('certificate_sha256') == ORIGINAL_CERT
                and entry.get('qa_only') is (key == 'test_apk'), 'Signed APK bytes differ from their receipt')


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        parsed = urllib.parse.urlparse(new_url)
        require(parsed.scheme == 'https' and parsed.hostname in
                {'github.com', 'release-assets.githubusercontent.com', 'github-releases.githubusercontent.com'},
                'Unexpected anonymous old-release redirect')
        return urllib.request.Request(new_url, headers={'User-Agent': 'LoveHouse-Android-Upgrade-QA'})


def fetch_old(path):
    request = urllib.request.Request(OLD['url'], headers={'User-Agent': 'LoveHouse-Android-Upgrade-QA'})
    with urllib.request.build_opener(PublicRedirect()).open(request, timeout=180) as response:
        raw = response.read(OLD['bytes'] + 1)
    require(len(raw) == OLD['bytes'] and hashlib.sha256(raw).hexdigest() == OLD['sha256'],
            'Public old APK differs from the fixed original-signed release')
    with path.open('xb') as stream:
        stream.write(raw)


def parse_probe(text, mode, api, version_code):
    require(mode in ('seed', 'verify') and api in (28, 36), 'Unknown upgrade probe scope')
    require(re.findall(r'^INSTRUMENTATION_CODE: (-?\d+)\s*$', text, re.M) == ['-1']
            and not re.search(r'INSTRUMENTATION_FAILED|shortMsg=|Process crashed|FAILURES!!!', text),
            'Real upgrade probe failed')
    expected = {'mode': mode, 'protocol': 'love-house-ui-upgrade/v1', 'target_package': APP_ID,
                'ok': 'true', 'api_level': str(api), 'from_version_code': '4',
                'expected_version_code': str(4 if mode == 'seed' else version_code),
                'same_original_certificate': 'true', 'original_text_preserved': 'true',
                'assistant_reply_preserved': 'true', 'tags_preserved': 'true'}
    for key, value in expected.items():
        require(re.findall(r'^INSTRUMENTATION_RESULT: ' + key + r'=([^\r\n]*)\s*$', text, re.M) == [value],
                'Upgrade probe does not contain one complete preservation receipt')


def identity(path, tools, version, code, *, test=False):
    require(signer_digest(command([tools / 'apksigner', 'verify', '--verbose', '--print-certs', path])) == ORIGINAL_CERT,
            'APK is not signed by the original release certificate')
    command([tools / 'zipalign', '-c', '-P', '16', '4', path])
    badging = command([tools / 'aapt', 'dump', 'badging', path])
    value = badging_identity(badging)
    expected = (APP_ID + '.test', '', '') if test else (APP_ID, str(code), version)
    require((value['package'], value['version_code'], value['version_name']) == expected
            and value['min_sdk'] == ['26'] and value['target_sdk'] == ['36'], 'APK identity differs from the reviewed upgrade')
    xml = command([tools / 'aapt', 'dump', 'xmltree', path, 'AndroidManifest.xml'])
    if test:
        instrumentation_identity(xml)
    else:
        require('application-debuggable' not in badging and not re.search(
            r'android:(?:debuggable|testOnly)\([^)]*\)=\(type 0x12\)0xffffffff', xml), 'Public APK must be a release build')
        with zipfile.ZipFile(path) as archive:
            validate_package_contents(archive, badging, engine=True)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--signed-dir', type=Path, required=True)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--expected-version-name', required=True)
    parser.add_argument('--expected-version-code', type=int, required=True)
    parser.add_argument('--sdk', type=Path, default=Path(os.environ.get('ANDROID_HOME', '')))
    parser.add_argument('--probe-apk', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--api-level', type=int, choices=(28, 36), required=True)
    args = parser.parse_args()
    require(os.name != 'nt', 'Run exact signed acceptance on a Linux/macOS disposable emulator host')
    require(not args.output_dir.exists() and args.output_dir.parent.is_dir(), 'Choose a fresh verification directory')
    args.output_dir.mkdir()
    report = {'schema': 'love-house-android-signed-upgrade/v1', 'ok': False,
              'source_commit': args.expected_source_commit, 'api_level': args.api_level, 'model_calls': 0}
    try:
        value, inputs = load_manifest(args.manifest, args.expected_source_commit,
                                      args.expected_version_name, args.expected_version_code)
        require(value['version_code'] > OLD['version_code'], 'New release must increase the public old version code')
        signed = args.signed_dir.resolve()
        paths = {'apk': signed / f'LoveHouse-{value["version_name"]}-Android.apk',
                 'test_apk': signed / f'LoveHouse-{value["version_name"]}-Android-QA-ONLY.apk'}
        receipt_path = signed / SIGNING_REPORT
        receipt = json.loads(receipt_path.read_text('utf-8'))
        validate_receipt(receipt, value, paths)
        require(receipt.get('input_manifest_sha256') == sha(args.manifest), 'Signing input manifest changed')
        for key in paths:
            require(archive_payload(paths[key]) == archive_payload(inputs[key]), 'Signed payload differs from the reviewed unsigned build')
        tools = args.sdk / 'build-tools/36.0.0'
        identities = {key: identity(path, tools, value['version_name'], value['version_code'], test=key == 'test_apk')
                      for key, path in paths.items()}
        adb_tool = args.sdk / 'platform-tools/adb'
        require(adb_tool.is_file(), 'The selected Android SDK has no platform-tools/adb')
        rows = [row.strip() for row in command([adb_tool, 'devices']).splitlines()[1:] if row.strip()]
        require(len(rows) == 1 and re.fullmatch(r'emulator-\d+\s+device', rows[0]), 'Exactly one fresh emulator and no physical device is required')
        adb = [adb_tool, '-s', rows[0].split()[0]]
        require(command(adb + ['shell', 'getprop', 'ro.kernel.qemu']).strip() == '1', 'Physical devices are not accepted')
        require(command(adb + ['shell', 'getprop', 'ro.build.version.sdk']).strip() == str(args.api_level), 'Wrong actual emulator API')
        require(not command(adb + ['shell', 'pm', 'list', 'packages', APP_ID]).strip(), 'Use a fresh emulator; existing app data will not be removed')
        provider = webview_identity(command(adb + ['shell', 'dumpsys', 'webviewupdate']))
        scope = scope_for(args.api_level, provider)
        report.update(webview=provider, instrumentation_scope=scope['instrumentation_scope'], partial=scope['partial'])
        old = args.output_dir / 'public-old-0.10.6rc1.apk'
        fetch_old(old)
        identity(old, tools, OLD['version_name'], OLD['version_code'])
        require(args.probe_apk.is_file() and not args.probe_apk.is_symlink(), 'Built standalone UI upgrade probe is missing')
        require('Success' in command(adb + ['install', old], 180), 'Public old APK install failed')
        require('Success' in command(adb + ['install', '-t', args.probe_apk], 180), 'Standalone upgrade probe install failed')
        transcripts = {}
        def probe(mode, name):
            text = command(adb + ['shell', 'am', 'instrument', '-w', '-r', '-e', 'mode', mode,
                '-e', 'from_version_code', '4', '-e', 'to_version_code', str(value['version_code']),
                '-e', 'to_version_name', value['version_name'], QA_RUNNER], 300)
            (args.output_dir / (name + '.txt')).write_text(text, encoding='utf-8')
            parse_probe(text, mode, args.api_level, value['version_code'])
            transcripts[name] = hashlib.sha256(text.encode()).hexdigest()
        probe('seed', 'seed')
        command(adb + ['shell', 'am', 'force-stop', APP_ID])
        require('Success' in command(adb + ['install', '-r', paths['apk']], 180), 'In-place original-signed upgrade failed')
        probe('verify', 'verify')
        command(adb + ['shell', 'am', 'force-stop', APP_ID])
        probe('verify', 'verify_restart')
        require('Success' in command(adb + ['install', '-r', '-t', paths['test_apk']], 180), 'Frozen original-signed instrumentation install failed')
        invocation = adb + ['shell', 'am', 'instrument', '-w', '-r']
        if scope['classes']:
            invocation += ['-e', 'class', ','.join(scope['classes'])]
        text = command(invocation + [APP_ID + '.test/androidx.test.runner.AndroidJUnitRunner'], 1200)
        (args.output_dir / 'instrumentation.txt').write_text(text, encoding='utf-8')
        cases = verified_test_names(text, scope['expected_tests'])
        report.update(ok=True, certificate_sha256=ORIGINAL_CERT, identities=identities,
            version_name=value['version_name'], version_code=value['version_code'],
            tested_apk={'bytes': paths['apk'].stat().st_size, 'sha256': sha(paths['apk'])},
            signing_receipt_sha256=sha(receipt_path), input_manifest_sha256=sha(args.manifest),
            upgrade_preservation={'passed': True, 'in_place': True, 'from_version_code': 4,
                'to_version_code': value['version_code'], 'after_process_restart': True,
                'scope': 'legacy_original_text_reply_tags'},
            full_engine_verified=scope['full_engine_verified'],
            instrumentation={'tests': len(cases), 'failures': 0, 'errors': 0, 'skipped': 0},
            instrumentation_sha256=hashlib.sha256(text.encode()).hexdigest(), transcripts=transcripts)
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        report['error'] = str(error) if type(error) is ValueError else type(error).__name__
        return 1
    finally:
        (args.output_dir / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report))


if __name__ == '__main__':
    raise SystemExit(main())
