"""Read-only recognition of known old MCP entries, never credential contents."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('legacy_config_detection',ROOT/'extensions/deepseek-harness/configure.py')
configure=importlib.util.module_from_spec(spec);spec.loader.exec_module(configure)

class LegacyDetectionTests(unittest.TestCase):
    def test_both_brands_and_yaml_wrapped_path_are_detected_without_secrets(self):
        for brand in ('爱之屋','知识星图'):
            with self.subTest(brand=brand),tempfile.TemporaryDirectory() as directory:
                profile=Path(directory);(profile/'cordis.yml').write_text('[]\n')
                bridge=str(profile/(brand+'.app')/'Contents/Resources/backend/harness_bridge.py')
                bridge=bridge.replace('harness_bridge.py','ha\\\n              rness_bridge.py')
                (profile/'cordis.patch.yml').write_text('- insert:\n    - id: memory-neural-kb\n      name: "@deepseek-ai/dsh-mcp-client"\n      config:\n        serverName: neural-memory\n        args:\n          - "'+bridge+'"\n        env:\n          FAKE_API_KEY: FAKE-NOT-A-REAL-KEY\n')
                before=(profile/'cordis.patch.yml').read_bytes();rows=configure._legacy_entries(profile)
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['target_library_id'],'default')
                self.assertFalse(rows[0]['explicit_library_binding']);self.assertNotIn('FAKE-NOT-A-REAL-KEY',str(rows))
                self.assertEqual((profile/'cordis.patch.yml').read_bytes(),before)
    def test_name_first_explicit_binding_and_unrelated_mcp_are_distinguished(self):
        with tempfile.TemporaryDirectory() as directory:
            profile=Path(directory);bridge=profile/'爱之屋.app/Contents/Resources/backend/harness_bridge.py'
            (profile/'cordis.yml').write_text('- name: "@deepseek-ai/dsh-mcp-client"\n  id: memory-neural-kb\n  config:\n    serverName: neural-memory\n    args:\n      - "'+str(bridge)+'"\n      - "--library-id"\n      - "lib_fixture"\n- id: unrelated\n  name: other-mcp\n  config:\n    serverName: unrelated\n')
            rows=configure._legacy_entries(profile)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['target_library_id'],'lib_fixture');self.assertTrue(rows[0]['explicit_library_binding'])
