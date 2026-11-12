#!/usr/bin/env python3
"""Check the shared heart artwork without changing assets or user settings."""
from __future__ import annotations

import argparse
import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

from prepare_public_release import safe_embedded_png, unsafe_svg

ROOT = Path(__file__).resolve().parent.parent
PNG_PREFIX = 'data:image/png;base64,'


class BrandImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'img' and values.get('id') == 'houseBrandIcon':
            if len(values) != len(attrs):
                raise ValueError('The header brand image contains duplicate attributes')
            self.sources.append(values.get('src', ''))


def header_png(html):
    parser = BrandImageParser()
    parser.feed(html)
    if len(parser.sources) != 1 or not safe_embedded_png(parser.sources[0]):
        raise ValueError('The header must contain exactly one valid embedded brand PNG')
    return base64.b64decode(parser.sources[0][len(PNG_PREFIX):], validate=True)


def check(app=None):
    master = (ROOT / 'assets/branding/love-house-icon.png').read_bytes()
    if not safe_embedded_png(PNG_PREFIX + base64.b64encode(master).decode('ascii')):
        raise ValueError('Canonical brand PNG is not a bounded static raster')
    width, height, depth, color, *_ = struct.unpack('>IIBBBBB', master[16:29])
    if depth != 8 or color != 6:
        raise ValueError('The heart master must preserve its RGBA transparency')
    metadata = json.loads((ROOT / 'assets/branding/brand-provenance.json').read_text())
    digest = hashlib.sha256(master).hexdigest()
    if (metadata['sha256'] != digest or metadata['bytes'] != len(master)
            or (metadata['width'], metadata['height']) != (width, height)):
        raise ValueError('Brand source/provenance bytes do not match')
    if metadata['generation']['prompt'] != 'assets/branding/icon-prompt.txt':
        raise ValueError('Generation prompt must use the public relative archive path')
    prompt = (ROOT / 'assets/branding/icon-prompt.txt').read_bytes()
    if hashlib.sha256(prompt).hexdigest() != metadata['generation']['prompt_sha256']:
        raise ValueError('Archived generation prompt does not match its provenance')
    html = (ROOT / 'nkb/viz/web/index.html').read_text()
    if header_png(html) != master:
        raise ValueError('Web header artwork differs from the canonical heart')
    warm = (ROOT / 'nkb/viz/web/warm-theme.js').read_text()
    if 'mark.src=brandImage.src' not in warm:
        raise ValueError('The empty-memory page no longer reuses the header heart')
    banner = (ROOT / 'assets/branding/project-banner.svg').read_text()
    if unsafe_svg(banner):
        raise ValueError('Brand banner contains unsupported or active SVG content')
    images = ET.fromstring(banner).findall('{http://www.w3.org/2000/svg}image')
    if len(images) != 1 or images[0].get('id') != 'love-house-heart':
        raise ValueError('Banner must reuse one canonical heart image')
    if base64.b64decode(images[0].get('href', '')[len(PNG_PREFIX):], validate=True) != master:
        raise ValueError('Banner artwork differs from the canonical heart')
    for name in ('build_macos.py', 'build_windows.py'):
        if 'assets/branding/love-house-icon.png' not in (ROOT / 'scripts' / name).read_text():
            raise ValueError('Native icon builder no longer points to the canonical heart')
    installed = False
    if app is not None:
        resources = app / 'Contents/Resources'
        if (resources / 'AppIconSource.png').read_bytes() != master:
            raise ValueError('macOS app icon source differs from the canonical heart')
        if header_png((resources / 'backend/nkb/viz/web/index.html').read_text()) != master:
            raise ValueError('macOS bundled header differs from the canonical heart')
        if not (resources / 'LoveHouse.icns').is_file():
            raise ValueError('macOS native icon container is missing')
        installed = True
    return {'ok': True, 'canonical': 'assets/branding/love-house-icon.png',
            'sha256': digest, 'bytes': len(master), 'width': width, 'height': height,
            'web_header_and_empty_share_master': True, 'banner_shares_master': True,
            'native_builders_share_master': True, 'app_checked': installed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Read-only validation (the default)')
    parser.add_argument('--app', type=Path, help='Also verify a built/installed macOS app without launching it')
    args = parser.parse_args()
    print(json.dumps(check(args.app), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
