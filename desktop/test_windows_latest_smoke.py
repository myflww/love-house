"""Exercise the same fake-model purpose flow that is frozen into the app."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from windows_latest_smoke import latest_backend_smoke


class LatestPackageProofTests(unittest.TestCase):
    def test_quick_persona_preserves_factual_queue_and_budget_counted_normal_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            result=latest_backend_smoke(directory)
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['fake_model_calls'],2)
            self.assertEqual(result['budget_count'],2)
            self.assertEqual(result['assistant_evidence_count'],2)
            self.assertEqual(result['real_model_calls'],0)
            self.assertFalse(result['real_credentials_accessed'])
            self.assertEqual(list(Path(directory).iterdir()),[])


if __name__=='__main__':unittest.main()
