"""Run the real UI payload/copy/status functions without a network or credentials."""
import shutil,subprocess,unittest
from pathlib import Path
class AgentConnectUITests(unittest.TestCase):
 def test_memory_only_contract(self):
  node=shutil.which('node')
  if not node:self.skipTest('Node unavailable')
  result=subprocess.run([node,'--test','tests/js/agent-connect-ui.test.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
