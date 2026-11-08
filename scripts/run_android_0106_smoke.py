#!/usr/bin/env python3
"""Run the actual packaged tests, with an explicit scope for old WebView providers.

No private keys, model APIs, physical devices, emulator wipes or app-data clears.
JUnit is derived from the raw Android runner's verified start/pass records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from check_android_test_results import check
from verify_android_release import APP_ID, parse_instrumentation
from verify_signed_080rc2 import valid_png

ROOT = Path(__file__).resolve().parents[1]
LEGACY_CLASSES = (
    'io.github.myflww.lovehouse.MobileSmokeTest',
    'io.github.myflww.lovehouse.NativeSafExportTest',
    'io.github.myflww.lovehouse.AndroidWebViewCompatibilityTest',
)


def webview_identity(text: str) -> dict:
    found = re.findall(r'^\s*Current WebView package \(name, version\): '
                       r'\(([A-Za-z0-9_.]+), ([0-9]+(?:\.[0-9]+){1,4})\)\s*$', text, re.M)
    if len(found) != 1:
        raise ValueError('Exactly one actual current WebView provider is required')
    package, version = found[0]
    return {'package': package, 'version': version, 'major': int(version.split('.')[0])}


def scope_for(api: int, provider: dict) -> dict:
    if api not in (28, 36):
        raise ValueError('Only the reviewed Android API28/API36 matrices are supported')
    if provider['major'] >= 109:
        return {'instrumentation_scope': 'full_engine_and_legacy', 'expected_tests': 11,
                'full_engine_verified': True, 'partial': False, 'classes': None}
    if api == 36:
        raise ValueError('API36 must have a modern WebView and run the complete engine suite')
    return {'instrumentation_scope': 'legacy_and_provider_upgrade_only', 'expected_tests': 7,
            'full_engine_verified': False, 'partial': True, 'classes': LEGACY_CLASSES}


def verified_test_names(text: str, expected: int) -> list[tuple[str, str]]:
    counts = parse_instrumentation(text)
    if counts['tests'] != expected:
        raise ValueError('Actual test count differs from the selected explicit verification scope')
    status, passed = {}, []
    for line in text.splitlines():
        if line.startswith('INSTRUMENTATION_STATUS: '):
            key, _, value = line[len('INSTRUMENTATION_STATUS: '):].partition('=')
            status[key] = value
        elif line.startswith('INSTRUMENTATION_STATUS_CODE: '):
            if line == 'INSTRUMENTATION_STATUS_CODE: 0':
                passed.append((status['class'], status['test']))
            status = {}
    if len(passed) != expected or len(set(passed)) != expected:
        raise ValueError('Verified raw runner test identities are incomplete or repeated')
    return passed


def command(parts, *, timeout=120, binary=False):
    result = subprocess.run([str(part) for part in parts], capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError('An Android verification command did not complete successfully')
    if len(result.stdout) > 20 * 1024 * 1024:
        raise ValueError('Android command evidence exceeds the bounded size limit')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-level', required=True, type=int, choices=(28, 36))
    args = parser.parse_args()
    output = ROOT / 'build/android'
    output.mkdir(parents=True, exist_ok=True)
    report = {'schema': 'love-house-android-instrumentation/v2', 'ok': False, 'api_level': args.api_level}
    try:
        rows = [line.strip() for line in command(['adb', 'devices']).splitlines()[1:] if line.strip()]
        if len(rows) != 1 or not re.fullmatch(r'emulator-\d+\s+device', rows[0]):
            raise ValueError('Exactly one online disposable emulator and no physical device are required')
        serial = rows[0].split()[0]
        prefix = ['adb', '-s', serial]
        if command(prefix + ['shell', 'getprop', 'ro.kernel.qemu']).strip() != '1':
            raise ValueError('Physical devices are not accepted for this automated test')
        actual_api = command(prefix + ['shell', 'getprop', 'ro.build.version.sdk']).strip()
        if actual_api != str(args.api_level):
            raise ValueError('Actual emulator API differs from the requested matrix entry')
        provider = webview_identity(command(prefix + ['shell', 'dumpsys', 'webviewupdate']))
        scope = scope_for(args.api_level, provider)
        report.update(webview=provider, full_engine_verified=False,
                      full_engine_requested=scope['full_engine_verified'],
                      **{key: value for key, value in scope.items() if key not in ('classes', 'full_engine_verified')})
        debug = ROOT / 'android/app/build/outputs/apk/debug/app-debug.apk'
        test = ROOT / 'android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk'
        for apk, developer_test in ((debug, False), (test, True)):
            if not apk.is_file() or apk.is_symlink():
                raise ValueError('Built debug application or test APK is missing')
            command(prefix + ['install', '-r'] + (['-t'] if developer_test else []) + [apk], timeout=180)
        invocation = prefix + ['shell', 'am', 'instrument', '-w', '-r']
        if scope['classes']:
            invocation += ['-e', 'class', ','.join(scope['classes'])]
        invocation += [APP_ID + '.test/androidx.test.runner.AndroidJUnitRunner']
        transcript = command(invocation, timeout=900)
        (output / 'instrumentation.txt').write_text(transcript, encoding='utf-8')
        cases = verified_test_names(transcript, scope['expected_tests'])
        reports = ROOT / 'android/app/build/outputs/androidTest-results/connected'
        reports.mkdir(parents=True, exist_ok=True)
        suite = ET.Element('testsuite', {'name': 'ActualAndroidInstrumentation', 'tests': str(len(cases)),
                                        'failures': '0', 'errors': '0', 'skipped': '0'})
        for classname, name in cases:
            ET.SubElement(suite, 'testcase', {'classname': classname, 'name': name})
        ET.ElementTree(suite).write(reports / 'TEST-raw-android-runner.xml', encoding='utf-8', xml_declaration=True)
        counts = check(reports)
        if counts['tests'] != scope['expected_tests']:
            raise ValueError('JUnit evidence includes a different or duplicated test run')
        screenshots = []
        names = ['android-smoke.png']
        if scope['full_engine_verified']:
            names.append('android-engine-smoke.png')
        for name in names:
            raw = command(prefix + ['exec-out', 'run-as', APP_ID, 'cat', 'files/' + name], binary=True)
            valid_png(raw)
            (output / name).write_bytes(raw)
            screenshots.append({'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                                'source': 'actual_packaged_instrumentation_before_cleanup'})
        report.update(ok=True, full_engine_verified=scope['full_engine_verified'],
                      **{key: value for key, value in counts.items() if key != 'ok'},
                      screenshots=screenshots, model_calls=0,
                      tested_apk={'kind': 'debug_QA_not_public_release', 'sha256': hashlib.sha256(debug.read_bytes()).hexdigest()})
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report['error'] = str(exc) if type(exc) is ValueError else type(exc).__name__
        return 1
    finally:
        (output / 'instrumentation-verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report))


if __name__ == '__main__':
    raise SystemExit(main())
