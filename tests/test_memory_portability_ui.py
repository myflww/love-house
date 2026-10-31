"""Exercise shipped portability UI, offline assembly and script-content escaping."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.viz.builder import build, template


class MemoryPortabilityUITests(unittest.TestCase):
    def test_desktop_and_offline_share_the_same_inline_component_with_tooltips(self):
        html = template()
        component = 'data-nkb-component="memory-portability-ui.js"'
        self.assertEqual(html.count(component), 1)
        self.assertLess(html.index('data-nkb-component="connection-ux.js"'), html.index(component))
        self.assertLess(html.index(component), html.index('data-nkb-component="button-hints.js"'))
        self.assertNotIn('src="memory-portability-ui.js"', html)
        for control in ('inheritLibraryBtn', 'shareLibraryBtn', 'importMemoryShareBtn', 'sharePersonalConsent', 'shareAIConsent',
                        'downloadMemoryJSON', 'downloadMemoryMarkdown', 'memoryShareFile', 'confirmMemoryShareImport'):
            self.assertIn(control, html)
        self.assertIn('memoryInheritanceDialog', html)
        self.assertIn('memoryShareDialog', html)
        self.assertIn('memoryShareImportDialog', html)

    def test_inline_portability_script_escapes_mixed_case_script_end_sequences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'web').mkdir()
            (root/'web/index.html').write_text('<body><main>Existing page</main></BODY>')
            (root/'web/memory-portability-ui.js').write_text('const fixture="</ScRiPt><script>";')
            with patch('nkb.viz.builder.resources.files', return_value=root): html = template()
            self.assertNotIn('</ScRiPt>', html)
            self.assertIn('<\\/script><script>', html)
            self.assertEqual(html.count('</script>'), 1)

    def test_offline_export_escapes_untrusted_memory_text_without_dropping_portability_component(self):
        with tempfile.TemporaryDirectory() as directory:
            brain = Brain.new(name='离线验收')
            brain.add('恶意结束标签资料', '</ScRiPt><script>UNTRUSTED_MEMORY_PAYLOAD()</script>')
            path = build(brain, Path(directory)/'offline.html'); html = path.read_text('utf-8')
            self.assertIn('data-nkb-component="memory-portability-ui.js"', html)
            self.assertIn('\\u003c/ScRiPt>', html)
            self.assertNotIn('<script>UNTRUSTED_MEMORY_PAYLOAD()', html)
            self.assertIn("S.mode==='serve'", html)  # Connection/download actions are serve-only.

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for UI behavior checks')
    def test_real_download_consent_scope_native_save_and_ai_actions(self):
        script = Path(__file__).parent/'js/memory-portability-ui.test.cjs'
        result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap', str(script)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('# fail 0', result.stdout)


if __name__ == '__main__': unittest.main()
