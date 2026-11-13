"""Read the reviewed Android identity without importing application code."""
from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def release_identity(root=ROOT):
    root = Path(root)
    text = (root / 'android/app/build.gradle').read_text('utf-8')
    names = re.findall(r"^\s*versionName\s+'([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.-]*)'\s*$", text, re.M)
    codes = re.findall(r'^\s*versionCode\s+([1-9][0-9]*)\s*$', text, re.M)
    if len(names) != 1 or len(codes) != 1:
        raise ValueError('Exactly one reviewed Android version name/code is required')
    tree = ast.parse((root / 'nkb/_version.py').read_text('utf-8'))
    core = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == '__version__' and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)]
    if core != names:
        raise ValueError('Android package and shared memory engine versions differ')
    return names[0], int(codes[0])
