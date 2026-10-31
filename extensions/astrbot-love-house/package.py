#!/usr/bin/env python3
"""Package the experimental plugin 0.2.0 from an explicit source-only allowlist."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import os
from pathlib import Path
import shutil
import stat
import zipfile

FILES = ("__init__.py", "main.py", "bridge.py", "source_client.py", "metadata.yaml", "_conf_schema.json", "README.md", "LICENSE")
PLUGIN_DIR = Path(__file__).resolve().parent
MAX_SOURCE_BYTES = 4 * 1024 * 1024


def _read_regular(path, maximum):
    """Read a bounded regular source without following file symlinks or FIFOs."""
    fd = None
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise ValueError('Package input must be a regular source file: ' + path.name)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('Package input changed during source validation: ' + path.name)
        if opened.st_size > maximum:
            raise ValueError('Plugin source exceeds the 4 MiB source budget')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError('Plugin source exceeds the 4 MiB source budget')
        return data
    except OSError:
        raise ValueError('Required regular source file is unavailable: ' + path.name) from None
    finally:
        if fd is not None:
            os.close(fd)


def package_bytes(*, strict_sdk=True):
    """Return a deterministic, source-only AstrBot ZIP; perform no file writes.

    The HTTP endpoint and local command share this exact routine. Filesystem
    timestamps/permissions never become archive metadata, and configuration,
    message journals and queues are never discovered or traversed.
    """
    if type(strict_sdk) is not bool:
        raise ValueError('strict_sdk must be a boolean')
    root = Path(PLUGIN_DIR)
    contents, used = {}, 0
    for name in FILES:
        data = _read_regular(root / name, MAX_SOURCE_BYTES - used)
        contents[name] = data
        used += len(data)
    if strict_sdk:
        sdk = root.parents[1] / 'nkb/service/source_client.py'
        if _read_regular(sdk, MAX_SOURCE_BYTES) != contents['source_client.py']:
            raise ValueError('Vendored SDK differs from the repository SDK')
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            info = zipfile.ZipInfo('astrbot_plugin_love_house/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.internal_attr = 0
            info.extra = b''
            info.comment = b''
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, contents[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync-client', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(PLUGIN_DIR)
    sdk = root.parents[1] / 'nkb/service/source_client.py'
    if args.sync_client:
        try:
            _read_regular(sdk, MAX_SOURCE_BYTES)
        except ValueError as error:
            raise SystemExit(str(error)) from None
        if (root / 'source_client.py').is_symlink():
            raise SystemExit('Refusing to synchronize through a vendored SDK symlink')
        shutil.copy2(sdk, root / 'source_client.py')
    try:
        payload = package_bytes(strict_sdk=args.check)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    if args.output:
        output = args.output.resolve()
        if output.exists():
            raise SystemExit('Output already exists; choose a new package path')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as stream:
            stream.write(payload)
        print(str(output) + '\nsha256=' + hashlib.sha256(payload).hexdigest())
    else:
        print('Source package validated; no private files included')


if __name__ == '__main__':
    main()
