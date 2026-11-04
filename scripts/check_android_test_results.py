#!/usr/bin/env python3
"""Require actual, non-empty Android instrumentation results before packaging."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def check(reports: Path) -> dict:
    if not reports.is_dir():
        raise ValueError('Android instrumentation reports are missing')
    paths = sorted(reports.rglob('*.xml'))
    if not paths:
        raise ValueError('Android instrumentation produced no JUnit XML reports')
    tests = failures = errors = skipped = 0
    for path in paths:
        if path.is_symlink():
            raise ValueError('Symlink instrumentation reports are not accepted')
        try:
            root = ET.parse(path).getroot()
            suites = [root] if root.tag == 'testsuite' else list(root.iter('testsuite'))
            if not suites:
                raise ValueError('Android report contains no test suite')
            for suite in suites:
                count = int(suite.get('tests', '0'))
                failed = int(suite.get('failures', '0'))
                errored = int(suite.get('errors', '0'))
                ignored = int(suite.get('skipped', '0'))
                if min(count, failed, errored, ignored) < 0:
                    raise ValueError('Android report counts are invalid')
                # Assert real test cases as well as generator summary fields.
                cases = list(suite.findall('testcase'))
                if len(cases) != count:
                    raise ValueError('Android report test count does not match its cases')
                tests += count
                failures += max(failed, sum(bool(case.findall('failure')) for case in cases))
                errors += max(errored, sum(bool(case.findall('error')) for case in cases))
                skipped += max(ignored, sum(bool(case.findall('skipped')) for case in cases))
        except (ET.ParseError, TypeError) as exc:
            raise ValueError('Android instrumentation produced invalid JUnit XML') from exc
    if not tests:
        raise ValueError('No Android instrumentation tests actually ran')
    if failures or errors or skipped:
        raise ValueError('Android instrumentation has failed, errored or skipped tests')
    return {'ok': True, 'tests': tests, 'failures': failures, 'errors': errors, 'skipped': skipped}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, default=ROOT / 'android/app/build/outputs/androidTest-results/connected')
    args = parser.parse_args()
    try:
        result = check(args.reports)
    except (OSError, ValueError):
        print(json.dumps({'ok': False, 'error': 'Missing, invalid, empty or unsuccessful Android instrumentation evidence'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
