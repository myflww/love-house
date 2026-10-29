#!/usr/bin/env python3
"""Verify public signed APK blobs and exercise those exact bytes on an emulator.

Private signing material is never read. The optional GitHub read token is used
only in an HTTPS request header to api.github.com and is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'love-house-android-candidate/v1'
APP_ID = 'io.github.myflww.lovehouse.preview'
MAX_APK_BYTES = 100 * 1024 * 1024
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')


class VerificationError(ValueError):
    """A controlled explanation that contains no external command/API text."""


def command_label(command: list[str | Path]) -> str:
    name = Path(command[0]).name.lower()
    names = {'git': 'git', 'git.exe': 'git', 'apksigner': 'apksigner', 'apksigner.bat': 'apksigner',
             'zipalign': 'zipalign', 'zipalign.exe': 'zipalign', 'aapt': 'aapt', 'aapt.exe': 'aapt',
             'adb': 'adb', 'adb.exe': 'adb'}
    tool = names.get(name, 'unknown-tool')
    operations = {'git': {'cat-file', 'diff', 'rev-parse'}, 'apksigner': {'verify'},
                  'zipalign': {'-c'}, 'aapt': {'dump'},
                  'adb': {'devices', 'shell', 'install', 'root', 'wait-for-device', 'exec-out'}}
    # Report only known constant command names, never a path, serial, APK name,
    # URL, token, full argument vector or command stdout/stderr.
    operation = next((str(item) for item in command[1:] if str(item) in operations.get(tool, set())), 'unknown-operation')
    return tool + ' ' + operation


def validate_manifest(value: dict) -> dict:
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        raise VerificationError('Unknown Android candidate metadata schema')
    if value.get('application_id') != APP_ID or not HEX40.fullmatch(str(value.get('source_commit', ''))):
        raise VerificationError('Invalid application identity or source commit')
    if value.get('version_name') != '0.1.0-preview1' or type(value.get('version_code')) is not int or value['version_code'] != 1:
        raise VerificationError('Unexpected Android preview version')
    if not HEX64.fullmatch(str(value.get('certificate_sha256', ''))):
        raise VerificationError('Invalid public signing certificate digest')
    for name in ('apk', 'test_apk'):
        entry = value.get(name)
        if not isinstance(entry, dict) or not HEX40.fullmatch(str(entry.get('blob_sha', ''))) or not HEX64.fullmatch(str(entry.get('sha256', ''))):
            raise VerificationError('Invalid public APK blob metadata')
        if type(entry.get('bytes')) is not int or not 0 < entry['bytes'] <= MAX_APK_BYTES:
            raise VerificationError('Invalid APK byte count')
    if value['apk']['blob_sha'] == value['test_apk']['blob_sha']:
        raise VerificationError('The application and test harness must be separate APKs')
    return value


def verify_bytes(content: bytes, entry: dict) -> None:
    if len(content) != entry['bytes'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
        raise VerificationError('APK size or SHA-256 differs from public metadata')
    git_blob = hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\0' + content).hexdigest()
    if git_blob != entry['blob_sha']:
        raise VerificationError('APK Git blob identity differs from public metadata')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VerificationError('Redirects are not allowed when fetching public APK blobs')


def fetch_blob(repository: str, entry: dict, destination: Path) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise VerificationError('Invalid GitHub repository identity')
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise VerificationError('APK output is not an ordinary generated file')
        content = destination.read_bytes()
        verify_bytes(content, entry)
        return
    headers = {'Accept': 'application/vnd.github.raw+json', 'X-GitHub-Api-Version': '2026-03-10',
               'User-Agent': 'LoveHouse-Android-Release-Verification'}
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com/repos/' + repository + '/git/blobs/' + entry['blob_sha'], headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=90) as response:
        content = response.read(entry['bytes'] + 1)
    verify_bytes(content, entry)
    destination.write_bytes(content)


def run(command: list[str | Path], *, timeout: int = 90) -> str:
    label = command_label(command)
    try:
        result = subprocess.run([str(part) for part in command], capture_output=True, encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationError('Android verification command could not complete: ' + label + ' (' + type(exc).__name__ + ')') from None
    if result.returncode:
        # Command output may contain environment paths; do not echo it on errors.
        raise VerificationError('Android verification command failed: ' + label + ' (exit ' + str(result.returncode) + ')')
    return result.stdout


def signer_digest(text: str) -> str:
    digests = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})\s*$', text, re.M)
    if len(digests) != 1:
        raise VerificationError('Expected exactly one APK signing certificate')
    return digests[0].lower()


def badging_identity(text: str) -> dict:
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'", text, re.M)
    if not package:
        raise VerificationError('Android APK package identity is missing')
    return {'package': package[1], 'version_code': package[2], 'version_name': package[3],
            'min_sdk': re.findall(r"^sdkVersion:'(\d+)'", text, re.M),
            'target_sdk': re.findall(r"^targetSdkVersion:'(\d+)'", text, re.M)}


def instrumentation_identity(xmltree: str) -> tuple[str, str]:
    blocks = re.findall(r'^\s*E: instrumentation\b[^\n]*\n((?:\s+A: [^\n]*\n?)+)', xmltree, re.M)
    if len(blocks) != 1:
        raise VerificationError('Expected exactly one Android instrumentation runner')
    names = re.findall(r'android:name\([^)]*\)="([^"]+)"', blocks[0])
    targets = re.findall(r'android:targetPackage\([^)]*\)="([^"]+)"', blocks[0])
    if names != ['androidx.test.runner.AndroidJUnitRunner'] or targets != [APP_ID]:
        raise VerificationError('Test runner or targetPackage differs from the release app')
    return names[0], targets[0]


def verify_apks(value: dict, output: Path, sdk: Path) -> dict:
    tools = sdk / 'build-tools/36.0.0'
    signer = tools / ('apksigner.bat' if os.name == 'nt' else 'apksigner')
    aapt = tools / ('aapt.exe' if os.name == 'nt' else 'aapt')
    zipalign = tools / ('zipalign.exe' if os.name == 'nt' else 'zipalign')
    identities = {}
    for name, filename in (('apk', 'LoveHouse-0.1.0-preview1-Android.apk'), ('test_apk', 'LoveHouse-Android-instrumentation-test.apk')):
        apk = output / filename
        verify_bytes(apk.read_bytes(), value[name])
        digest = signer_digest(run([signer, 'verify', '--verbose', '--print-certs', apk]))
        if digest != value['certificate_sha256']:
            raise VerificationError('APK signer differs from the public certificate fingerprint')
        run([zipalign, '-c', '-P', '16', '4', apk])
        badging = run([aapt, 'dump', 'badging', apk])
        identity = badging_identity(badging)
        xmltree = run([aapt, 'dump', 'xmltree', apk, 'AndroidManifest.xml'])
        if name == 'apk':
            if identity != {'package': APP_ID, 'version_code': str(value['version_code']), 'version_name': value['version_name'], 'min_sdk': ['26'], 'target_sdk': ['36']}:
                raise VerificationError('Release APK identity or supported SDK versions differ from metadata')
            if 'application-debuggable' in badging or re.search(r'android:(?:debuggable|testOnly)\([^)]*\)=\(type 0x12\)0xffffffff', xmltree):
                raise VerificationError('The public candidate must be a release APK')
            if re.search(r'^uses-permission', badging, re.M):
                raise VerificationError('The offline APK unexpectedly requests device permissions')
            with zipfile.ZipFile(apk) as archive:
                names = archive.namelist()
                if 'assets/web/index.html' not in names or any(re.fullmatch(r'lib/[^/]+/[^/]+\.so', item) for item in names):
                    raise VerificationError('Release APK lacks local assets or contains an unexpected native library')
        else:
            if identity['package'] != APP_ID + '.test':
                raise VerificationError('Unexpected Android test package identity')
            identity['runner'], identity['target_package'] = instrumentation_identity(xmltree)
        identities[name] = identity
    return identities


def parse_instrumentation(text: str) -> dict:
    started: set[tuple[str, str]] = set()
    passed: set[tuple[str, str]] = set()
    status: dict[str, str] = {}
    declared: set[int] = set()
    for line in text.splitlines():
        if line.startswith('INSTRUMENTATION_STATUS: '):
            key, separator, value = line[len('INSTRUMENTATION_STATUS: '):].partition('=')
            if separator:
                status[key] = value
        elif line.startswith('INSTRUMENTATION_STATUS_CODE: '):
            code = int(line.split(': ', 1)[1])
            identity = (status.get('class', ''), status.get('test', ''))
            if not all(identity) or code not in (0, 1):
                raise VerificationError('Instrumentation has a failed, ignored or incomplete test')
            if 'numtests' in status:
                declared.add(int(status['numtests']))
            if code == 1:
                if identity in started:
                    raise VerificationError('Instrumentation test started more than once')
                started.add(identity)
            else:
                if identity not in started or identity in passed:
                    raise VerificationError('Instrumentation did not report a matching test start')
                passed.add(identity)
            status = {}
    summaries = re.findall(r'^OK \((\d+) tests?\)\s*$', text, re.M)
    final_codes = re.findall(r'^INSTRUMENTATION_CODE: (-?\d+)\s*$', text, re.M)
    if (not passed or passed != started or summaries != [str(len(passed))] or final_codes != ['-1']
            or declared != {len(passed)} or re.search(r'INSTRUMENTATION_FAILED|FAILURES!!!|shortMsg=|Process crashed', text)):
        raise VerificationError('Instrumentation did not produce complete successful test evidence')
    return {'tests': len(passed), 'failures': 0, 'errors': 0, 'skipped': 0}


def exercise(value: dict, identities: dict, output: Path, sdk: Path, api_level: int) -> dict:
    adb = sdk / 'platform-tools' / ('adb.exe' if os.name == 'nt' else 'adb')
    devices = [line.split()[0] for line in run([adb, 'devices']).splitlines()
               if re.fullmatch(r'emulator-\d+\s+device', line)]
    if len(devices) != 1:
        raise VerificationError('Exactly one disposable Android emulator is required')
    prefix = [adb, '-s', devices[0]]
    if run(prefix + ['shell', 'getprop', 'ro.kernel.qemu']).strip() != '1':
        raise VerificationError('Release tests require a disposable emulator')
    if run(prefix + ['shell', 'getprop', 'ro.build.version.sdk']).strip() != str(api_level):
        raise VerificationError('Android emulator API differs from the requested test version')
    for filename, test in (('LoveHouse-0.1.0-preview1-Android.apk', False), ('LoveHouse-Android-instrumentation-test.apk', True)):
        installed = run(prefix + ['install', '-r'] + (['-t'] if test else []) + [output / filename], timeout=180)
        if 'Success' not in installed:
            raise VerificationError('Signed Android APK was not installed successfully')
    target = identities['test_apk']['package'] + '/' + identities['test_apk']['runner']
    instrument = run(prefix + ['shell', 'am', 'instrument', '-w', '-r', target], timeout=900)
    (output / 'instrumentation.txt').write_text(instrument, encoding='utf-8', newline='\n')
    counts = parse_instrumentation(instrument)
    # A root-capable Google APIs emulator can copy the screenshot saved by the
    # test inside the non-debuggable release application's private files.
    run(prefix + ['root'])
    run(prefix + ['wait-for-device'])
    image = subprocess.run([str(part) for part in prefix + ['exec-out', 'cat', '/data/user/0/' + APP_ID + '/files/android-smoke.png']], capture_output=True, timeout=30)
    if image.returncode or not image.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise VerificationError('Release instrumentation screenshot evidence is missing')
    (output / 'android-smoke.png').write_bytes(image.stdout)
    return {'api_level': api_level, 'installed_release_sha256': value['apk']['sha256'], **counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'android/release-candidate.json')
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', 'myflww/love-house'))
    parser.add_argument('--sdk', type=Path, default=Path(os.environ.get('ANDROID_HOME', os.environ.get('ANDROID_SDK_ROOT', ''))))
    parser.add_argument('--run-instrumentation', action='store_true')
    parser.add_argument('--api-level', type=int, choices=(28, 36))
    args = parser.parse_args()
    stage = 'metadata'
    try:
        if args.manifest.is_symlink() or args.manifest.resolve() != (ROOT / 'android/release-candidate.json').resolve():
            raise VerificationError('Only the reviewed public candidate metadata path is accepted')
        value = validate_manifest(json.loads(args.manifest.read_text(encoding='utf-8')))
        stage = 'source'
        run(['git', '-C', ROOT, 'cat-file', '-e', value['source_commit'] + '^{commit}'])
        changed = run(['git', '-C', ROOT, 'diff', '--name-only', value['source_commit'], 'HEAD', '--',
                       'android/app', 'android/settings.gradle', 'android/build.gradle', 'android/gradle.properties',
                       'mobile/web', 'scripts/prepare_mobile_assets.py', 'scripts/prepare_public_release.py'])
        if changed.strip():
            raise VerificationError('Candidate source differs from the checked-out Android implementation')
        output = ROOT / 'build/android-release'
        if output.is_symlink() or not output.resolve().is_relative_to(ROOT):
            raise VerificationError('Invalid generated release evidence directory')
        output.mkdir(parents=True, exist_ok=True)
        for name, filename in (('apk', 'LoveHouse-0.1.0-preview1-Android.apk'), ('test_apk', 'LoveHouse-Android-instrumentation-test.apk')):
            stage = 'download_apk' if name == 'apk' else 'download_test_apk'
            fetch_blob(args.repository, value[name], output / filename)
        stage = 'verify_apks'
        identities = verify_apks(value, output, args.sdk)
        result = {'schema': 'love-house-android-release-verification/v1', 'source_commit': value['source_commit'],
                  'certificate_sha256': value['certificate_sha256'], 'apk': value['apk'], 'test_apk': value['test_apk'],
                  'identities': identities, 'signature_and_metadata': 'passed'}
        if args.run_instrumentation:
            stage = 'instrumentation'
            if not args.api_level:
                raise VerificationError('An emulator API level is required')
            result['instrumentation'] = exercise(value, identities, output, args.sdk, args.api_level)
        (output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
        print(json.dumps({'ok': True, 'signature_and_metadata': 'passed', 'instrumentation': result.get('instrumentation', 'not_run')}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        # Do not print tokens, HTTP headers, raw downloads or arbitrary stderr.
        error = {'ok': False, 'error': 'Signed Android release verification did not pass',
                 'stage': stage, 'exception': type(exc).__name__}
        # Only our controlled errors are printable. Built-in ValueError (for
        # example int parsing), HTTP errors and OS exceptions may echo input.
        if isinstance(exc, VerificationError):
            error['detail'] = str(exc)
        print(json.dumps(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
