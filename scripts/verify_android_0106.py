#!/usr/bin/env python3
"""Exercise original-signed APK bytes through a real public-old-package upgrade.

Disposable hosted emulators only. No private signing material, model APIs,
physical devices, uninstall, app-data clear, downgrade or replacement debug app.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import zipfile

from verify_android_release import (badging_identity, instrumentation_identity,
                                    signer_digest, validate_package_contents,
                                    parse_instrumentation)
from run_android_0106_smoke import webview_identity, scope_for, verified_test_names
from verify_signed_080rc2 import valid_png

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '732d7df84815e7b360f3bf1820b261747ae1d047'
APP = 'io.github.myflww.lovehouse.preview'
CERT = 'ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc'
EXTRA = 'io.github.myflww.lovehouse.extraqa'
RUNNER = 'io.github.myflww.lovehouse.upgradeqa.UpgradeProbeInstrumentation'
EXPECTED = {'apk': (48430105, '4d27f0a732c6edc53fbfcdcaac43f573b91327b703e10396e5d0c8435390f018'),
            'test_apk': (914423, '7fd6efc07b602d6ccb056550a1fd3149e112ca5175fe94df730b5e61240412f2')}
OLD = {'url': 'https://github.com/myflww/love-house/releases/download/v0.8.0rc2/LoveHouse-0.8.0rc2-Android.apk',
       'bytes': 2646434, 'sha256': '79a23dfa571cd6d10668e882c3b923e22e24b7658a935b46253d7fbee804915a',
       'version_name': '0.8.0rc2', 'version_code': 3}
MODES = {'seed', 'verify', 'credential_seed', 'credential_delete', 'migrate', 'persisted'}
SOURCE_ARCHIVE = (16785970, 'ab273124f3fa3781f57e1780f74b5aee09b1941219ec9e2622f82e914050531d')
UNSIGNED_INPUTS = {'apk': (48409678, 'faf64b0886f39a458a5e835ac5385073d525fe2dc471e322a4940864138c838b'),
                   'test_apk': (911171, '411ef0c7753bc98201be56c8923b4b21631486e46129ce51971edefd4828982b')}

def require(value, message):
    if not value:
        raise ValueError(message)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()

def ordinary(path):
    require(path.is_file() and not path.is_symlink(), 'A fixed input file is unavailable')
    require(path.resolve().is_relative_to(ROOT), 'An input path leaves the task checkout')
    return path

def record(raw, value, git=False):
    require(type(value.get('bytes')) is int and 0 < value['bytes'] <= 150 * 1024 * 1024,
            'Input size is outside the bounded APK budget')
    require(len(raw) == value['bytes'] and digest(raw) == value.get('sha256'), 'Fixed file hash mismatch')
    if git:
        require(blob(raw) == value.get('blob_sha'), 'Fixed file Git blob mismatch')

def candidate(path):
    value = json.loads(ordinary(path).read_text('utf-8'))
    require(value.get('schema') == 'love-house-android-0106-candidate/v1', 'Unknown original-signed candidate schema')
    require((value.get('source_commit'), value.get('build_run_id'), value.get('application_id'),
             value.get('version_name'), value.get('version_code'), value.get('certificate_sha256')) ==
            (SOURCE, 42439732197, APP, '0.10.6rc1', 4, CERT), 'Candidate differs from the frozen source build')
    require(type(value['version_code']) is int and type(value['build_run_id']) is int, 'Candidate versions are not integer identities')
    require(value.get('old_apk') == OLD, 'Public old APK identity changed')
    require(set(value.get('artifacts', {})) == {'apk', 'test_apk', 'extra_qa'}, 'Expected all three separate signed APKs')
    for key, (size, sha) in EXPECTED.items():
        require((value['artifacts'][key].get('bytes'), value['artifacts'][key].get('sha256')) == (size, sha),
                'Production APK differs from the locally signed fixed payload')
    return value

def validate_signing_receipt(signing, value):
    require(signing.get('schema') == 'love-house-android-0106-original-signing/v1'
            and signing.get('source_commit') == SOURCE and signing.get('same_original_signer') is True
            and signing.get('payload_preserved') is True and signing.get('signature_and_metadata') == 'passed',
            'Original signing receipt does not match the frozen APK inputs')
    require((signing.get('application_id'), signing.get('version_name'), signing.get('version_code'),
             signing.get('certificate_sha256')) == (APP, '0.10.6rc1', 4, CERT)
            and type(signing.get('version_code')) is int, 'Signing receipt package identity changed')
    require(signing.get('input_manifest_sha256') == '6976945a77dd1a9f5bc1de2c56370eb5fa3580923f5af069f3faf76b494360ec'
            and signing.get('apksigner_jar_sha256') == '3716d9311e55d2b0918a2fd9d54ba9e406c5f6abeea700b287f11259bc163dec',
            'Signing receipt did not verify the fixed handoff and official tool')
    require((signing.get('source_archive', {}).get('bytes'), signing.get('source_archive', {}).get('sha256')) == SOURCE_ARCHIVE,
            'Signing receipt refers to another source archive')
    for key in EXPECTED:
        signed = signing.get('signed', {}).get(key, {})
        require((signed.get('bytes'), signed.get('sha256')) == EXPECTED[key]
                and (signed.get('bytes'), signed.get('sha256')) ==
                    (value['artifacts'][key]['bytes'], value['artifacts'][key]['sha256'])
                and signed.get('certificate_sha256') == CERT and signed.get('qa_only') is (key == 'test_apk'),
                'Signing receipt does not bind the actual signed app and frozen QA bytes')
        identity = signed.get('identity', {})
        expected = (APP, '4', '0.10.6rc1') if key == 'apk' else (APP + '.test', '', '')
        require((identity.get('package'), identity.get('version_code'), identity.get('version_name')) == expected
                and identity.get('min_sdk') == ['26'] and identity.get('target_sdk') == ['36'],
                'Signing receipt APK identity changed')
        before = signing.get('inputs', {}).get(key, {})
        require((before.get('bytes'), before.get('sha256')) == UNSIGNED_INPUTS[key], 'Signing receipt uses different frozen unsigned inputs')

def assemble(value, destination):
    parts = value.get('parts')
    require(isinstance(parts, list) and 0 < len(parts) <= 400, 'APK parts are unavailable')
    result = bytearray()
    names = set()
    for part in parts:
        name = part.get('path', '')
        require(isinstance(name, str) and name.startswith('release-handoff/0.10.6rc1/')
                and '\\' not in name and ':' not in name and '\0' not in name
                and all(p not in ('', '.', '..') for p in name.split('/')),
                'An APK part is outside the fixed developer handoff')
        require(name not in names, 'Repeated APK part')
        names.add(name)
        raw = ordinary(ROOT / name).read_bytes()
        record(raw, part, git=True)
        result.extend(raw)
        require(len(result) <= value['bytes'], 'APK parts exceed the fixed size')
    record(result, value, git=True)
    require(not destination.exists(), 'Choose a fresh generated verification directory')
    destination.write_bytes(result)
    return destination

class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        require(req.get_method() == 'GET' and parsed.scheme == 'https' and parsed.hostname in
                {'github.com', 'release-assets.githubusercontent.com', 'github-releases.githubusercontent.com'},
                'Unexpected anonymous old-release redirect')
        return urllib.request.Request(newurl, headers={'User-Agent': 'LoveHouse-Original-Signed-0106-QA'})

def fetch_old(path):
    request = urllib.request.Request(OLD['url'], headers={'User-Agent': 'LoveHouse-Original-Signed-0106-QA'})
    with urllib.request.build_opener(PublicRedirect()).open(request, timeout=120) as response:
        raw = response.read(OLD['bytes'] + 1)
    record(raw, OLD)
    path.write_bytes(raw)
    return path

def command(parts, timeout=120, binary=False):
    result = subprocess.run([str(p) for p in parts], capture_output=True, timeout=timeout)
    require(len(result.stdout) < 20 * 1024 * 1024, 'Command evidence exceeds its byte budget')
    require(result.returncode == 0, 'An Android verification tool failed')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')

def identity(path, sdk, kind):
    tools = sdk / 'build-tools/36.0.0'
    cert = signer_digest(command([tools / 'apksigner', 'verify', '--verbose', '--print-certs', path]))
    require(cert == CERT, 'APK is not signed by the original certificate')
    command([tools / 'zipalign', '-c', '-P', '16', '4', path])
    badging = command([tools / 'aapt', 'dump', 'badging', path])
    result = badging_identity(badging)
    xml = command([tools / 'aapt', 'dump', 'xmltree', path, 'AndroidManifest.xml'])
    expected = {'apk': (APP, '4', '0.10.6rc1'), 'old': (APP, '3', '0.8.0rc2'),
                'test_apk': (APP + '.test', '', ''), 'extra_qa': (EXTRA, '1', '1')}[kind]
    require((result['package'], result['version_code'], result['version_name']) == expected
            and result['min_sdk'] == ['26'] and result['target_sdk'] == ['36'],
            'APK identity differs from its fixed original-signed role')
    if kind in ('apk', 'old'):
        require('application-debuggable' not in badging and not re.search(
            r'android:(?:debuggable|testOnly)\([^)]*\)=\(type 0x12\)0xffffffff', xml),
            'Public main APK must not be a debug or test build')
        with zipfile.ZipFile(path) as archive:
            validate_package_contents(archive, badging, engine=kind == 'apk')
    elif kind == 'test_apk':
        runner, target = instrumentation_identity(xml)
        result.update(runner=runner, target_package=target)
    else:
        blocks = re.findall(r'^\s*E: instrumentation\b[^\n]*\n((?:\s+A: [^\n]*\n?)+)', xml, re.M)
        require(len(blocks) == 1 and re.findall(r'android:name\([^)]*\)="([^"]+)"', blocks[0]) == [RUNNER]
                and re.findall(r'android:targetPackage\([^)]*\)="([^"]+)"', blocks[0]) == [APP],
                'Supplemental QA runner does not target the actual release process')
        result.update(runner=RUNNER, target_package=APP)
    result['certificate_sha256'] = cert
    return result

def parse_probe(text, mode, api_level):
    require(mode in MODES and api_level in (28, 36), 'Unreviewed supplemental verification mode')
    require(re.findall(r'^INSTRUMENTATION_CODE: (-?\d+)\s*$', text, re.M) == ['-1'], 'Supplemental runner failed')
    require(not re.search(r'INSTRUMENTATION_FAILED|shortMsg=|Process crashed|FAILURES!!!', text), 'Supplemental runner crashed')
    expected = {'mode': mode, 'protocol': 'love-house-original-upgrade-0106/v1', 'ok': 'true',
                'api_level': str(api_level), 'original_certificate': 'true',
                'version_code': '3' if mode == 'seed' else '4', 'model_calls': '0'}
    for name, val in expected.items():
        require(re.findall(r'^INSTRUMENTATION_RESULT: ' + name + r'=([^\r\n]*)\s*$', text, re.M) == [val],
                'Supplemental runner receipt is incomplete or repeated')
    require(not re.search(r'^INSTRUMENTATION_RESULT: (?:error_stage|exception)=', text, re.M), 'Supplemental runner has a failure receipt')
    return {'mode': mode, 'api_level': api_level, 'protocol': expected['protocol'], 'version_code': int(expected['version_code']),
            'ok': True, 'original_certificate': True, 'model_calls': 0}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-level', type=int, choices=(28, 36), required=True)
    parser.add_argument('--diagnostic-only', action='store_true', help='Non-release API36 timeout/stack investigation only')
    args = parser.parse_args()
    output = ROOT / 'build/android0106'
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'love-house-android-original-signed-0106-acceptance/v1', 'ok': False,
              'source_commit': SOURCE, 'api_level': args.api_level, 'model_calls': 0}
    if args.diagnostic_only:
        require(args.api_level == 36, 'Supplemental diagnostic uses only the API36 disposable emulator')
        report.update(diagnostic_only=True, public_release_evidence=False)
    stage = 'candidate'
    try:
        require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted',
                'This installer accepts only disposable GitHub-hosted runners')
        value = candidate(ROOT / 'release-handoff/0.10.6rc1/candidate.json')
        report['candidate_sha256'] = digest((ROOT / 'release-handoff/0.10.6rc1/candidate.json').read_bytes())
        require(not command(['git', '-C', ROOT, 'diff', '--name-only', SOURCE, 'HEAD', '--',
                             'android/app', 'android/build.gradle', 'android/settings.gradle', 'android/gradle.properties',
                             'mobile/web', 'nkb', 'scripts/prepare_android_engine.py', 'scripts/prepare_mobile_assets.py']).strip(),
                'Frozen production source changed during signing acceptance')
        receipt = value['signing_receipt']
        original = ordinary(ROOT / receipt['path']).read_bytes();record(original, receipt)
        signing = json.loads(original)
        validate_signing_receipt(signing, value)
        (output / 'Android-0106-original-signing-verification.json').write_bytes(original)
        filenames = {'apk': 'LoveHouse-0.10.6rc1-Android.apk', 'test_apk': 'frozen-QA-only.apk', 'extra_qa': 'supplemental-QA-only.apk'}
        paths = {key: assemble(entry, output / filenames[key]) for key, entry in value['artifacts'].items()}
        sdk = Path(os.environ['ANDROID_HOME'])
        report['identities'] = {key: identity(path, sdk, key) for key, path in paths.items()}
        report['extra_qa_identity'] = report['identities']['extra_qa']
        report['certificate_sha256'] = CERT
        for name, key in [('tested_apk', 'apk'), ('frozen_test_apk', 'test_apk'), ('extra_qa_apk', 'extra_qa')]:
            report[name] = {field: value['artifacts'][key][field] for field in ('bytes', 'sha256')}
        stage = 'disposable_emulator'
        rows = [line.strip() for line in command(['adb', 'devices']).splitlines()[1:] if line.strip()]
        require(len(rows) == 1 and re.fullmatch(r'emulator-\d+\s+device', rows[0]), 'Exactly one disposable emulator required')
        prefix = ['adb', '-s', rows[0].split()[0]]
        require(command(prefix + ['shell', 'getprop', 'ro.kernel.qemu']).strip() == '1', 'Physical devices are not accepted')
        require(command(prefix + ['shell', 'getprop', 'ro.build.version.sdk']).strip() == str(args.api_level), 'Wrong actual emulator API')
        require(not command(prefix + ['shell', 'pm', 'list', 'packages', APP]).strip(), 'Fresh emulator required; existing app data will not be removed')
        provider = webview_identity(command(prefix + ['shell', 'dumpsys', 'webviewupdate']))
        scope = scope_for(args.api_level, provider)
        report.update(webview=provider, instrumentation_scope=scope['instrumentation_scope'], partial=scope['partial'], full_engine_verified=False)
        stage = 'public_original_apk'
        old = fetch_old(output / 'public-old-0.8.0rc2.apk');report['old_apk_identity'] = identity(old, sdk, 'old')
        require('Success' in command(prefix + ['install', old], timeout=180), 'Old public release install failed')
        require('Success' in command(prefix + ['install', '-t', paths['extra_qa']], timeout=180), 'Supplemental original-signed QA install failed')
        results = []
        transcripts = {}
        def capture_diagnostics(label, *, stack=False):
            # Entire emulator is fresh and owned. No real libraries/keys exist.
            # Read only synthetic activity metadata, crash output and PNGs.
            for name, tail in [('activity', ['shell', 'dumpsys', 'activity', 'top']),
                               ('fatal', ['logcat', '-d', '-t', '500', '-s', 'AndroidRuntime:E'])]:
                try:
                    raw = command(prefix + tail, timeout=20).encode('utf-8')[:262144]
                    (output / (label + '-' + name + '-diagnostic.txt')).write_bytes(raw)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            try:
                raw = command(prefix + ['exec-out', 'screencap', '-p'], timeout=20, binary=True)
                valid_png(raw);(output / (label + '-synthetic-timeout.png')).write_bytes(raw)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            if stack:
                try:
                    command(prefix + ['root'], timeout=20);command(prefix + ['wait-for-device'], timeout=20)
                    pid = command(prefix + ['shell', 'pidof', APP], timeout=15).strip()
                    require(bool(re.fullmatch(r'[0-9]+', pid)), 'Only the exact owned target process may be dumped')
                    command(prefix + ['shell', 'kill', '-3', pid], timeout=15)
                    # SIGQUIT writes Android's managed-thread dump under /data/anr.
                    import time
                    time.sleep(3)
                    listing = command(prefix + ['shell', 'ls', '-t', '/data/anr'], timeout=15).splitlines()
                    for name in listing[:2]:
                        if re.fullmatch(r'anr_[A-Za-z0-9_.-]{1,100}', name):
                            raw = command(prefix + ['exec-out', 'cat', '/data/anr/' + name], timeout=20, binary=True)
                            (output / (label + '-' + name + '-diagnostic.txt')).write_bytes(raw[:1048576])
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
        def probe(mode, filename):
            nonlocal stage
            stage = filename
            stop = threading.Event()
            observer = None
            if args.diagnostic_only and mode == 'migrate':
                def observe():
                    if not stop.wait(60):
                        capture_diagnostics('migrate-60s', stack=True)
                observer = threading.Thread(target=observe, daemon=True)
                observer.start()
            try:
                text = command(prefix + ['shell', 'am', 'instrument', '-w', '-r', '-e', 'mode', mode, EXTRA + '/' + RUNNER], timeout=180 if args.diagnostic_only and mode == 'migrate' else 600)
            except subprocess.TimeoutExpired as exc:
                raw = exc.stdout or b''
                if isinstance(raw, str):
                    raw = raw.encode('utf-8')
                raw = raw[:1048576]
                (output / (filename + '-probe.txt')).write_bytes(raw)
                text = raw.decode('utf-8', errors='replace')
                phases = re.findall(r'^INSTRUMENTATION_STATUS: qa_stage=([A-Za-z0-9_]{1,80})\s*$', text, re.M)
                safe = {'mode': mode, 'exception': 'TimeoutExpired'}
                if phases:
                    safe['error_stage'] = phases[-1]
                report['supplemental_failure'] = safe
                print(json.dumps({'supplemental_failure': safe}))
                capture_diagnostics(filename + '-timeout', stack=args.diagnostic_only)
                raise
            finally:
                stop.set()
                if observer:
                    observer.join(timeout=60)
            (output / (filename + '-probe.txt')).write_text(text, encoding='utf-8', newline='\n')
            transcripts[filename + '-probe.txt'] = digest(text.encode('utf-8'))
            try:
                result = parse_probe(text, mode, args.api_level)
            except ValueError:
                safe = {'mode': mode}
                for key in ('error_stage', 'exception'):
                    found = re.findall(r'^INSTRUMENTATION_RESULT: ' + key + r'=([A-Za-z0-9_]{1,80})\s*$', text, re.M)
                    if len(found) == 1:
                        safe[key] = found[0]
                report['supplemental_failure'] = safe
                print(json.dumps({'supplemental_failure': safe}))
                raise
            result['transcript'] = filename + '-probe.txt';results.append(result)
        def restart():
            command(prefix + ['shell', 'am', 'force-stop', APP])
        probe('seed', 'seed');restart()
        stage = 'in_place_upgrade'
        require('Success' in command(prefix + ['install', '-r', paths['apk']], timeout=180), 'Original-signed in-place replacement failed')
        probe('verify', 'verify');restart();probe('verify', 'verify_restart')
        report['upgrade_preservation'] = {'passed': True, 'from_version_code': 3, 'to_version_code': 4,
                                           'libraries': 2, 'in_place': True, 'after_restart': True}
        require('Success' in command(prefix + ['install', '-r', '-t', paths['test_apk']], timeout=180), 'Frozen original-signed test install failed')
        probe('credential_seed', 'credential_seed');restart();probe('credential_delete', 'credential_delete')
        if scope['full_engine_verified']:
            restart();probe('migrate', 'migrate');restart();probe('persisted', 'persisted')
        if args.diagnostic_only:
            report['diagnostic_completed'] = True
            return 1  # Diagnostic-only runs can never become release evidence.
        report['supplemental'] = {'passed': True, 'modes': [x.removesuffix('-probe.txt') for x in transcripts], 'results': results,
                                  'migration': 'passed' if scope['full_engine_verified'] else 'requires_modern_webview',
                                  'complete_engine_export_restore_saf': 'passed' if scope['full_engine_verified'] else 'requires_modern_webview',
                                  'credential_process_restart_delete': 'passed'}
        stage = 'frozen_instrumentation'
        restart()
        invocation = prefix + ['shell', 'am', 'instrument', '-w', '-r']
        if scope['classes']:
            invocation += ['-e', 'class', ','.join(scope['classes'])]
        invocation += [APP + '.test/androidx.test.runner.AndroidJUnitRunner']
        text = command(invocation, timeout=1200)
        (output / 'instrumentation.txt').write_text(text, encoding='utf-8', newline='\n')
        transcripts['instrumentation.txt'] = digest(text.encode('utf-8'))
        cases = verified_test_names(text, scope['expected_tests'])
        counts = parse_instrumentation(text)
        require(counts == {'tests': scope['expected_tests'], 'failures': 0, 'errors': 0, 'skipped': 0}, 'Frozen actual tests did not all pass')
        report['instrumentation'] = counts
        report['frozen_test_names'] = [{'class': cls, 'test': name} for cls, name in cases]
        stage = 'actual_screenshots'
        command(prefix + ['root']);command(prefix + ['wait-for-device'])
        screenshots = []
        for filename in ['android-smoke.png'] + (['android-engine-smoke.png'] if scope['full_engine_verified'] else []):
            raw = command(prefix + ['exec-out', 'cat', '/data/user/0/' + APP + '/files/' + filename], binary=True)
            valid_png(raw);(output / filename).write_bytes(raw)
            screenshots.append({'name': filename, 'bytes': len(raw), 'sha256': digest(raw)})
        report.update(ok=True, transcripts=transcripts, screenshots=screenshots, full_engine_verified=scope['full_engine_verified'])
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        report.update(error_stage=stage, error=str(exc) if type(exc) is ValueError else type(exc).__name__)
        return 1
    finally:
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps(report))

if __name__ == '__main__':
    raise SystemExit(main())
