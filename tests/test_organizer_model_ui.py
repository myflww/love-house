from pathlib import Path
import shutil
import subprocess
import unittest

from nkb.viz.builder import template


class OrganizerModelUITests(unittest.TestCase):
    def test_component_is_inlined_once(self):
        self.assertEqual(template().count('data-nkb-component="organizer-model-ui.js"'), 1)

    @unittest.skipUnless(shutil.which('node'), 'Node optional')
    def test_actual_model_controls_discovery_and_save_scope(self):
        result = subprocess.run([shutil.which('node'), '--test',
            str(Path(__file__).parent / 'js' / 'organizer-model-ui.test.cjs')],
            capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
