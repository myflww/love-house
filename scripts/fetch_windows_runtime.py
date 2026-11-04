#!/usr/bin/env python3
"""Fetch the pinned Microsoft x64 Evergreen installer and verify before bundling.

The installer stays out of Git. Both its SHA256 and its Authenticode publisher
are checked on Windows, including when reusing a previously downloaded file.
Changing the upstream installer requires a reviewed pin/manifest update.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FILENAME = 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
SHA256 = '1c401b327fbc7bb9731b4e350a2194f083cbc3ede46508d52e1cae6610a39bea'
URL = ('https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/'
       'f699d81e-69ce-4b09-aa07-23ff2713045b/' + FILENAME)
MANIFEST = {
    'schema': 'love-house-webview2-installer/v1',
    'filename': FILENAME,
    'sha256': SHA256,
    'publisher': 'Microsoft Corporation',
    'architecture': 'x64',
}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_manifest(directory):
    (directory / 'manifest.json').write_text(
        json.dumps(MANIFEST, indent=2) + '\n', encoding='utf-8')


def ensure_runtime(bundle_root=ROOT, *, installer_path=None):
    """Return the verified runtime directory; no installer is executed here."""
    if sys.platform != 'win32':
        raise RuntimeError('Validate Microsoft Authenticode on Windows before bundling.')
    sys.path.insert(0, str(ROOT / 'desktop'))
    from windows_prerequisites import bundled_installer_status

    bundle_root = Path(bundle_root).resolve()
    destination = bundle_root / 'resources' / 'runtime'
    target = destination / FILENAME
    if installer_path is None and target.is_file():
        # A preexisting binary is not a trusted cache until verified again.
        status = bundled_installer_status(bundle_root=bundle_root)
        if status.get('verified') is not True:
            raise RuntimeError('Cached WebView2 installer failed verification: ' + status.get('code', 'unknown'))
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='love-house-runtime-', dir=destination.parent) as staging:
        stage_root = Path(staging)
        stage_runtime = stage_root / 'resources' / 'runtime'
        stage_runtime.mkdir(parents=True)
        candidate = stage_runtime / FILENAME
        if installer_path is not None:
            shutil.copyfile(Path(installer_path).resolve(), candidate)
        else:
            request = urllib.request.Request(URL, headers={'User-Agent': 'LoveHouse-Windows-Build/1'})
            with urllib.request.urlopen(request, timeout=60) as response:
                endpoint = urllib.parse.urlparse(response.geturl())
                if endpoint.scheme != 'https' or endpoint.hostname != 'msedge.sf.dl.delivery.mp.microsoft.com':
                    raise RuntimeError('WebView2 installer redirected outside the pinned Microsoft host.')
                with candidate.open('wb') as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
        if sha256(candidate) != SHA256:
            raise RuntimeError('WebView2 installer SHA256 differs from the reviewed pin.')
        write_manifest(stage_runtime)
        status = bundled_installer_status(bundle_root=stage_root)
        if status.get('verified') is not True:
            raise RuntimeError('WebView2 installer Authenticode/manifest verification failed: ' + status.get('code', 'unknown'))
        destination.mkdir(parents=True, exist_ok=True)
        # Replace only after the candidate has passed both independent checks.
        candidate.replace(target)
        write_manifest(destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, help='Reuse a downloaded installer after the same checks.')
    parser.add_argument('--bundle-root', type=Path, default=ROOT)
    arguments = parser.parse_args()
    path = ensure_runtime(arguments.bundle_root, installer_path=arguments.installer)
    print(json.dumps({'ok': True, 'directory': str(path), 'sha256': SHA256}))
