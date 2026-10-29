#!/usr/bin/env python3
"""Prepare/scan a clean public source tree; never reads user app data or uploads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT_FILES = frozenset({
    '.gitignore', '.gitattributes', 'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'ROADMAP.md',
    'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'pyproject.toml', 'Makefile',
    '启动爱之屋.command', '启动知识星图.command', '启动爱之屋Windows.cmd',
})
ROOT_DIRS = frozenset({'.github', 'nkb', 'desktop', 'extensions', 'scripts',
                      'tests', 'examples', 'assets', 'docs'})
EXCLUDED_PARTS = frozenset({'.git', 'node_modules', '__pycache__', '.pytest_cache',
    '.mypy_cache', '.ruff_cache', '.venv', 'venv', 'env', 'reports', 'outputs',
    'references', '.runtime', '.DS_Store'})
TEXT_SUFFIXES = frozenset({'.py', '.js', '.mjs', '.cjs', '.ts', '.json', '.toml',
    '.md', '.txt', '.html', '.css', '.yaml', '.yml', '.swift', '.plist', '.command',
    '.svg', '.iss', '.spec', '.ps1', '.cmd', '.bat', '.sh', '.rc', '.manifest'})
BINARY_SUFFIXES = frozenset({'.png', '.woff2', '.ico'})
PRIVATE_SUFFIXES = ('.brain.json', '.sqlite3', '.sqlite3-wal', '.sqlite3-shm',
                    '.pem', '.p12', '.key', '.keychain', '.keychain-db')
PRIVATE_NAMES = frozenset({'brain.json', 'graph.json', 'connections.json',
    'libraries.json', 'providers.json', '.env', '.env.local', 'id_rsa',
    'id_ed25519', 'capture.sqlite3', 'organizer.sqlite3'})
MAX_SOURCE_BYTES = 40 * 1024 * 1024
SECRET_PATTERNS = (
    ('private-key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('github-token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b')),
    ('model-key', re.compile(r'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}\b')),
    ('aws-access-key', re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('url-credentials', re.compile(r'https?://[^\s/<>\"\']+:[^\s/<>\"\']+@[^\s/<>\"\']+')),
    ('mac-temporary-path', re.compile(r'/var/folders/[A-Za-z0-9]{2}/[A-Za-z0-9_]+/')),
    ('private-attachment', re.compile(r'(?:codex-clipboard-|nt_qq_)[A-Za-z0-9_-]{12,}')),
)
LITERAL_SECRET = re.compile(
    r'''(?ix)["'](?:api_key|access_token|auth_token|password|token|secret)["']\s*:\s*["']([A-Za-z0-9_./+=-]{20,})["']''')
EXAMPLE_VALUE = re.compile(r'(?i)(?:fake|dummy|example|placeholder|not.?a.?real|your[_-]|test[_-]|change.?me|invalid)')


def unsafe_svg(content: str) -> bool:
    """Public banners/icons are static shapes/text, with no active or remote content."""
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', content, re.I):
        return True
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return True
    if root.tag != '{http://www.w3.org/2000/svg}svg':
        return True
    allowed = {'svg', 'g', 'title', 'desc', 'defs', 'rect', 'path', 'circle', 'ellipse',
               'line', 'polyline', 'polygon', 'text', 'tspan', 'lineargradient',
               'radialgradient', 'stop', 'clippath', 'mask', 'use'}
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith('{http://www.w3.org/2000/svg}'):
            return True
        if element.tag.rsplit('}', 1)[-1].lower() not in allowed:
            return True
        for raw_name, value in element.attrib.items():
            name = raw_name.rsplit('}', 1)[-1].lower()
            if name.startswith('on') or name in {'style', 'base'} or '\\' in value:
                return True
            if name == 'href' and not value.startswith('#'):
                return True
            urls = re.findall(r'''url\(\s*['"]?([^'")\s]+)''', value, re.I)
            if any(not url.startswith('#') for url in urls):
                return True
    return False


def is_allowed(relative: Path) -> bool:
    """Source allowlist, excluding run output even if it sits under a source dir."""
    parts = relative.parts
    if not parts or any(p in EXCLUDED_PARTS or p.endswith('.egg-info') for p in parts):
        return False
    if relative.name in PRIVATE_NAMES or relative.name.endswith(PRIVATE_SUFFIXES):
        return False
    if relative.suffix in {'.pyc', '.pyo', '.map', '.log'}:
        return False
    if len(parts) == 1:
        return relative.name in ROOT_FILES
    if parts[0] not in ROOT_DIRS:
        return False
    if parts[0] == 'docs' and len(parts) > 1 and parts[1] == 'assets':
        return False  # Historical screenshots were never approved public assets.
    if parts[0] == 'extensions' and parts[1] != 'deepseek-harness':
        return False
    if 'dist' in parts and not (parts[:3] == ('extensions', 'deepseek-harness', 'dist')
                               or parts[:4] == ('nkb', 'service', 'harness', 'dist')):
        return False
    return (relative.suffix in TEXT_SUFFIXES | BINARY_SUFFIXES
            or relative.name in {'LICENSE', 'NOTICE', 'Makefile', 'py.typed'}
            or relative.name.startswith('LICENSE.'))


def scan_bytes(relative: Path, content: bytes, *, home: Path | None = None) -> list[dict]:
    """Report locations/types only. Never return a matching credential value."""
    findings = []
    if len(content) > MAX_SOURCE_BYTES:
        return [{'path': relative.as_posix(), 'line': 0, 'category': 'oversize-source'}]
    if relative.suffix in BINARY_SUFFIXES:
        return findings
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        return [{'path': relative.as_posix(), 'line': 0, 'category': 'unexpected-binary'}]
    if relative.suffix == '.svg' and unsafe_svg(text):
        findings.append({'path': relative.as_posix(), 'line': 0, 'category': 'unsafe-svg'})
    patterns = list(SECRET_PATTERNS)
    home = home or Path.home()
    # Source may use POSIX separators, native Windows separators or escaped
    # Windows paths in JSON/Python strings. Inspect all three consistently,
    # irrespective of the OS running this release gate.
    normalized_home = str(home).replace('\\', '/').rstrip('/')
    if normalized_home not in ('', '.') and not re.fullmatch(r'[A-Za-z]:', normalized_home):
        separator = r'(?:/|\\+)'
        home_pattern = separator.join(re.escape(part) for part in normalized_home.split('/'))
        flags = re.I if re.match(r'^[A-Za-z]:/', normalized_home) or normalized_home.startswith('//') else 0
        patterns.append(('developer-home-path', re.compile(home_pattern + r'(?=$|[/\\\s\'"<>])', flags)))
    for category, pattern in patterns:
        for match in pattern.finditer(text):
            if category in {'model-key', 'github-token'} and EXAMPLE_VALUE.search(match.group()):
                continue
            if category == 'url-credentials' and re.fullmatch(
                    r'https?://user:password@(?:remote\.example|example\.test)', match.group()):
                continue  # Exact reserved-domain negative-test fixtures, not arbitrary passwords.
            findings.append({'path': relative.as_posix(), 'line': text.count('\n', 0, match.start()) + 1,
                             'category': category})
    for match in LITERAL_SECRET.finditer(text):
        if EXAMPLE_VALUE.search(match.group(1)) or len(set(match.group(1))) < 5:
            continue
        findings.append({'path': relative.as_posix(), 'line': text.count('\n', 0, match.start()) + 1,
                         'category': 'literal-credential'})
    return findings


def collect(source: Path, *, staged: bool = False) -> tuple[list[Path], list[dict]]:
    files, findings = [], []
    for directory, dirs, names in os.walk(source, followlinks=False):
        base = Path(directory)
        for name in list(dirs):
            path = base / name
            if base == source and name not in ROOT_DIRS:
                if staged:
                    findings.append({'path': name, 'line': 0, 'category': 'unapproved-directory'})
                dirs.remove(name)
                continue
            if base == source / 'docs' and name == 'assets':
                if staged:
                    findings.append({'path': 'docs/assets', 'line': 0, 'category': 'historical-screenshots'})
                dirs.remove(name)
                continue
            if path.is_symlink():
                rel = path.relative_to(source)
                if staged or rel.parts[0] in ROOT_DIRS:
                    findings.append({'path': rel.as_posix(), 'line': 0, 'category': 'symlink'})
                dirs.remove(name)
            elif name in EXCLUDED_PARTS or name.endswith('.egg-info'):
                if staged:
                    findings.append({'path': path.relative_to(source).as_posix(), 'line': 0,
                                     'category': 'excluded-directory'})
                dirs.remove(name)
        for name in names:
            path = base / name
            rel = path.relative_to(source)
            if rel.as_posix() == 'PUBLIC_SOURCE_MANIFEST.json' and staged:
                findings.extend(scan_bytes(rel, path.read_bytes()))
                continue
            allowed = is_allowed(rel)
            if not allowed:
                if staged:
                    findings.append({'path': rel.as_posix(), 'line': 0, 'category': 'unapproved-file'})
                continue
            if path.is_symlink():
                findings.append({'path': rel.as_posix(), 'line': 0, 'category': 'symlink'})
                continue
            findings.extend(scan_bytes(rel, path.read_bytes()))
            files.append(rel)
    return sorted(files), findings


def verify_manifest(source: Path, files: list[Path]) -> list[dict]:
    """Verify the prepared file list and copied bytes, without printing file contents."""
    marker = source / 'PUBLIC_SOURCE_MANIFEST.json'
    try:
        manifest = json.loads(marker.read_text('utf-8'))
        entries = manifest['files']
        if manifest.get('schema') != 'love-house-public-source/v1' or not isinstance(entries, list):
            raise ValueError('schema')
        expected = {entry['path']: entry for entry in entries}
        if len(expected) != len(entries) or set(expected) != {p.as_posix() for p in files}:
            raise ValueError('files')
        for relative in files:
            content = (source / relative).read_bytes(); entry = expected[relative.as_posix()]
            if entry['bytes'] != len(content) or entry['sha256'] != hashlib.sha256(content).hexdigest():
                raise ValueError('hash')
    except (OSError, KeyError, TypeError, ValueError):
        return [{'path': 'PUBLIC_SOURCE_MANIFEST.json', 'line': 0, 'category': 'manifest-integrity'}]
    return []


def prepare(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError('Output must not exist; use a fresh staging directory')
    files, findings = collect(source)
    if findings:
        return {'ok': False, 'findings': findings}
    required = {'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'pyproject.toml'}
    if not required.issubset({p.as_posix() for p in files}):
        raise ValueError('Required release and license files are missing')
    if not (source / 'LICENSE').read_text().startswith('# PolyForm Noncommercial License 1.0.0'):
        raise ValueError('Expected official PolyForm Noncommercial License 1.0.0')
    destination.mkdir(parents=True)
    entries = []
    for rel in files:
        src, dst = source / rel, destination / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        content = dst.read_bytes()
        copied_findings = scan_bytes(rel, content)
        if copied_findings:
            return {'ok': False, 'findings': copied_findings}
        entries.append({'path': rel.as_posix(), 'bytes': len(content),
                        'sha256': hashlib.sha256(content).hexdigest()})
    manifest = {'schema': 'love-house-public-source/v1', 'files': entries,
                'excluded': ['user memories', 'credentials', 'reports', 'reference clones',
                             'rollback copies', 'historical screenshots', 'source maps']}
    (destination / 'PUBLIC_SOURCE_MANIFEST.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return {'ok': True, 'files': len(entries), 'bytes': sum(e['bytes'] for e in entries),
            'findings': [], 'manifest': 'PUBLIC_SOURCE_MANIFEST.json'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path)
    mode.add_argument('--scan', type=Path, help='Audit an already prepared tree; fail on extra files')
    args = parser.parse_args()
    try:
        if args.scan:
            files, findings = collect(args.scan.resolve(), staged=True)
            findings.extend(verify_manifest(args.scan.resolve(), files))
            result = {'ok': not findings, 'files': len(files), 'findings': findings}
        else:
            result = prepare(args.source, args.output)
    except (OSError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
