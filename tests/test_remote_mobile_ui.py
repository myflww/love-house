"""Exercise the shipped mobile configuration and truthful capture status functions."""
from pathlib import Path
import shutil
import subprocess
import unittest

class RemoteMobileUITests(unittest.TestCase):
    def test_https_config_and_capture_state(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable')
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([node,'--test','tests/js/remote-mobile.test.mjs'],cwd=root,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
