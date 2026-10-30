#!/usr/bin/env python3
"""Append the verified original-key Android upgrade to the existing 0.8 preview.

This program never creates a release/tag, deletes an asset, replaces an asset,
reads a signing key or publishes the developer instrumentation APK.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import verify_signed_080 as verify

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'myflww/love-house'
TAG = 'v0.8.0rc1'
RELEASE_ID = 429144697
TARGET = 'd4130f8aec3882a30a7d237a5d29122509a2dc0d'
APK_NAME = 'LoveHouse-0.8.0rc1-Android.apk'
EVIDENCE_NAME = 'Android-Signed-080rc1-verification.json'
CHECKSUMS_NAME = 'Android-Signed-080rc1-SHA256SUMS.txt'
BRANCH = 'refs/heads/codex/android-080rc1-original-signing'
API_BASE = '/repos/' + REPOSITORY + '/releases/' + str(RELEASE_ID)
ORIGINAL_ASSETS = {
    'FINAL-PROVENANCE.json': (692422942, 2916, '17785de83485fa7cb2c916a88c2f2160846298318d48b49380373aabf6a498db'),
    'LoveHouse-0.8.0rc1-Original-Key-Portable-382c5ee.zip': (692422972, 4708467, '321f26138739efe006ac40ac921fcb9768dcfc6c6657ce3f891a5edddb9b7051'),
    'LoveHouse-0.8.0rc1-Windows-x64.zip': (692423020, 265123708, '97e35675311edb4db6d51833663155213c97beb224a09c8e0c1f235901c17342'),
    'LoveHouse-Setup-0.8.0rc1-Windows-x64.exe': (692422618, 255123516, '313ad4c15da5dd70b79d2da682f7a8c02c8c130cebb72a806dbeaef1e320819b'),
    'Preview-SHA256SUMS.txt': (692423476, 604, '67ba7349d334a3af0a76d2bb0ab4336c4c95d891249e0805eb0605333852048d'),
    'WINDOWS-MOBILE-080RC1.md': (692422535, 4872, '224e69ae547357f47f23b0ee6deb467fc25282697178ce302905c37e80b329ad'),
    'Windows-SHA256SUMS.txt': (692422576, 210, '60ba1d458817489da189ecb2e487091bd05b11157cf00e9a51a2fcc4f9e1bb12'),
    'Windows-test-evidence-382c5ee.zip': (692422490, 4371, '2c7ca808de1f23a314782cbbf5dc2475652bdaf276eea330c52c184f44225212'),
}


def ordinary_bytes(path: Path, maximum: int = 100 * 1024 * 1024) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('Expected an ordinary bounded verification artifact')
    return path.read_bytes()


def checked_evidence(candidate: dict, report: dict, api: int, transcript: str,
                     seed: str, restored: str) -> dict:
    if (not isinstance(report, dict) or report.get('schema') != 'love-house-android-080-verification/v1'
            or report.get('candidate') != candidate or report.get('api_level') != api
            or report.get('signature_and_metadata') != 'passed'):
        raise ValueError('Signed candidate verification identity is inconsistent')
    identities = report.get('identities')
    if not isinstance(identities, dict):
        raise ValueError('Verified application identities are missing')
    identity = identities.get('apk')
    expected = {'package': verify.APP_ID, 'version_code': '2', 'version_name': '0.8.0rc1',
                'min_sdk': ['26'], 'target_sdk': ['36']}
    if identity != expected:
        raise ValueError('Verified Android application identity is unexpected')
    harness = identities.get('test_apk', {})
    if (not isinstance(harness, dict) or harness.get('package') != verify.APP_ID + '.test'
            or harness.get('runner') != 'androidx.test.runner.AndroidJUnitRunner'
            or harness.get('target_package') != verify.APP_ID):
        raise ValueError('Instrumentation does not target the signed application')
    counts = verify.parse_instrumentation(transcript)
    if (counts != {'tests': 6, 'failures': 0, 'errors': 0, 'skipped': 0} or report.get('instrumentation') != counts
            or any(type(report['instrumentation'].get(key)) is not int for key in counts)):
        raise ValueError('All six instrumentation tests must pass without skips')
    if report.get('instrument_sha256') != hashlib.sha256(transcript.encode('utf-8')).hexdigest():
        raise ValueError('Instrumentation transcript differs from its verification record')
    if verify.parse_probe(seed, 'seed')['api_level'] != api or verify.parse_probe(restored, 'verify')['api_level'] != api:
        raise ValueError('Upgrade probe was run on another Android API')
    upgrade = report.get('upgrade_preservation', {})
    if (not isinstance(upgrade, dict) or upgrade.get('passed') is not True or type(upgrade.get('from_version_code')) is not int
            or upgrade.get('from_version_code') != 1 or type(upgrade.get('to_version_code')) is not int or upgrade.get('to_version_code') != 2
            or upgrade.get('seed_probe_sha256') != hashlib.sha256(seed.encode('utf-8')).hexdigest()
            or upgrade.get('verify_probe_sha256') != hashlib.sha256(restored.encode('utf-8')).hexdigest()):
        raise ValueError('Old-app memory preservation has not been demonstrated')
    return {'api_level': api, 'signature_and_metadata': 'passed', 'application_identity': identity,
            'instrumentation': counts, 'instrumentation_sha256': report['instrument_sha256'],
            'upgrade_preservation': {key: upgrade[key] for key in
                ('passed', 'from_version_code', 'to_version_code', 'seed_probe_sha256', 'verify_probe_sha256')}}


def collect_assets(root: Path, candidate: dict, artifacts: Path) -> dict[str, bytes]:
    verify.validate_candidate(candidate)
    if artifacts.is_symlink() or not artifacts.resolve().is_relative_to(root.resolve()):
        raise ValueError('Verification artifacts must stay within the owned build directory')
    accepted = None
    reports = {}
    for api in (28, 36):
        directory = artifacts / ('api-' + str(api))
        if directory.is_symlink() or not directory.resolve().is_relative_to(artifacts.resolve()):
            raise ValueError('Invalid verification artifact directory')
        raw = ordinary_bytes(directory / APK_NAME)
        digest = hashlib.sha256(raw).hexdigest()
        expected = candidate['apk']
        if len(raw) != expected['bytes'] or digest != expected['sha256']:
            raise ValueError('The publishable APK differs from the signed candidate')
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if blob != expected['blob_sha'] or (accepted is not None and raw != accepted):
            raise ValueError('Emulator jobs did not accept the same exact APK')
        accepted = raw
        report = json.loads(ordinary_bytes(directory / 'verification.json', 1024 * 1024).decode('utf-8'))
        transcripts = [ordinary_bytes(directory / name, 4 * 1024 * 1024).decode('utf-8') for name in
                       ('instrumentation.txt', 'upgrade-seed.txt', 'upgrade-verify.txt')]
        result = checked_evidence(candidate, report, api, *transcripts)
        screenshot = ordinary_bytes(directory / 'android-smoke.png', 20 * 1024 * 1024)
        verify.valid_png(screenshot)
        result['screenshot_sha256'] = hashlib.sha256(screenshot).hexdigest()
        reports[str(api)] = result
    # Only these reviewed public fields enter the public evidence asset. Raw
    # memory text, arbitrary artifact metadata and developer APKs are excluded.
    public = {'schema': 'love-house-android-080-public-signing/v1', 'tag': TAG,
              'application_id': verify.APP_ID, 'version_name': '0.8.0rc1', 'version_code': 2,
              'source_commit': candidate['source_commit'], 'certificate_sha256': verify.CERT,
              'signed_apk': dict(candidate['apk']), 'emulators': reports,
              'physical_android_phone_tested': False,
              'old_release_assets_unchanged': {name: {'id': item[0], 'bytes': item[1], 'sha256': item[2]}
                                               for name, item in ORIGINAL_ASSETS.items()}}
    assets = {APK_NAME: accepted,
              EVIDENCE_NAME: (json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')}
    assets[CHECKSUMS_NAME] = ''.join(hashlib.sha256(content).hexdigest() + '  ' + name + '\n'
                                   for name, content in sorted(assets.items())).encode('ascii')
    return assets


def rewritten_body(body: str, run_url: str, apk_hash: str) -> str:
    if not re.fullmatch(r'https://github\.com/myflww/love-house/actions/runs/[0-9]+', run_url):
        raise ValueError('The release evidence URL is not a repository workflow run')
    if not re.fullmatch(r'[0-9a-f]{64}', apk_hash):
        raise ValueError('Invalid signed APK SHA-256')
    download = ('- Android：下载 `LoveHouse-0.8.0rc1-Android.apk`（已使用原发行密钥签名，可覆盖升级旧版）。'
                '请使用 `Android-Signed-080rc1-SHA256SUMS.txt` 核对本 APK；保留已有记忆和备份。'
                '原开发签名交接 ZIP 仅供追溯，不是普通用户安装包。')
    section = ('## Android 原密钥签名与覆盖升级验收\n\n'
               'Android APK 已使用原发行密钥签名，包名仍为 `io.github.myflww.lovehouse.preview`，'
               'versionName `0.8.0rc1`、versionCode `2`。原证书 SHA-256 为 '
               '`' + verify.CERT + '`；签名私钥和密码未上传。\n\n'
               '同一最终签名文件已在 Android 9（API28）和 Android 16（API36）模拟器安装、'
               '运行全部 6 项 instrumentation 测试且无跳过；从旧版 `0.1.0-preview1` 直接覆盖安装，'
               '并通过界面确认升级前保存的合成原文、回复和标签仍可读取，没有先卸载旧 App。'
               '这不是实体手机验收，仍属于预览版。\n\n'
               '最终 APK SHA-256：`' + apk_hash + '`。'
               '[原签名与覆盖升级验收工作流](' + run_url + ')；'
               '两个模拟器的记录在本页 `Android-Signed-080rc1-verification.json`。'
               '开发 test APK 不作为用户安装包发布，已有 Windows、macOS 和历史附件保持不变。\n\n')
    old_heading = '## 给原 Android 签名电脑的接手任务\n'
    new_heading = '## Android 原密钥签名与覆盖升级验收\n'
    following = '## 已验证的范围'
    heading = new_heading if new_heading in body else old_heading
    if body.count(heading) != 1 or body.count(following) != 1:
        raise ValueError('Existing release text does not have the reviewed Android section')
    start = body.index(heading)
    end = body.index(following, start)
    lines = body[:start].splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith('- Android：')]
    if len(matches) != 1:
        raise ValueError('Expected exactly one Android download line')
    lines[matches[0]] = download + '\n'
    prefix = ''.join(lines).replace('移动端入口和 Android 原密钥签名交接。',
                                   '移动端入口和已用原发行密钥签名的 Android APK。', 1)
    return prefix + section + body[end:]


def asset_map(entries: list[dict]) -> dict[str, dict]:
    by_name = {item['name']: item for item in entries}
    if len(by_name) != len(entries):
        raise ValueError('Release assets contain duplicate names')
    allowed = set(ORIGINAL_ASSETS) | {APK_NAME, EVIDENCE_NAME, CHECKSUMS_NAME}
    if set(by_name) - allowed:
        raise ValueError('Existing release assets differ from the reviewed append-only set')
    for name, (asset_id, size, digest) in ORIGINAL_ASSETS.items():
        item = by_name.get(name, {})
        if (item.get('id') != asset_id or item.get('size') != size or item.get('state') != 'uploaded'
                or item.get('digest') != 'sha256:' + digest):
            raise ValueError('An original release asset has changed; publication stopped')
    return by_name


def checked_release(value: dict) -> None:
    if (value.get('id') != RELEASE_ID or value.get('tag_name') != TAG or value.get('draft')
            or value.get('prerelease') is not True or value.get('target_commitish') != TARGET):
        raise ValueError('Existing release identity differs from the intended preview')


class AssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if (req.get_method() != 'GET' or parsed.scheme != 'https' or parsed.username or parsed.password
                or parsed.hostname not in {'release-assets.githubusercontent.com', 'github-releases.githubusercontent.com'}):
            raise ValueError('Unexpected release-asset redirect')
        # Bearer tokens are never forwarded to the signed storage URL.
        return urllib.request.Request(newurl, headers={'User-Agent': 'LoveHouse-Signed-Android-080'})


class GitHub:
    def __init__(self, token: str):
        if not token:
            raise ValueError('Repository publication token is unavailable')
        self.token = token
        self.opener = urllib.request.build_opener(AssetRedirect())

    def request(self, method: str, path: str, *, payload=None, content=None,
                upload: bool = False, binary: bool = False, expected_bytes: int = 0):
        if not path.startswith('/repos/' + REPOSITORY + '/releases/'):
            raise ValueError('Publisher request is outside the fixed release API')
        if method not in {'GET', 'POST', 'PATCH'}:
            raise ValueError('Release deletion or replacement is not supported')
        headers = {'Authorization': 'Bearer ' + self.token, 'X-GitHub-Api-Version': '2026-03-10',
                   'User-Agent': 'LoveHouse-Signed-Android-080',
                   'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json'}
        if payload is not None:
            content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json; charset=utf-8'
        elif content is not None:
            headers['Content-Type'] = 'application/octet-stream'
        origin = 'https://uploads.github.com' if upload else 'https://api.github.com'
        request = urllib.request.Request(origin + path, headers=headers, data=content, method=method)
        try:
            with self.opener.open(request, timeout=120) as response:
                result = response.read(expected_bytes + 1 if binary else 2 * 1024 * 1024)
        except urllib.error.HTTPError:
            raise ValueError('GitHub rejected the append-only publication request') from None
        if binary:
            if len(result) != expected_bytes:
                raise ValueError('Release asset byte count differs from the verified artifact')
            return result
        return json.loads(result.decode('utf-8'))


def publish(client: GitHub, assets: dict[str, bytes], run_url: str) -> dict:
    if set(assets) != {APK_NAME, EVIDENCE_NAME, CHECKSUMS_NAME}:
        raise ValueError('Only the three reviewed public Android files may be appended')
    release = client.request('GET', API_BASE)
    checked_release(release)
    new_body = rewritten_body(release['body'], run_url, hashlib.sha256(assets[APK_NAME]).hexdigest())
    existing = asset_map(client.request('GET', API_BASE + '/assets?per_page=100'))
    # Validate all pre-existing new-name collisions before any upload occurs.
    for name, content in assets.items():
        if name in existing:
            item = existing[name]
            if item.get('size') != len(content) or item.get('state') != 'uploaded' or type(item.get('id')) is not int:
                raise ValueError('A new Android asset name conflicts with a different existing file')
            actual = client.request('GET', '/repos/' + REPOSITORY + '/releases/assets/' + str(item['id']),
                                    binary=True, expected_bytes=len(content))
            if actual != content:
                raise ValueError('A new Android asset has different bytes and will not be overwritten')
    for name, content in sorted(assets.items()):
        if name in existing:
            continue
        item = client.request('POST', API_BASE + '/assets?name=' + urllib.parse.quote(name, safe=''),
                              content=content, upload=True)
        if (item.get('name') != name or item.get('size') != len(content) or item.get('state') != 'uploaded'
                or type(item.get('id')) is not int):
            raise ValueError('New release asset metadata is inconsistent')
        actual = client.request('GET', '/repos/' + REPOSITORY + '/releases/assets/' + str(item['id']),
                                binary=True, expected_bytes=len(content))
        if actual != content:
            raise ValueError('Uploaded Android asset does not match the verified bytes')
    final_assets = asset_map(client.request('GET', API_BASE + '/assets?per_page=100'))
    if set(final_assets) != set(ORIGINAL_ASSETS) | set(assets):
        raise ValueError('The complete expected append-only asset set is missing')
    # Re-read the body before PATCH to avoid silently replacing edits made while
    # uploading. This remains an append operation to an already public preview.
    latest = client.request('GET', API_BASE)
    checked_release(latest)
    if latest['body'] != release['body']:
        raise ValueError('Release text changed during upload; no body edit was applied')
    if new_body != release['body']:
        final_release = client.request('PATCH', API_BASE, payload={'body': new_body})
        checked_release(final_release)
        if final_release.get('body') != new_body:
            raise ValueError('The Android release-note update did not complete')
    asset_map(client.request('GET', API_BASE + '/assets?per_page=100'))
    return {'ok': True, 'release_url': 'https://github.com/' + REPOSITORY + '/releases/tag/' + TAG,
            'apk_sha256': hashlib.sha256(assets[APK_NAME]).hexdigest(), 'appended_assets': sorted(assets),
            'original_assets_preserved': len(ORIGINAL_ASSETS)}


def main() -> int:
    try:
        if (os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or os.environ.get('GITHUB_REF') != BRANCH
                or os.environ.get('GITHUB_EVENT_NAME') not in {'push', 'workflow_dispatch'}):
            raise ValueError('Publication is restricted to the reviewed signing workflow branch')
        candidate = verify.validate_candidate(json.loads(ordinary_bytes(ROOT / 'scripts/android-080-signing-candidate.json', 16384)))
        assets = collect_assets(ROOT, candidate, ROOT / 'build/android080-artifacts')
        run_id = os.environ.get('GITHUB_RUN_ID', '')
        if not run_id.isdigit():
            raise ValueError('Workflow evidence identity is unavailable')
        run_url = 'https://github.com/' + REPOSITORY + '/actions/runs/' + run_id
        print(json.dumps(publish(GitHub(os.environ.get('GITHUB_TOKEN', '')), assets, run_url), ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': 'Signed Android append-only publication did not complete',
                          'exception': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
