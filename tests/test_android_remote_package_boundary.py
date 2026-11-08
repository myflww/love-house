"""Regression for the remote portal gate's obsolete zero-network assertion."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_android_remote_reports import check_production_boundary
from verify_android_release import APP_ID,ENGINE_ABIS,ENGINE_LIBRARIES


class ProductionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.permission="package: "+APP_ID+"\nuses-permission: name='android.permission.INTERNET'\n"
        self.entries=['assets/chaquopy/app.imy','assets/web/index.html']+[
            'lib/'+abi+'/'+name for abi in ENGINE_ABIS for name in ENGINE_LIBRARIES]
        self.proof={'schema':'love-house-production-apk-boundary/v1','package_validated':True,
                    'engine':True,'sha256':'a'*64,'entry_count':len(self.entries)}
    def check(self,permissions=None,entries=None,proof=None):
        return check_production_boundary(permissions or self.permission,'\n'.join(entries or self.entries),
                                         self.proof if proof is None else proof)
    def test_current_engine_passes_but_old_zero_network_and_extra_permissions_do_not(self):
        self.check()
        for permissions in ['package: '+APP_ID+'\n',self.permission+"uses-permission: name='android.permission.RECORD_AUDIO'\n",
                            self.permission+"uses-permission-sdk-m: name='android.permission.CAMERA'\n"]:
            with self.assertRaises(ValueError):self.check(permissions=permissions)
    def test_test_only_trust_extra_native_code_and_missing_engine_are_rejected(self):
        for entries in [self.entries+['res/raw/remote_test_ca.pem'],self.entries+['lib/arm64-v8a/other.so'],
                        self.entries[1:]]:
            with self.assertRaises(ValueError):self.check(entries=entries)
    def test_missing_false_or_wrong_artifact_evidence_never_passes(self):
        for proof in [{},{**self.proof,'package_validated':False},{**self.proof,'entry_count':0},
                      {**self.proof,'sha256':'not-a-real-digest'}]:
            with self.assertRaises(ValueError):self.check(proof=proof)


if __name__=='__main__':unittest.main()
