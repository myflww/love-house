"""Camera geometry invariants are tested with the same pure JS module as the UI."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ViewportPolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is optional for visual development checks')
    def test_adaptive_camera_geometry_and_packing(self):
        script=Path(__file__).parent/'js/viewport-policy.test.cjs'
        result=subprocess.run([shutil.which('node'),'--test','--test-reporter=tap',str(script)],
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('# pass 8',result.stdout)


if __name__=='__main__':
    unittest.main()
