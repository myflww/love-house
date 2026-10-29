"""Exercise scoped handoff UI consent and async behavior, not its string layout."""
from pathlib import Path
import shutil
import subprocess
import unittest


class WindowHandoffUITests(unittest.TestCase):
    def test_shipped_template_has_one_handoff_after_portability_and_before_hints(self):
        from nkb.viz.builder import template
        html = template()
        marker = 'data-nkb-component="window-handoff-ui.js"'
        self.assertEqual(html.count(marker), 1)
        self.assertLess(html.index('data-nkb-component="memory-portability-ui.js"'), html.index(marker))
        self.assertLess(html.index(marker), html.index('data-nkb-component="button-hints.js"'))

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for UI behavior checks')
    def test_actual_consent_scope_size_races_separate_connection_and_clipboard(self):
        script = Path(__file__).parent/'js/window-handoff-ui.test.cjs'
        result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap', str(script)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('# pass 8', result.stdout)


if __name__ == '__main__': unittest.main()
