#!/usr/bin/env python3
"""Fetch the already reviewed Apple Silicon runtime; verify before extracting."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / 'assets/licenses/python-3.12.14-20260825/provenance.json'
URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260825/cpython-3.12.14+20260825-aarch64-apple-darwin-pgo+lto-full.tar.zst'
SHA256 = 'bce7da43c65a574be0185c9cf8ae8305c44afb53f746a05e8c51415c8c621bf7'
MAX_BYTES = 1024 * 1024 * 1024


def verify_provenance():
    value = json.loads(PROVENANCE.read_text('utf-8'))
    if (value.get('archive') != URL or value.get('archive_sha256') != SHA256
            or value.get('python_version') != '3.12.14' or value.get('target_triple') != 'aarch64-apple-darwin'):
        raise ValueError('Mac runtime pin and reviewed licence provenance differ')
    return value


def verify_archive(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Mac Python archive exceeds the download limit')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != SHA256:
        raise ValueError('Mac Python archive does not match the reviewed SHA256')


def fetch(output, *, archive=None):
    verify_provenance()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Runtime output must be a fresh directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mac-runtime-', dir=output.parent) as temporary:
        staging = Path(temporary)
        candidate = Path(archive).resolve() if archive else staging / 'python.tar.zst'
        if archive is None:
            request = Request(URL, headers={'User-Agent':'LoveHouse-runtime-build'})
            with urlopen(request, timeout=120) as response, candidate.open('wb') as target:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_BYTES:
                        raise ValueError('Mac Python archive exceeds the download limit')
                    target.write(block)
        verify_archive(candidate)
        # The SHA pin is checked before any extraction. Only the installed
        # runtime subtree is selected; build sources do not enter the app.
        subprocess.run(['/usr/bin/tar', '-xf', str(candidate), '-C', str(staging), 'python/install'], check=True)
        runtime = staging / 'python/install'
        if not (runtime / 'bin/python3.12').is_file() or not (runtime / 'lib/python3.12/os.py').is_file():
            raise ValueError('The verified archive lacks its complete Python 3.12 install tree')
        approved = ROOT / 'assets/licenses/python-3.12.14-20260825/LICENSE.cpython-runtime.txt'
        if (runtime / 'lib/python3.12/LICENSE.txt').read_bytes() != approved.read_bytes():
            raise ValueError('Installed runtime licence differs from the reviewed copy')
        shutil.move(str(runtime), str(output))
    proof = {'schema':'love-house-macos-runtime/v1', 'python_version':'3.12.14',
             'target_triple':'aarch64-apple-darwin', 'archive':URL, 'archive_sha256':SHA256,
             'licence_verified':True}
    (output.parent / 'runtime-provenance.json').write_bytes((json.dumps(proof, indent=2)+'\n').encode('utf-8'))
    return output / 'bin/python3.12'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, help='Reuse an archive only after the same SHA verification')
    args = parser.parse_args()
    print(fetch(args.output, archive=args.archive))


if __name__ == '__main__':
    main()
