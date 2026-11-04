"""Signing handoff contracts with inert files; no key generation or real private key."""
from pathlib import Path
import hashlib
import importlib.util
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('upgrade_signing',ROOT/'scripts/sign_android_upgrade.py')
signing=importlib.util.module_from_spec(spec);spec.loader.exec_module(signing)

class AndroidUpgradeSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);tools=self.root/'tools';(tools/'lib').mkdir(parents=True)
        suffix='.exe' if signing.os.name=='nt' else ''
        for name in ('aapt'+suffix,'zipalign'+suffix,'lib/apksigner.jar'):(tools/name).write_bytes(b'FAKE inert tool fixture')
        apk=self.root/'unsigned.apk'
        with zipfile.ZipFile(apk,'w') as archive:archive.writestr('AndroidManifest.xml',b'FAKE inert manifest fixture')
        key=self.root/'existing.jks';key.write_bytes(b'FAKE inert key placeholder; not a generated key')
        java=self.root/('java'+suffix);java.write_bytes(b'FAKE inert Java fixture')
        self.args=SimpleNamespace(unsigned_apk=apk,output_apk=self.root/'output.apk',keystore=key,build_tools=tools,
            java=java,expected_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),alias='existing-fixture-alias')
        self.calls=[];self.cert=signing.ORIGINAL_CERT;self.badging="package: name='io.github.myflww.lovehouse.preview' versionCode='2' versionName='0.8.0rc1'\nsdkVersion:'26'\ntargetSdkVersion:'36'\n"
    def tearDown(self):self.temp.cleanup()
    def tool(self,command,*,passwords=None,require_success=True):
        values=list(map(str,command));self.calls.append((values,passwords))
        if 'badging' in values:return 0,self.badging
        if 'sign' in values:
            Path(values[values.index('--out')+1]).write_bytes(self.args.unsigned_apk.read_bytes());return 0,''
        if 'verify' in values:
            if '--print-certs' not in values:return 1,''
            return 0,'Signer #1 certificate SHA-256 digest: '+self.cert+'\n'
        return 0,''
    def test_passwords_only_reach_stdin_and_same_original_certificate_is_required(self):
        with patch.object(signing,'run',side_effect=self.tool):
            result=signing.sign(self.args,prompt=lambda _: 'FAKE hidden password')
        self.assertTrue(result['same_original_signer']);self.assertFalse(result['device_upgrade_verified'])
        command,passwords=next(pair for pair in self.calls if 'sign' in pair[0])
        self.assertNotIn('FAKE hidden password',json.dumps(command));self.assertEqual(passwords,b'FAKE hidden password\nFAKE hidden password\n')
        self.assertEqual(command[command.index('--ks-pass')+1],'stdin');self.assertEqual(command[command.index('--key-pass')+1],'stdin')
        self.assertTrue(self.args.output_apk.exists())
    def test_wrong_certificate_never_delivers_upgrade_apk(self):
        self.cert='0'*64
        with patch.object(signing,'run',side_effect=self.tool),self.assertRaises(signing.SigningError):
            signing.sign(self.args,prompt=lambda _: 'FAKE wrong signer password')
        self.assertFalse(self.args.output_apk.exists());self.assertFalse(list(self.root.glob('.love-house-sign-*')))
    def test_wrong_hash_or_package_is_rejected_before_password_prompt(self):
        prompt=lambda _:self.fail('Must not request passwords for wrong unsigned input')
        self.args.expected_sha256='0'*64
        with self.assertRaises(signing.SigningError):signing.sign(self.args,prompt=prompt)
        self.args.expected_sha256=hashlib.sha256(self.args.unsigned_apk.read_bytes()).hexdigest();self.badging=self.badging.replace("versionCode='2'","versionCode='1'")
        with patch.object(signing,'run',side_effect=self.tool),self.assertRaises(signing.SigningError):signing.sign(self.args,prompt=prompt)
    def test_existing_output_is_never_overwritten(self):
        self.args.output_apk.write_bytes(b'KEEP existing result')
        with self.assertRaises(signing.SigningError):signing.sign(self.args,prompt=lambda _:self.fail('No prompt'))
        self.assertEqual(self.args.output_apk.read_bytes(),b'KEEP existing result')

if __name__=='__main__':unittest.main()
