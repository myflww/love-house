#!/usr/bin/env python3
"""Copy reviewed desktop engine sources into the owned Android build directory.

This is a build-time copy, never an export of a running memory directory.
No developer environment, desktop runtime or credential material is included.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import prepare_public_release as public

ROOT = Path(__file__).resolve().parents[1]
MARKER = ".love-house-engine.json"
SCHEMA = "love-house-android-engine/v1"
MAX_BYTES = 32 * 1024 * 1024


def prepare(root=ROOT):
    root = Path(root).resolve()
    output = root / "android/app/build/generated/enginePython"
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents if parent != root and parent.is_relative_to(root)):
        raise ValueError("Android engine output must not contain symlinks")
    source_roots = [(root / "nkb", Path("nkb")),
                    (root / "android/app/src/main/python/lovehouse_android", Path("lovehouse_android"))]
    files = {}
    for source, prefix in source_roots:
        if source.is_symlink() or not source.is_dir() or not source.resolve().is_relative_to(root):
            raise ValueError("Reviewed Android engine source is missing")
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(root)
            if any(part in public.EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError("Engine source symlinks are not allowed")
            if path.is_dir():
                continue
            if not path.is_file() or not public.is_allowed(relative):
                # Do not silently include app data which was left beside source.
                if path.suffix in (".pyc", ".pyo"):
                    continue
                raise ValueError("Unapproved Android engine source: " + relative.as_posix())
            content = path.read_bytes()
            if public.scan_bytes(relative, content):
                raise ValueError("Android engine source failed public checks: " + relative.as_posix())
            files[(prefix / path.relative_to(source)).as_posix()] = content
    icon = root / 'mobile/web/assets/love-house-icon.png'
    if icon.is_file() and not icon.is_symlink():
        files['lovehouse_android/icon.png'] = icon.read_bytes()
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        content = (root / name).read_bytes()
        if public.scan_bytes(Path(name), content):
            raise ValueError("Android engine licence notice failed checks")
        files["lovehouse_android/licenses/" + name] = content
    # Android-specific runtime notices are part of the distributable engine,
    # independent of the desktop runtime or any developer SDK installation.
    license_root = root / "android/licenses"
    if license_root.exists():
        if license_root.is_symlink() or not license_root.is_dir():
            raise ValueError("Android runtime notices must be a real source directory")
        for path in sorted(license_root.rglob("*")):
            if path.is_symlink():
                raise ValueError("Android runtime notice symlinks are not allowed")
            if path.is_dir():
                continue
            relative = path.relative_to(root)
            if not path.is_file() or path.suffix not in {".txt", ".md", ".json"} or not public.is_allowed(relative):
                raise ValueError("Unapproved Android runtime notice")
            content = path.read_bytes()
            if public.scan_bytes(relative, content):
                raise ValueError("Android runtime notice failed public checks")
            files["lovehouse_android/licenses/android/licenses/" + path.relative_to(license_root).as_posix()] = content
    for name in ("THIRD_PARTY_NOTICES.md", "LICENSE.androidx-Apache-2.0.txt"):
        path = root / "android" / name
        if path.is_file() and not path.is_symlink():
            content = path.read_bytes()
            if public.scan_bytes(path.relative_to(root), content):
                raise ValueError("Android licence notice failed public checks")
            files["lovehouse_android/licenses/android/" + name] = content
    size = sum(map(len, files.values()))
    if size > MAX_BYTES or not files.get("nkb/service/host.py") or not files.get("lovehouse_android/__init__.py"):
        raise ValueError("Android engine source size or structure is invalid")
    if output.exists() and any(output.iterdir()):
        try:
            marker = json.loads((output / MARKER).read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Refusing to replace an unowned engine build directory") from exc
        if marker.get("schema") != SCHEMA:
            raise ValueError("Android engine ownership marker is invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": SCHEMA, "files": [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())]}
    with tempfile.TemporaryDirectory(prefix=".engine-", dir=output.parent) as directory:
        stage = Path(directory)
        for name, data in files.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (stage / MARKER).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(stage, output)
    return {"ok": True, "files": len(files), "bytes": size, "output": output.relative_to(root).as_posix()}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'android/app/build/generated/enginePython')
    arguments = parser.parse_args()
    try:
        if arguments.output.resolve() != (ROOT / 'android/app/build/generated/enginePython').resolve():
            raise ValueError('Only the owned Android engine output is allowed')
        print(json.dumps(prepare()))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
