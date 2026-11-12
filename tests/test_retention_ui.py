"""Continuous-retention UI has scoped async behavior, no expiry-day controls."""
from pathlib import Path
import shutil
import subprocess
import unittest


class RetentionUITests(unittest.TestCase):
    def test_shipped_retention_component_is_inline_once_before_tooltips(self):
        from nkb.viz.builder import template
        html = template()
        marker = 'data-nkb-component="retention-ui.js"'
        self.assertEqual(html.count(marker), 1)
        self.assertLess(html.index(marker), html.index('data-nkb-component="button-hints.js"'))
        self.assertIn('memoryRetentionBtn', html)
        self.assertIn('memoryRetentionDialog', html)

    @unittest.skipUnless(shutil.which('node'), 'Node optional for UI behavior checks')
    def test_real_component_scope_draft_locks_read_only_failures_and_no_fixed_time_controls(self):
        result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap',
                                 str(Path(__file__).parent/'js/retention-ui.test.cjs')],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# fail 0', result.stdout)

    def test_manual_recall_switch_is_distinguished_from_connected_use_feedback(self):
        html = (Path(__file__).resolve().parents[1]/'nkb/viz/web/index.html').read_text('utf-8')
        self.assertIn('<span>手动召回时巩固</span>', html)
        self.assertIn('只作用于点击“关联召回”', html)
        self.assertIn('连接取回资料的使用反馈，在“记忆规律”中单独设置', html)


if __name__ == '__main__': unittest.main()
