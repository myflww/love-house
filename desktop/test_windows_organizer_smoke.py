"""The same organizer proof runs from source and the actual frozen executable."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from windows_organizer_smoke import organizer_smoke


class OrganizerPackageProofTests(unittest.TestCase):
    def test_loopback_model_with_session_key_and_exact_evidence_cleans_its_data(self):
        with tempfile.TemporaryDirectory() as directory:
            result=organizer_smoke(directory)
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['fake_api_calls'],1)
            self.assertEqual(result['real_model_calls'],0)
            self.assertFalse(result['real_credentials_accessed'])
            self.assertEqual(list(Path(directory).iterdir()),[])


if __name__=='__main__':unittest.main()
