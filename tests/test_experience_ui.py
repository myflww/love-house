"""Human episodic view stays scoped and reads only safe projected material."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ExperienceUITests(unittest.TestCase):
    def test_shipped_local_component_comes_before_tooltips(self):
        from nkb.viz.builder import template
        html=template()
        marker='data-nkb-component="experience-ui.js"'
        self.assertEqual(html.count(marker),1)
        self.assertLess(html.index(marker),html.index('data-nkb-component="button-hints.js"'))
        for control in ('experienceLibraryBtn','experienceOrganizerBtn','experienceTimelineDialog','experienceTimelineList'):
            self.assertIn(control,html)

    @unittest.skipUnless(shutil.which('node'),'Node optional')
    def test_actual_async_component_and_scope_guards(self):
        result=subprocess.run([shutil.which('node'),'--test','--test-reporter=tap',str(Path(__file__).parent/'js/experience-ui.test.cjs')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('# fail 0',result.stdout)


if __name__=='__main__':unittest.main()
