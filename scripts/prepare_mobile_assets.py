#!/usr/bin/env python3
"""Prepare a strictly local Android WebView asset bundle.

Only reviewed static files under mobile/web and project licence notices are
copied. No desktop Runtime, personal exports, credentials, caches or symlinks
are accepted. The only replaceable output is an owned generated build folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import prepare_public_release as public_source

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'love-house-mobile-assets/v1'
MARKER = '.love-house-assets.json'
STATIC_SUFFIXES = frozenset({'.html', '.css', '.js', '.mjs', '.svg', '.png', '.woff2', '.webmanifest'})
LICENSE_NAMES = frozenset({'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'})
FONT_LICENSE = 'assets/ark-pixel-OFL.txt'
FORBIDDEN_PARTS = frozenset({'.git', '.gradle', 'node_modules', 'data', 'reports', 'build', 'dist', '__pycache__'})
MAX_BUNDLE_BYTES = 32 * 1024 * 1024


def _validate_output(root: Path, output: Path) -> Path:
    root = root.resolve()
    output = output.resolve()
    build_root = (root / 'android/app/build').resolve()
    if not build_root.is_relative_to(root) or output == build_root or not output.is_relative_to(build_root):
        raise ValueError('Mobile assets output must be beneath this project\'s android/app/build directory')
    return output


def _source_files(root: Path) -> dict[str, bytes]:
    source = root / 'mobile/web'
    if not source.is_dir():
        raise ValueError('mobile/web is missing; create the shared mobile web application before building Android')
    if (root / 'mobile').is_symlink() or source.is_symlink() or not source.resolve().is_relative_to(root):
        raise ValueError('Mobile web source must be a real directory inside this project')
    files: dict[str, bytes] = {}
    case_names: set[str] = set()
    size = 0
    for path in sorted(source.rglob('*'), key=lambda item: item.as_posix()):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise ValueError('Symlinks are not allowed in mobile web assets: ' + relative.as_posix())
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            raise ValueError('Generated or private directories are not mobile assets: ' + relative.as_posix())
        if path.is_dir():
            continue
        if not path.is_file() or (path.suffix not in STATIC_SUFFIXES and path.name not in LICENSE_NAMES
                                  and not path.name.startswith('LICENSE.') and relative.as_posix() != FONT_LICENSE):
            raise ValueError('Unapproved mobile web asset: ' + relative.as_posix())
        folded = relative.as_posix().casefold()
        if folded in case_names:
            raise ValueError('Case-colliding mobile web assets are not portable')
        case_names.add(folded)
        if size + path.stat().st_size > MAX_BUNDLE_BYTES:
            raise ValueError('Mobile static assets exceed the 32 MiB build limit')
        content = path.read_bytes()
        if relative.as_posix() == FONT_LICENSE:
            approved = root / 'assets/fonts/ark-pixel-OFL.txt'
            if not approved.is_file() or approved.is_symlink() or content != approved.read_bytes():
                raise ValueError('Mobile font licence differs from the approved original notice')
        findings = public_source.scan_bytes(Path('mobile/web') / relative, content)
        if findings:
            categories = sorted({finding['category'] for finding in findings})
            raise ValueError('Mobile web asset failed public-source checks: ' + relative.as_posix() + ' (' + ', '.join(categories) + ')')
        size += len(content)
        if size > MAX_BUNDLE_BYTES:
            raise ValueError('Mobile static assets exceed the 32 MiB build limit')
        files['web/' + relative.as_posix()] = content
    if not files.get('web/index.html'):
        raise ValueError('mobile/web/index.html is missing or empty')
    for name in LICENSE_NAMES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Required project licence notice is missing: ' + name)
        content = path.read_bytes()
        if public_source.scan_bytes(Path(name), content):
            raise ValueError('Project licence notice failed public-source checks: ' + name)
        target = 'web/' + name
        if target in files and files[target] != content:
            raise ValueError('Mobile source conflicts with the project licence notice: ' + name)
        files[target] = content
    for name in ('LICENSE.androidx-Apache-2.0.txt', 'THIRD_PARTY_NOTICES.md'):
        path = root / 'android' / name
        if path.is_file() and not path.is_symlink():
            content = path.read_bytes()
            if public_source.scan_bytes(Path('android') / name, content):
                raise ValueError('Android licence notice failed public-source checks: ' + name)
            files['web/android-licenses/' + name] = content
    return files


def prepare(root: Path = ROOT, output: Path | None = None) -> dict:
    root = root.resolve()
    requested_output = output if output is not None else root / 'android/app/build/generated/mobileAssets'
    if requested_output.is_symlink():
        raise ValueError('Refusing a symlink mobile assets output')
    output = _validate_output(root, requested_output)
    # Complete all input/secret validation before touching an existing build.
    files = _source_files(root)
    if output.exists():
        if not output.is_dir():
            raise ValueError('Mobile assets output is not a directory')
        if any(output.iterdir()):
            try:
                marker = json.loads((output / MARKER).read_text('utf-8'))
            except (OSError, ValueError, UnicodeError) as exc:
                raise ValueError('Refusing to replace an unowned non-empty output directory') from exc
            if not isinstance(marker, dict) or marker.get('schema') != SCHEMA or marker.get('output') != output.relative_to(root).as_posix():
                raise ValueError('Generated mobile asset ownership marker does not match')
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    with tempfile.TemporaryDirectory(prefix='.love-house-assets-', dir=output.parent) as temporary:
        stage = Path(temporary)
        for name, content in sorted(files.items()):
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            entries.append({'path': name, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        manifest = {'schema': SCHEMA, 'output': output.relative_to(root).as_posix(), 'files': entries}
        (stage / MARKER).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
        # Validate the resolved Windows target again directly before removal.
        if _validate_output(root, output) != output:
            raise ValueError('Generated assets output changed during preparation')
        if output.exists():
            shutil.rmtree(output)
        # Moving children keeps TemporaryDirectory cleanup valid on all hosts.
        output.mkdir()
        for child in list(stage.iterdir()):
            target = output / child.name
            if not child.resolve().is_relative_to(stage.resolve()) or not target.resolve().is_relative_to(output):
                raise ValueError('Refusing a move outside the generated mobile build')
            shutil.move(str(child), str(target))
    return {'ok': True, 'schema': SCHEMA, 'files': len(entries), 'bytes': sum(entry['bytes'] for entry in entries),
            'generated': output.relative_to(root).as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = prepare(ROOT, args.output)
    except (OSError, ValueError) as exc:
        # Error strings contain only controlled explanations or relative names,
        # never the rejected credential contents or personal app data.
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
