from pathlib import Path
import shutil
import subprocess
import unittest
from nkb.viz.builder import template


class ConnectionHelpUITests(unittest.TestCase):
    def test_help_is_local_and_available_after_both_connection_flows(self):
        html=template();marker='data-nkb-component="connection-help-ui.js"'
        self.assertEqual(html.count(marker),1)
        self.assertLess(html.index('data-nkb-component="agent-sources-ui.js"'),html.index(marker))
        self.assertLess(html.index(marker),html.index('data-nkb-component="button-hints.js"'))

    @unittest.skipUnless(shutil.which('node'),'Node optional for browser behavior')
    def test_route_help_focus_and_stale_library_behavior(self):
        result=subprocess.run([shutil.which('node'),'--test','--test-reporter=tap',str(Path(__file__).parent/'js/connection-help-ui.test.cjs')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('# fail 0',result.stdout)


if __name__=='__main__':unittest.main()
