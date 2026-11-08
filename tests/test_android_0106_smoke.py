"""The Android CI matrix must report its actual WebView and tested capabilities."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('android_0106_smoke', ROOT / 'scripts/run_android_0106_smoke.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Android0106ScopeTests(unittest.TestCase):
    def test_scope_never_turns_an_old_api36_provider_into_partial_success(self):
        old = {'major': 66}
        current = {'major': 140}
        partial = runner.scope_for(28, old)
        self.assertTrue(partial['partial'])
        self.assertFalse(partial['full_engine_verified'])
        self.assertEqual(partial['expected_tests'], 7)
        self.assertEqual(len(partial['classes']), 3)
        for api in (28, 36):
            full = runner.scope_for(api, current)
            self.assertFalse(full['partial'])
            self.assertTrue(full['full_engine_verified'])
            self.assertEqual(full['expected_tests'], 11)
            self.assertIsNone(full['classes'])
        for api in (26, 36):
            with self.subTest(api=api), self.assertRaises(ValueError):
                runner.scope_for(api, old)

    def test_provider_comes_from_one_actual_current_provider_line(self):
        line = '  Current WebView package (name, version): (com.google.android.webview, 66.0.3359.158)\n'
        value = runner.webview_identity('Other package info\n' + line)
        self.assertEqual(value, {'package': 'com.google.android.webview', 'version': '66.0.3359.158', 'major': 66})
        for invalid in ('No WebView installed', line + line, line.replace('66.0.3359.158', '../private')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                runner.webview_identity(invalid)

    def test_report_cases_require_matching_nonempty_real_raw_runner_records(self):
        text = ('INSTRUMENTATION_STATUS: class=example.ActualTest\n'
                'INSTRUMENTATION_STATUS: test=persistsUnicode\n'
                'INSTRUMENTATION_STATUS: numtests=1\nINSTRUMENTATION_STATUS_CODE: 1\n'
                'INSTRUMENTATION_STATUS: class=example.ActualTest\n'
                'INSTRUMENTATION_STATUS: test=persistsUnicode\n'
                'INSTRUMENTATION_STATUS: numtests=1\nINSTRUMENTATION_STATUS_CODE: 0\n'
                'OK (1 test)\nINSTRUMENTATION_CODE: -1\n')
        self.assertEqual(runner.verified_test_names(text, 1), [('example.ActualTest', 'persistsUnicode')])
        for raw, expected in ((text, 7), ('OK (0 tests)\nINSTRUMENTATION_CODE: -1\n', 0),
                              (text.replace('INSTRUMENTATION_STATUS_CODE: 0', 'INSTRUMENTATION_STATUS_CODE: -3'), 1)):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                runner.verified_test_names(raw, expected)


if __name__ == '__main__':
    unittest.main()
