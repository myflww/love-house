from pathlib import Path
import shutil
import subprocess
import unittest

from nkb.viz.builder import template


class AgentSourcesUITests(unittest.TestCase):
    def test_local_source_component_is_shipped_after_portability_before_hints(self):
        html=template();marker='data-nkb-component="agent-sources-ui.js"'
        self.assertEqual(html.count(marker),1)
        self.assertLess(html.index('data-nkb-component="memory-portability-ui.js"'),html.index(marker))
        self.assertLess(html.index(marker),html.index('data-nkb-component="button-hints.js"'))
        self.assertIn('agentSourceConsent',html);self.assertIn('agentSourceConfigPath',html)

    @unittest.skipUnless(shutil.which('node'),'Node optional for behavior tests')
    def test_actual_source_view_consented_creation_scope_pause_and_same_machine_paths(self):
        result=subprocess.run([shutil.which('node'),'--test','--test-reporter=tap',str(Path(__file__).parent/'js/agent-sources-ui.test.cjs')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('# fail 0',result.stdout)


if __name__=='__main__':unittest.main()
