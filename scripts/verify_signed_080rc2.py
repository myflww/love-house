#!/usr/bin/env python3
"""Verify fixed original-key 0.8.0rc2 APK bytes and preserve old memories on emulators.

No signing material is read. Only a bounded repository blob GET may use the
read-only GitHub token; downloads never forward that token to another origin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import urllib.request
import zipfile
import zlib

from verify_android_release import badging_identity, signer_digest, instrumentation_identity, parse_instrumentation

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'myflww/love-house'
SOURCE = 'ab373b9f6d5b1763b14eb5903a66fb20775eda73'
PRODUCTION_SOURCE = SOURCE
SCHEMA = 'love-house-signed-080rc2/v1'
APP_ID = 'io.github.myflww.lovehouse.preview'
CERT = 'ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc'
APK_NAME = 'LoveHouse-0.8.0rc2-Android.apk'
TEST_NAME = 'LoveHouse-0.8.0rc2-test-signed.apk'
QA_PACKAGE = 'io.github.myflww.lovehouse.upgradeqa'
QA_RUNNER = QA_PACKAGE + '/' + QA_PACKAGE + '.UpgradeProbeInstrumentation'
UPGRADE_FROM = {
    1: {'version_name': '0.1.0-preview1', 'bytes': 2642266,
        'sha256': '056a4669f6a723f0fbc9097af6628c090c4d3d047313e9754fd0f04cb3a72937',
        'url': 'https://github.com/myflww/love-house/releases/download/android-v0.1.0-preview1/LoveHouse-0.1.0-preview1-Android.apk'},
    2: {'version_name': '0.8.0rc1', 'bytes': 2646434,
        'sha256': 'c82c1ef486fcd74540a132267a80e3abdfddf3806aca7163e8c433efd8421f20',
        'url': 'https://github.com/myflww/love-house/releases/download/v0.8.0rc1/LoveHouse-0.8.0rc1-Android.apk'},
}
MAX_APK = 100 * 1024 * 1024


class VerificationError(ValueError):
    """Controlled, non-sensitive diagnostic."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def validate_candidate(value: dict) -> dict:
    require(isinstance(value, dict) and value.get('schema') == SCHEMA, 'Unknown fixed signing candidate schema')
    require(set(value) == {'schema','source_commit','handoff_commit','application_id','version_name','version_code','certificate_sha256','apk','test_apk'}, 'Unexpected fields in public candidate metadata')
    require(bool(re.fullmatch('[0-9a-f]{40}', SOURCE)) and SOURCE != '0' * 40, 'Frozen source commit has not been filled')
    require(value.get('source_commit') == PRODUCTION_SOURCE and value.get('handoff_commit') == SOURCE,
            'Candidate source is not the frozen handoff release')
    require(value.get('application_id') == APP_ID and value.get('version_name') == '0.8.0rc2'
            and type(value.get('version_code')) is int and value['version_code'] == 3,
            'Candidate package or version differs from the fixed upgrade')
    require(value.get('certificate_sha256') == CERT, 'Candidate does not use the original public certificate')
    for key in ('apk', 'test_apk'):
        entry = value.get(key)
        require(isinstance(entry, dict), 'APK metadata is missing')
        require(set(entry) == {'blob_sha','sha256','bytes'}, 'Unexpected fields in public APK metadata')
        require(bool(re.fullmatch('[0-9a-f]{40}', str(entry.get('blob_sha', '')))), 'Invalid Git blob digest')
        require(bool(re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256', '')))), 'Invalid APK SHA-256 digest')
        require(type(entry.get('bytes')) is int and 0 < entry['bytes'] <= MAX_APK, 'APK byte budget is invalid')
    require(value['apk']['blob_sha'] != value['test_apk']['blob_sha'], 'App and test harness cannot be the same APK')
    return value


def checked_bytes(raw: bytes, entry: dict) -> None:
    require(len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256'], 'APK bytes differ from signed metadata')
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    require(blob == entry['blob_sha'], 'Git blob bytes differ from signed metadata')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VerificationError('Repository blob redirects are not accepted')


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        parsed = urlparse(newurl)
        require(req.get_method() == 'GET' and parsed.scheme == 'https'
                and parsed.hostname in {'github.com', 'release-assets.githubusercontent.com', 'github-releases.githubusercontent.com'},
                'Unexpected public release download redirect')
        return urllib.request.Request(newurl, headers={'User-Agent': 'LoveHouse-Original-Key-Upgrade-QA'})


def fetch_candidate(entry: dict, destination: Path) -> None:
    require(not destination.is_symlink(), 'Candidate output is not an ordinary generated file')
    if destination.exists():
        require(destination.is_file() and not destination.is_symlink(), 'Candidate output is not an ordinary generated file')
        checked_bytes(destination.read_bytes(), entry)
        return
    headers = {'Accept': 'application/vnd.github.raw+json', 'X-GitHub-Api-Version': '2026-03-10',
               'User-Agent': 'LoveHouse-Original-Key-Upgrade-QA'}
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/git/blobs/' + entry['blob_sha'], headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as response:
        raw = response.read(entry['bytes'] + 1)
    checked_bytes(raw, entry)
    destination.write_bytes(raw)


def fetch_old(destination: Path, from_version_code: int) -> None:
    require(type(from_version_code) is int and from_version_code in UPGRADE_FROM, 'Unknown public upgrade starting version')
    old = UPGRADE_FROM[from_version_code]
    require(not destination.is_symlink(), 'Old APK output is not an ordinary generated file')
    if destination.exists():
        require(destination.is_file() and not destination.is_symlink(), 'Old APK output is not an ordinary generated file')
        raw = destination.read_bytes()
    else:
        request = urllib.request.Request(old['url'], headers={'User-Agent': 'LoveHouse-Original-Key-Upgrade-QA'})
        with urllib.request.build_opener(PublicRedirect()).open(request, timeout=120) as response:
            raw = response.read(old['bytes'] + 1)
        require(len(raw) == old['bytes'] and hashlib.sha256(raw).hexdigest() == old['sha256'], 'Public old APK download differs from the original release')
        destination.write_bytes(raw)
    require(len(raw) == old['bytes'] and hashlib.sha256(raw).hexdigest() == old['sha256'], 'Old APK differs from the original public release')


def run(command: list, *, timeout: int = 120) -> str:
    try:
        value = subprocess.run([str(part) for part in command], capture_output=True, encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise VerificationError('A required Android command could not complete') from None
    require(value.returncode == 0, 'An Android command failed: ' + Path(command[0]).name)
    return value.stdout


def tools_for(sdk: Path) -> dict:
    build = sdk / 'build-tools/36.0.0'
    suffix = '.exe' if os.name == 'nt' else ''
    return {'aapt': build / ('aapt' + suffix), 'zipalign': build / ('zipalign' + suffix),
            'apksigner': build / ('apksigner.bat' if os.name == 'nt' else 'apksigner'),
            'adb': sdk / 'platform-tools' / ('adb' + suffix)}


def checked_identity(path: Path, tools: dict, *, app: bool, from_version_code: int | None = None) -> dict:
    certificate = signer_digest(run([tools['apksigner'], 'verify', '--verbose', '--print-certs', path]))
    require(certificate == CERT, 'APK certificate does not match the original signing identity')
    run([tools['zipalign'], '-c', '-P', '16', '4', path])
    badging = run([tools['aapt'], 'dump', 'badging', path])
    identity = badging_identity(badging)
    manifest = run([tools['aapt'], 'dump', 'xmltree', path, 'AndroidManifest.xml'])
    if app:
        require(from_version_code is None or (type(from_version_code) is int and from_version_code in UPGRADE_FROM), 'Unknown old package version')
        expected = {'package': APP_ID, 'version_code': str(from_version_code or 3),
                    'version_name': UPGRADE_FROM[from_version_code]['version_name'] if from_version_code else '0.8.0rc2', 'min_sdk': ['26'], 'target_sdk': ['36']}
        require(identity == expected, 'App manifest differs from the fixed old or new release identity')
        require('application-debuggable' not in badging and not re.search(r'android:(?:debuggable|testOnly)\([^)]*\)=\(type 0x12\)0xffffffff', manifest),
                'The public app must be a non-debuggable release APK')
        require(not re.search(r'^uses-permission', badging, re.M), 'The offline app requests unexpected device permissions')
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            require(archive.testzip() is None and 'assets/web/index.html' in names,
                    'Local app assets are missing or corrupted')
            require(not any(re.fullmatch(r'lib/[^/]+/[^/]+\.so', name) for name in names), 'Unexpected native library in the universal app')
    else:
        require(identity['package'] == APP_ID + '.test' and identity['min_sdk'] == ['26'] and identity['target_sdk'] == ['36'],
                'Test harness identity or SDK differs from the frozen target')
        runner, target = instrumentation_identity(manifest)
        require(runner == 'androidx.test.runner.AndroidJUnitRunner' and target == APP_ID, 'Developer test runner differs from the release app target')
        identity.update(runner=runner, target_package=target)
    return identity


def parse_probe(text: str, mode: str, from_version_code: int, api_level: int) -> dict:
    require(mode in ('seed', 'verify'), 'Unknown upgrade probe mode')
    require(type(from_version_code) is int and from_version_code in UPGRADE_FROM, 'Unknown probe starting version')
    require(type(api_level) is int and api_level in (28, 36), 'Unknown probe emulator API')
    require(re.findall(r'^INSTRUMENTATION_CODE: (-?\d+)\s*$', text, re.M) == ['-1'], 'Upgrade probe did not finish successfully')
    require(re.findall(r'^INSTRUMENTATION_RESULT: ok=([^\r\n]*)\s*$', text, re.M) == ['true'], 'Upgrade probe did not report a true success result')
    require(re.findall(r'^INSTRUMENTATION_RESULT: mode=([^\r\n]*)\s*$', text, re.M) == [mode], 'Upgrade probe reported another mode')
    expected = {'protocol': 'love-house-ui-upgrade/v1', 'target_package': APP_ID,
                'from_version_code': str(from_version_code),
                'expected_version_code': str(from_version_code) if mode == 'seed' else '3',
                'same_original_certificate': 'true', 'original_text_preserved': 'true',
                'assistant_reply_preserved': 'true', 'tags_preserved': 'true'}
    for name, value in expected.items():
        require(re.findall(r'^INSTRUMENTATION_RESULT: ' + name + r'=([^\r\n]*)\s*$', text, re.M) == [value],
                'Upgrade probe did not report complete original-memory preservation')
    levels = re.findall(r'^INSTRUMENTATION_RESULT: api_level=([^\r\n]*)\s*$', text, re.M)
    require(levels == [str(api_level)], 'Upgrade probe did not identify the requested emulator')
    require(not re.search(r'INSTRUMENTATION_FAILED|shortMsg=|Process crashed|FAILURES!!!', text), 'Upgrade probe crashed or failed')
    return {'ok': True, 'mode': mode, 'api_level': int(levels[0]), 'from_version_code': from_version_code}


def valid_png(raw: bytes) -> None:
    require(8 < len(raw) <= 20 * 1024 * 1024 and raw.startswith(b'\x89PNG\r\n\x1a\n'), 'Actual emulator screenshot is missing')
    offset = 8
    first = True
    while offset + 12 <= len(raw):
        length = int.from_bytes(raw[offset:offset+4], 'big')
        kind = raw[offset+4:offset+8]
        end = offset + 8 + length
        require(end + 4 <= len(raw), 'Emulator screenshot has a truncated chunk')
        require(zlib.crc32(raw[offset+4:end]) & 0xffffffff == int.from_bytes(raw[end:end+4], 'big'), 'Emulator screenshot CRC failed')
        if first:
            require(kind == b'IHDR' and length == 13 and all(struct.unpack('>II', raw[offset+8:offset+16])), 'Emulator screenshot dimensions are invalid')
            first = False
        offset = end + 4
        if kind == b'IEND':
            require(length == 0 and offset == len(raw), 'Emulator screenshot has an invalid ending')
            return
    raise VerificationError('Emulator screenshot has no valid ending')


def exercise(candidate: dict, output: Path, tools: dict, api_level: int, qa_apk: Path, from_version_code: int) -> dict:
    adb = tools['adb']
    devices = [line.split()[0] for line in run([adb, 'devices']).splitlines() if re.fullmatch(r'emulator-\d+\s+device', line)]
    require(len(devices) == 1, 'Exactly one disposable emulator is required')
    prefix = [adb, '-s', devices[0]]
    require(run(prefix + ['shell', 'getprop', 'ro.kernel.qemu']).strip() == '1', 'Upgrade tests may run only on a disposable emulator')
    require(run(prefix + ['shell', 'getprop', 'ro.build.version.sdk']).strip() == str(api_level), 'Emulator API differs from the requested test')
    require(not run(prefix + ['shell', 'pm', 'list', 'packages', APP_ID]).strip(), 'Upgrade QA requires a fresh emulator; existing app data will not be removed')
    old = output / ('LoveHouse-from-' + str(from_version_code) + '-Android.apk')
    fetch_old(old, from_version_code)
    checked_identity(old, tools, app=True, from_version_code=from_version_code)
    require('Success' in run(prefix + ['install', old]), 'The original app was not installed')
    require(qa_apk.is_file() and not qa_apk.is_symlink(), 'Standalone upgrade QA APK is missing')
    require('Success' in run(prefix + ['install', '-t', qa_apk]), 'The standalone QA APK was not installed')
    seed = run(prefix + ['shell', 'am', 'instrument', '-w', '-r', '-e', 'from_version_code', str(from_version_code), '-e', 'mode', 'seed', QA_RUNNER], timeout=240)
    (output / 'upgrade-seed.txt').write_text(seed, encoding='utf-8', newline='\n')
    parse_probe(seed, 'seed', from_version_code, api_level)
    run(prefix + ['shell', 'am', 'force-stop', APP_ID])
    require('Success' in run(prefix + ['install', '-r', output / APK_NAME]), 'The existing app was not upgraded in place')
    run(prefix + ['shell', 'am', 'force-stop', APP_ID])
    verified = run(prefix + ['shell', 'am', 'instrument', '-w', '-r', '-e', 'from_version_code', str(from_version_code), '-e', 'mode', 'verify', QA_RUNNER], timeout=240)
    (output / 'upgrade-verify.txt').write_text(verified, encoding='utf-8', newline='\n')
    parse_probe(verified, 'verify', from_version_code, api_level)
    require('Success' in run(prefix + ['install', '-r', '-t', output / TEST_NAME]), 'The same-signer developer test package was not installed')
    transcript = run(prefix + ['shell', 'am', 'instrument', '-w', '-r', APP_ID + '.test/androidx.test.runner.AndroidJUnitRunner'], timeout=900)
    (output / 'instrumentation.txt').write_text(transcript, encoding='utf-8', newline='\n')
    counts = parse_instrumentation(transcript)
    require(counts == {'tests': 6, 'failures': 0, 'errors': 0, 'skipped': 0}, 'All six frozen instrumentation cases must pass without skips')
    run(prefix + ['root'])
    run(prefix + ['wait-for-device'])
    image = subprocess.run([str(p) for p in prefix + ['exec-out', 'cat', '/data/user/0/' + APP_ID + '/files/android-smoke.png']], capture_output=True, timeout=60)
    require(image.returncode == 0, 'Actual app screenshot could not be retrieved')
    valid_png(image.stdout)
    (output / 'android-smoke.png').write_bytes(image.stdout)
    return {'upgrade_preservation': {'passed': True, 'from_version_code': from_version_code, 'to_version_code': 3,
                                    'seed_probe_sha256': hashlib.sha256(seed.encode('utf-8')).hexdigest(),
                                    'verify_probe_sha256': hashlib.sha256(verified.encode('utf-8')).hexdigest()},
            'instrumentation': counts, 'instrument_sha256': hashlib.sha256(transcript.encode('utf-8')).hexdigest()}


def verify_source_snapshot(root: Path = ROOT) -> None:
    require(bool(re.fullmatch('[0-9a-f]{40}', SOURCE)) and SOURCE != '0' * 40, 'Frozen source commit has not been filled')
    run(['git', '-C', root, 'cat-file', '-e', SOURCE + '^{commit}'])
    source_paths = ['android', 'mobile/web', 'scripts/prepare_mobile_assets.py', 'scripts/prepare_public_release.py',
                    'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'assets/fonts/ark-pixel-OFL.txt']
    changed = run(['git', '-C', root, 'diff', '--name-only', SOURCE, 'HEAD', '--', *source_paths])
    require(not changed.strip(), 'Frozen production application sources changed during signing handoff')
    require(not run(['git', '-C', root, 'diff', '--name-only', 'HEAD', '--', *source_paths]).strip(), 'Frozen production sources have local modifications')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, default=ROOT / 'scripts/android-080rc2-signing-candidate.json')
    parser.add_argument('--sdk', type=Path, default=Path(os.environ.get('ANDROID_HOME', os.environ.get('ANDROID_SDK_ROOT', ''))))
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--api-level', type=int, choices=(28, 36))
    parser.add_argument('--from-version-code', type=int, choices=(1, 2))
    parser.add_argument('--qa-apk', type=Path, default=ROOT / 'android/upgrade-qa/app/build/outputs/apk/debug/app-debug.apk')
    args = parser.parse_args()
    stage = 'metadata'
    try:
        candidate = validate_candidate(json.loads(args.metadata.read_text('utf-8')))
        stage = 'source'
        verify_source_snapshot()
        output = ROOT / 'build/android080rc2'
        require(not output.is_symlink() and output.resolve().is_relative_to(ROOT), 'Invalid generated evidence directory')
        output.mkdir(parents=True, exist_ok=True)
        stage = 'download'
        fetch_candidate(candidate['apk'], output / APK_NAME)
        fetch_candidate(candidate['test_apk'], output / TEST_NAME)
        stage = 'signature_and_identity'
        tools = tools_for(args.sdk)
        identities = {'apk': checked_identity(output / APK_NAME, tools, app=True),
                      'test_apk': checked_identity(output / TEST_NAME, tools, app=False)}
        result = {'schema': 'love-house-android-080rc2-verification/v1', 'candidate': candidate,
                  'signature_and_metadata': 'passed', 'identities': identities, 'api_level': args.api_level,
                  'from_version_code': args.from_version_code}
        if args.run:
            require(not args.verify_only and args.api_level in (28, 36) and args.from_version_code in (1, 2), 'A single explicit emulator API and upgrade path are required')
            stage = 'upgrade_and_instrumentation'
            result.update(exercise(candidate, output, tools, args.api_level, args.qa_apk, args.from_version_code))
        (output / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps({'ok': True, 'stage': 'complete', 'instrumentation': result.get('instrumentation'),
                          'upgrade_preserved': result.get('upgrade_preservation', {}).get('passed', False)}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        error = {'ok': False, 'stage': stage, 'error_type': type(exc).__name__}
        if isinstance(exc, VerificationError):
            error['detail'] = str(exc)
        print(json.dumps(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
