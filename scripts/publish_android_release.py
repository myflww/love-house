#!/usr/bin/env python3
"""Publish only the exact signed Android candidate accepted on both emulators.

The fixed Android preview tag is independent of desktop releases. Assets are
never deleted or overwritten, and signing keys are never read or uploaded.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import verify_android_release as verify

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'myflww/love-house'
TAG = 'android-v0.1.0-preview1'
TITLE = '爱之屋 0.1.0 手机版预览'
APK_NAME = 'LoveHouse-0.1.0-preview1-Android.apk'
EVIDENCE_NAME = 'Android-0.1.0-preview1-verification.json'
LICENSE_NAME = 'LoveHouse-0.1.0-preview1-Licenses.zip'
BODY = '''爱之屋手机版独立离线预览。

**安卓下载：** 下载本页的 `LoveHouse-0.1.0-preview1-Android.apk`，支持 Android 8.0 及以上。APK 已使用持久私钥签名；同一文件已在 Android 9 / Android 16 模拟器完成安装和至少 5 项真实仪器测试，未跳过测试。尚未完成真实安卓手机测试，预览版可能仍存在机型差异；请保留导出备份。

**iPhone：** 使用 Safari 打开 [爱之屋手机版](https://love-house-mobile-myflww.sharp-rice-0090.chatgpt.site)，选择分享 → 添加到主屏幕。它是 PWA 网页应用，没有 IPA 安装包；尚未完成 iPhone 真机测试。

当前功能包括手动记录、检索、多记忆库、JSON 导入导出、Markdown 导出和标签关系图。记忆保存在当前设备；本版没有 Agent 自动采集或模型整理功能。

本页只发布安卓手机版预览，Mac 与 Windows 下载请使用各自已有的桌面版本。许可原文、SHA-256 校验和以及两个 Android 模拟器的验收记录随下载提供。
'''


def ordinary_bytes(path: Path, *, maximum: int = verify.MAX_APK_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('Expected an ordinary, bounded candidate artifact')
    return path.read_bytes()


def checked_evidence(candidate: dict, evidence: dict, api_level: int, transcript: str) -> dict:
    if not isinstance(evidence, dict) or evidence.get('schema') != 'love-house-android-release-verification/v1' or evidence.get('signature_and_metadata') != 'passed':
        raise ValueError('Signed candidate verification evidence is missing')
    for name in ('source_commit', 'certificate_sha256', 'apk', 'test_apk'):
        if evidence.get(name) != candidate[name]:
            raise ValueError('Candidate metadata differs between emulator jobs')
    identities = evidence.get('identities')
    if not isinstance(identities, dict):
        raise ValueError('Application verification identities are missing')
    identity = identities.get('apk')
    if identity != {'package': verify.APP_ID, 'version_code': '1', 'version_name': '0.1.0-preview1', 'min_sdk': ['26'], 'target_sdk': ['36']}:
        raise ValueError('Verified release application identity is unexpected')
    harness = identities.get('test_apk', {})
    if (not isinstance(harness, dict) or harness.get('package') != verify.APP_ID + '.test' or harness.get('runner') != 'androidx.test.runner.AndroidJUnitRunner'
            or harness.get('target_package') != verify.APP_ID):
        raise ValueError('Verified test harness does not target the release application')
    counts = verify.parse_instrumentation(transcript)
    result = evidence.get('instrumentation', {})
    if not isinstance(result, dict) or type(result.get('api_level')) is not int or result['api_level'] != api_level:
        raise ValueError('Unexpected emulator API in release verification')
    if result.get('installed_release_sha256') != candidate['apk']['sha256']:
        raise ValueError('Emulator did not install the APK being published')
    for name in ('tests', 'failures', 'errors', 'skipped'):
        if type(result.get(name)) is not int or result[name] != counts[name]:
            raise ValueError('Test counters differ from actual instrumentation output')
    if counts['tests'] < 5 or any(counts[name] for name in ('failures', 'errors', 'skipped')):
        raise ValueError('Each emulator must complete at least five tests without skips')
    return evidence


def licence_archive(root: Path) -> bytes:
    names = ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'android/LICENSE.androidx-Apache-2.0.txt',
             'android/THIRD_PARTY_NOTICES.md', 'assets/fonts/ark-pixel-OFL.txt')
    data = io.BytesIO()
    # Stored entries and fixed metadata make identical retries byte-for-byte
    # stable across hosts; upstream notice bytes are never reformatted.
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name in names:
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            archive.writestr(item, ordinary_bytes(root / name, maximum=1024 * 1024))
    return data.getvalue()


def collect_assets(root: Path, candidate: dict, artifacts: Path) -> dict[str, bytes]:
    if artifacts.is_symlink() or not artifacts.resolve().is_relative_to(root.resolve()):
        raise ValueError('Candidate artifacts must remain inside this project build directory')
    apk_bytes = None
    evidence = {}
    for api_level in (28, 36):
        directory = artifacts / ('api-' + str(api_level))
        if directory.is_symlink() or not directory.resolve().is_relative_to(artifacts.resolve()):
            raise ValueError('Invalid candidate artifact directory')
        content = ordinary_bytes(directory / APK_NAME)
        verify.verify_bytes(content, candidate['apk'])
        if apk_bytes is not None and content != apk_bytes:
            raise ValueError('The emulator jobs accepted different APK bytes')
        apk_bytes = content
        report = json.loads(ordinary_bytes(directory / 'verification.json', maximum=1024 * 1024).decode('utf-8'))
        transcript = ordinary_bytes(directory / 'instrumentation.txt', maximum=4 * 1024 * 1024).decode('utf-8')
        report = checked_evidence(candidate, report, api_level, transcript)
        screenshot = ordinary_bytes(directory / 'android-smoke.png', maximum=20 * 1024 * 1024)
        if not screenshot.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Emulator screenshot evidence is missing')
        # Publish only reviewed fields, never arbitrary artifact metadata/text.
        evidence[str(api_level)] = {'signature_and_metadata': 'passed',
                                   'application_identity': report['identities']['apk'],
                                   'test_runner': report['identities']['test_apk']['runner'],
                                   'instrumentation': {key: report['instrumentation'][key] for key in
                                                       ('api_level', 'installed_release_sha256', 'tests', 'failures', 'errors', 'skipped')},
                                   'instrumentation_sha256': hashlib.sha256(transcript.encode('utf-8')).hexdigest(),
                                   'screenshot_sha256': hashlib.sha256(screenshot).hexdigest()}
    public_evidence = {'schema': 'love-house-android-public-release/v1', 'tag': TAG,
                       'application_id': candidate['application_id'], 'version_name': candidate['version_name'],
                       'version_code': candidate['version_code'], 'source_commit': candidate['source_commit'],
                       'certificate_sha256': candidate['certificate_sha256'], 'apk': candidate['apk'], 'emulators': evidence,
                       'physical_android_phone_tested': False, 'physical_iphone_tested': False}
    assets = {APK_NAME: apk_bytes, EVIDENCE_NAME: (json.dumps(public_evidence, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8'),
              LICENSE_NAME: licence_archive(root)}
    assets['SHA256SUMS.txt'] = ''.join(hashlib.sha256(content).hexdigest() + '  ' + name + '\n'
                                     for name, content in sorted(assets.items())).encode('ascii')
    return assets


class AssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if req.get_method() != 'GET' or parsed.scheme != 'https' or parsed.hostname not in {'release-assets.githubusercontent.com', 'github-releases.githubusercontent.com'}:
            raise ValueError('Unexpected GitHub release download redirect')
        # A signed storage URL needs no bearer token. Never forward it outside
        # the GitHub API/Uploads origin.
        return urllib.request.Request(newurl, headers={'User-Agent': 'LoveHouse-Android-Preview-Publisher'})


class GitHub:
    def __init__(self, token: str):
        if not token:
            raise ValueError('A GitHub repository token is required in the environment')
        self.token = token
        self.opener = urllib.request.build_opener(AssetRedirect())

    def request(self, method: str, path: str, *, payload=None, content: bytes | None = None,
                upload: bool = False, binary: bool = False, expected_bytes: int = 0, allow_missing: bool = False):
        origin = 'https://uploads.github.com' if upload else 'https://api.github.com'
        if not path.startswith('/repos/' + REPOSITORY + '/'):
            raise ValueError('The publisher is restricted to the Love House repository')
        headers = {'Authorization': 'Bearer ' + self.token, 'X-GitHub-Api-Version': '2026-03-10',
                   'User-Agent': 'LoveHouse-Android-Preview-Publisher',
                   'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json'}
        if payload is not None:
            content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json; charset=utf-8'
        elif content is not None:
            headers['Content-Type'] = 'application/octet-stream'
        request = urllib.request.Request(origin + path, data=content, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=120) as response:
                limit = expected_bytes + 1 if binary else 2 * 1024 * 1024
                result = response.read(limit)
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code == 404:
                return None
            raise ValueError('GitHub did not accept the Android preview operation') from None
        if binary:
            if len(result) != expected_bytes:
                raise ValueError('Existing release asset size differs from the verified candidate')
            return result
        return json.loads(result.decode('utf-8'))

    def find_release(self):
        value = self.request('GET', '/repos/' + REPOSITORY + '/releases/tags/' + TAG, allow_missing=True)
        if value is not None:
            return value
        # Draft tags might not yet have a Git ref. Locate an interrupted upload
        # before considering creation, so a retry never duplicates that draft.
        found = []
        for page in range(1, 6):
            releases = self.request('GET', '/repos/' + REPOSITORY + '/releases?per_page=100&page=' + str(page))
            found.extend(item for item in releases if item.get('tag_name') == TAG)
            if len(releases) < 100:
                break
        else:
            raise ValueError('Release listing was not exhausted; a draft will not be duplicated')
        if len(found) > 1:
            raise ValueError('More than one Android preview draft exists')
        return found[0] if found else None

    def tag_commit(self):
        value = self.request('GET', '/repos/' + REPOSITORY + '/git/ref/tags/' + TAG, allow_missing=True)
        if value is None:
            return None
        obj = value['object']
        for _ in range(6):
            if obj.get('type') == 'commit' and verify.HEX40.fullmatch(str(obj.get('sha', ''))):
                return obj['sha']
            if obj.get('type') != 'tag' or not verify.HEX40.fullmatch(str(obj.get('sha', ''))):
                break
            obj = self.request('GET', '/repos/' + REPOSITORY + '/git/tags/' + obj['sha'])['object']
        raise ValueError('Android preview tag does not resolve to an expected commit')


def publish(client: GitHub, target_sha: str, assets: dict[str, bytes]) -> dict:
    existing_tag = client.tag_commit()
    if existing_tag is not None and existing_tag != target_sha:
        raise ValueError('The existing Android preview tag targets a different commit')
    release = client.find_release()
    if release is None:
        release = client.request('POST', '/repos/' + REPOSITORY + '/releases', payload={
            'tag_name': TAG, 'target_commitish': target_sha, 'name': TITLE, 'body': BODY,
            'draft': True, 'prerelease': True, 'make_latest': 'false'})
    if (release.get('tag_name') != TAG or release.get('target_commitish') != target_sha
            or not release.get('prerelease') or type(release.get('id')) is not int):
        raise ValueError('Existing release differs from the reviewed Android preview target')
    if not release.get('draft') and existing_tag != target_sha:
        raise ValueError('Public release has no matching Git tag')
    if not release.get('draft') and (release.get('name') != TITLE or release.get('body') != BODY):
        raise ValueError('Public Android preview text differs from the reviewed release')
    release_id = str(release['id'])
    prefix = '/repos/' + REPOSITORY + '/releases/' + release_id
    current = client.request('GET', prefix + '/assets?per_page=100')
    by_name = {entry['name']: entry for entry in current}
    if len(by_name) != len(current) or set(by_name) - set(assets):
        raise ValueError('Android preview contains duplicate or unexpected assets')
    if not release.get('draft') and set(by_name) != set(assets):
        raise ValueError('A public Android preview may only be retried with its complete original assets')
    for name, content in sorted(assets.items()):
        asset = by_name.get(name)
        if asset is None:
            if not release.get('draft'):
                raise ValueError('Public release assets will not be changed')
            asset = client.request('POST', prefix + '/assets?name=' + urllib.parse.quote(name, safe=''), content=content, upload=True)
        if (asset.get('name') != name or asset.get('size') != len(content) or asset.get('state') != 'uploaded'
                or type(asset.get('id')) is not int):
            raise ValueError('Existing or uploaded release asset metadata differs')
        actual = client.request('GET', '/repos/' + REPOSITORY + '/releases/assets/' + str(asset['id']),
                                binary=True, expected_bytes=len(content))
        if hashlib.sha256(actual).digest() != hashlib.sha256(content).digest():
            raise ValueError('Existing release asset has different bytes; it will not be replaced')
    if release.get('draft'):
        tag_before_publication = client.tag_commit()
        if tag_before_publication is not None and tag_before_publication != target_sha:
            raise ValueError('Android preview tag changed during draft preparation')
        release = client.request('PATCH', prefix, payload={'name': TITLE, 'body': BODY, 'draft': False, 'prerelease': True, 'make_latest': 'false'})
    if release.get('draft') or not release.get('prerelease') or client.tag_commit() != target_sha:
        raise ValueError('Android preview publication did not retain its reviewed target')
    return {'ok': True, 'tag': TAG, 'assets': sorted(assets), 'url': 'https://github.com/' + REPOSITORY + '/releases/tag/' + TAG}


def main() -> int:
    try:
        if (os.environ.get('GITHUB_EVENT_NAME') != 'push' or os.environ.get('GITHUB_REF') != 'refs/heads/codex/android-preview'
                or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY):
            raise ValueError('Publication is restricted to the reviewed Android preview push workflow')
        target_sha = os.environ.get('GITHUB_SHA', '')
        if not verify.HEX40.fullmatch(target_sha) or verify.run(['git', '-C', ROOT, 'rev-parse', 'HEAD']).strip() != target_sha:
            raise ValueError('Workflow target differs from the checked-out source')
        candidate = verify.validate_manifest(json.loads(ordinary_bytes(ROOT / 'android/release-candidate.json', maximum=16 * 1024).decode('utf-8')))
        assets = collect_assets(ROOT, candidate, ROOT / 'build/android-release-artifacts')
        sdk = Path(os.environ.get('ANDROID_HOME', os.environ.get('ANDROID_SDK_ROOT', '')))
        apk_path = ROOT / 'build/android-release-artifacts/api-28' / APK_NAME
        certificate = verify.signer_digest(verify.run([sdk / 'build-tools/36.0.0/apksigner', 'verify', '--verbose', '--print-certs', apk_path]))
        if certificate != candidate['certificate_sha256']:
            raise ValueError('Final APK signature differs from the verified public certificate')
        print(json.dumps(publish(GitHub(os.environ.get('GITHUB_TOKEN', '')), target_sha, assets), ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile):
        # Never print bearer tokens, request headers, signed URLs or response bodies.
        print(json.dumps({'ok': False, 'error': 'Android preview publication checks did not pass; existing assets were not overwritten'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
