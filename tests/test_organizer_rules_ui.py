from pathlib import Path
import shutil
import subprocess
import unittest
from nkb.viz.builder import template


class OrganizerRulesUITests(unittest.TestCase):
    def test_shipped_local_guide_component(self):
        html=template()
        self.assertEqual(html.count('data-nkb-component="organizer-rules-ui.js"'),1)
        self.assertIn('organizerRulesBtn',html)
        self.assertIn('organizerFullGuide',html)

    @unittest.skipUnless(shutil.which('node'),'Node optional')
    def test_real_read_only_action_and_scope_guards(self):
        result=subprocess.run([shutil.which('node'),'--test',str(Path(__file__).parent/'js/organizer-rules-ui.test.cjs')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
