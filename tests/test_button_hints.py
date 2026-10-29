"""UI component packaging and behavior, without external dependencies or API calls."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nkb.viz.builder import template


class ButtonHintsTests(unittest.TestCase):
    def test_help_is_self_contained_in_desktop_and_offline_template(self):
        html = template()
        self.assertIn('data-nkb-component="button-hints.js"', html)
        self.assertLess(html.index('data-nkb-component="button-hints.js"'), html.lower().rfind('</body>'))
        self.assertIn('role\', \'tooltip', html)
        self.assertNotIn('src="button-hints.js"', html)
        if 'data-nkb-component="connection-ux.js"' in html:
            self.assertLess(html.index('data-nkb-component="connection-ux.js"'), html.index('data-nkb-component="button-hints.js"'))

    def test_inline_components_escape_script_end_sequences_in_any_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'web').mkdir()
            (root/'web/index.html').write_text('<body><main>Existing app</main></BODY>')
            (root/'web/button-hints.js').write_text('const example="</ScRiPt><script>";')
            with patch('nkb.viz.builder.resources.files',return_value=root):
                html=template()
            self.assertIn('<\\/script><script>',html)
            self.assertNotIn('</ScRiPt>',html)
            self.assertEqual(html.count('</script>'),1)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for UI development checks')
    def test_hover_focus_disabled_privacy_and_dynamic_dialog_behavior(self):
        script=Path(__file__).parent/'js/button-hints.test.cjs'
        result=subprocess.run([shutil.which('node'),'--test','--test-reporter=tap',str(script)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('# pass 4',result.stdout)


if __name__=='__main__':unittest.main()
