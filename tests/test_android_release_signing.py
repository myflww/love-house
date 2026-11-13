"""Original-key handoff gates using inert tools and ZIPs, never a real key."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sign_android_release as signing

SOURCE = "a" * 40
SECRET = "SYNTHETIC hidden password"


def write_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def record(path):
    return {"path": path.name, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class AndroidReleaseSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.tools = self.root / "tools"
        (self.tools / "lib").mkdir(parents=True)
        suffix = ".exe" if signing.os.name == "nt" else ""
        for name in ("aapt" + suffix, "zipalign" + suffix, "lib/apksigner.jar"):
            (self.tools / name).write_bytes(b"SYNTHETIC inert tool")
        self.app = self.root / "release-unsigned.apk"
        self.test = self.root / "debug-androidTest.apk"
        self.source = self.root / "source.zip"
        write_zip(self.app, {"AndroidManifest.xml": b"SYNTHETIC main manifest", "classes.dex": b"SYNTHETIC memory engine"})
        write_zip(self.test, {"AndroidManifest.xml": b"SYNTHETIC QA manifest", "classes.dex": b"SYNTHETIC tests",
                              "META-INF/DEBUG.SF": b"SYNTHETIC prior debug signature"})
        write_zip(self.source, {"nkb/_version.py": b"SYNTHETIC version", "LICENSE": b"SYNTHETIC notice"})
        self.manifest = self.root / "Android-signing-input.json"
        self.value = {"schema": signing.SCHEMA, "source_commit": SOURCE, "application_id": signing.APP_ID,
                      "version_name": "0.10.7rc1", "version_code": 5, "certificate_sha256": signing.ORIGINAL_CERT,
                      "apk": record(self.app), "test_apk": record(self.test), "source_archive": record(self.source)}
        self.write_manifest()
        java = self.root / ("java" + suffix)
        java.write_bytes(b"SYNTHETIC inert executable")
        key = self.root / "original-key-placeholder.jks"
        key.write_bytes(b"SYNTHETIC inert placeholder, no generated or private key")
        self.args = SimpleNamespace(manifest=self.manifest, expected_source_commit=SOURCE,
                                    output_dir=self.root / "fresh-signed", build_tools=self.tools,
                                    expected_version_name="0.10.7rc1", expected_version_code=5,
                                    java=java, keystore=key, alias="existing-synthetic-alias")
        self.calls = []
        self.signed = 0
        self.cert = signing.ORIGINAL_CERT
        self.mutate_payload = False
        self.fail_second = False
        self.app_already_signed = False
        self.wrong_runner = False
        self.wrong_version = False

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.value), encoding="utf-8")

    def tool(self, command, *, passwords=None, require_success=True):
        values = list(map(str, command))
        self.calls.append((values, passwords))
        if "badging" in values:
            path = Path(values[-1])
            qa = path == self.test or path.name == "LoveHouse-0.10.7rc1-Android-QA-ONLY.apk"
            app_id = signing.APP_ID + (".test" if qa else "")
            code, version = ("", "") if qa else ("5", "0.10.7rc1")
            if self.wrong_version and not qa:
                code = "3"
            return 0, f"package: name='{app_id}' versionCode='{code}' versionName='{version}'\nsdkVersion:'26'\ntargetSdkVersion:'36'\n"
        if "xmltree" in values:
            target = "wrong.app" if self.wrong_runner else signing.APP_ID
            return 0, ('  E: instrumentation (line=1)\n'
                       '    A: android:name(0x01010003)="androidx.test.runner.AndroidJUnitRunner"\n'
                       f'    A: android:targetPackage(0x01010021)="{target}"\n')
        if "sign" in values:
            self.signed += 1
            if self.fail_second and self.signed == 2:
                raise signing.SigningError("Synthetic second tool failure")
            source = Path(values[-1])
            target = Path(values[values.index("--out") + 1])
            target.write_bytes(source.read_bytes())
            if self.mutate_payload:
                with zipfile.ZipFile(target, "a") as archive:
                    archive.writestr("SYNTHETIC-INJECTED-CODE.dex", b"modified payload")
            return 0, ""
        if "verify" in values:
            if "--print-certs" in values:
                return 0, "Signer #1 certificate SHA-256 digest: " + self.cert + "\n"
            return (0 if Path(values[-1]) == self.test or self.app_already_signed else 1), ""
        return 0, ""

    def no_prompt(self, _):
        self.fail("Invalid input must fail before requesting a password")

    def sign(self, prompt=lambda _: SECRET):
        with patch.object(signing, "run", side_effect=self.tool):
            return signing.sign(self.args, prompt=prompt)

    def assert_no_delivery(self):
        self.assertFalse(self.args.output_dir.exists())
        self.assertEqual(list(self.root.glob(".love-house-release-sign-*")), [])

    def test_batch_signs_two_distinct_original_cert_inputs_without_password_arguments(self):
        result = self.sign()
        self.assertEqual(self.signed, 2)
        self.assertEqual(set(path.name for path in self.args.output_dir.iterdir()),
                         {"LoveHouse-0.10.7rc1-Android.apk", "LoveHouse-0.10.7rc1-Android-QA-ONLY.apk", signing.REPORT})
        self.assertEqual(result["source_commit"], SOURCE)
        self.assertTrue(result["same_original_signer"])
        self.assertTrue(result["payload_preserved"])
        self.assertFalse(result["device_upgrade_verified"])
        self.assertFalse(result["independent_rebuild_verified"])
        self.assertFalse(result["published"])
        self.assertFalse(result["signed"]["apk"]["qa_only"])
        self.assertTrue(result["signed"]["test_apk"]["qa_only"])
        self.assertEqual(result["signed"]["test_apk"]["identity"]["version_code"], "")
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(str(self.args.keystore), json.dumps(result))
        for command, passwords in self.calls:
            self.assertNotIn(SECRET, json.dumps(command))
            if "sign" in command:
                self.assertEqual(passwords, (SECRET + "\n" + SECRET + "\n").encode())
                self.assertEqual(command[command.index("--ks-pass") + 1], "stdin")
                self.assertEqual(command[command.index("--key-pass") + 1], "stdin")

    def test_wrong_source_or_version_or_original_fingerprint_is_rejected_before_prompt(self):
        for key, replacement in (("source_commit", "b" * 40), ("version_name", "0.8.0rc2"),
                                 ("version_code", True), ("certificate_sha256", "b" * 64),
                                 ("application_id", "another.app"), ("schema", "unknown")):
            original = deepcopy(self.value)
            self.value[key] = replacement
            self.write_manifest()
            with self.subTest(key=key), self.assertRaises(signing.SigningError):
                self.sign(prompt=self.no_prompt)
            self.assert_no_delivery()
            self.value = original
        self.write_manifest()
        self.args.expected_source_commit = "0" * 40
        with self.assertRaises(signing.SigningError):
            self.sign(prompt=self.no_prompt)

    def test_explicit_expected_version_cannot_be_a_path_or_noninteger_code(self):
        for version, code in (('../another-release', 5), ('0.10.7rc1', True), ('0.10.7rc1', 0)):
            self.args.expected_version_name = version
            self.args.expected_version_code = code
            with self.assertRaises(signing.SigningError):
                self.sign(prompt=self.no_prompt)
            self.assert_no_delivery()

    def test_each_frozen_artifact_must_match_size_and_sha_before_prompt(self):
        for name in ("apk", "test_apk", "source_archive"):
            for field, replacement in (("bytes", 1), ("sha256", "0" * 64)):
                old = deepcopy(self.value)
                self.value[name][field] = replacement
                self.write_manifest()
                with self.subTest(name=name, field=field), self.assertRaises(signing.SigningError):
                    self.sign(prompt=self.no_prompt)
                self.value = old
                self.assert_no_delivery()

    def test_private_unknown_metadata_and_repeated_fields_are_rejected(self):
        self.value["password"] = "SYNTHETIC never an accepted manifest field"
        self.write_manifest()
        with self.assertRaises(signing.SigningError):
            self.sign(prompt=self.no_prompt)
        self.value.pop("password")
        self.write_manifest()
        raw = self.manifest.read_text()
        self.manifest.write_text(raw[:-1] + ',"source_commit":"' + SOURCE + '"}')
        with self.assertRaises(signing.SigningError):
            self.sign(prompt=self.no_prompt)

    def test_paths_cannot_escape_handoff_or_reference_a_symbolic_link(self):
        for path in ("../release.apk", "/absolute.apk", "C:/release.apk", "folder\\release.apk", "./release.apk"):
            self.value["apk"]["path"] = path
            self.write_manifest()
            with self.subTest(path=path), self.assertRaises(signing.SigningError):
                self.sign(prompt=self.no_prompt)
        if hasattr(Path, "symlink_to"):
            linked = self.root / "linked.apk"
            try:
                linked.symlink_to(self.app)
            except OSError:
                return
            self.value["apk"]["path"] = linked.name
            self.write_manifest()
            with self.assertRaises(signing.SigningError):
                self.sign(prompt=self.no_prompt)

    def test_already_signed_release_wrong_app_metadata_and_wrong_runner_do_not_prompt(self):
        for flag in ("app_already_signed", "wrong_version", "wrong_runner"):
            setattr(self, flag, True)
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.sign(prompt=self.no_prompt)
            setattr(self, flag, False)
            self.assert_no_delivery()

    def test_wrong_original_certificate_or_modified_payload_never_delivers_either_apk(self):
        self.cert = "b" * 64
        with self.assertRaises(signing.SigningError):
            self.sign()
        self.assert_no_delivery()
        self.cert = signing.ORIGINAL_CERT
        self.mutate_payload = True
        with self.assertRaises(signing.SigningError):
            self.sign()
        self.assert_no_delivery()

    def test_second_signing_failure_does_not_leave_a_half_verified_release(self):
        self.fail_second = True
        with self.assertRaises(signing.SigningError):
            self.sign()
        self.assertEqual(self.signed, 2)
        self.assert_no_delivery()

    def test_artifact_replacement_during_hidden_password_entry_is_rejected(self):
        def replace_input(_):
            self.source.write_bytes(b"SYNTHETIC altered after input validation")
            return SECRET
        with self.assertRaises(signing.SigningError):
            self.sign(prompt=replace_input)
        self.assert_no_delivery()

    def test_manifest_replacement_during_hidden_password_entry_is_rejected(self):
        def replace_manifest(_):
            self.manifest.write_text(self.manifest.read_text() + " ")
            return SECRET
        with self.assertRaises(signing.SigningError):
            self.sign(prompt=replace_manifest)
        self.assert_no_delivery()

    def test_existing_handoff_and_incomplete_password_input_cannot_be_overwritten(self):
        self.args.output_dir.mkdir()
        keep = self.args.output_dir / "KEEP"
        keep.write_bytes(b"Existing handoff")
        with self.assertRaises(signing.SigningError):
            self.sign(prompt=self.no_prompt)
        self.assertEqual(keep.read_bytes(), b"Existing handoff")
        keep.unlink()
        self.args.output_dir.rmdir()
        for password in ("", "line\nbreak", "null\0byte"):
            with self.subTest(password=password), self.assertRaises(signing.SigningError):
                self.sign(prompt=lambda _: password)
            self.assert_no_delivery()

    def test_payload_comparison_keeps_everything_except_specific_signature_entries(self):
        baseline = signing.archive_payload(self.app)
        with zipfile.ZipFile(self.app, "a") as archive:
            archive.writestr("META-INF/MANIFEST.MF", b"SYNTHETIC signature manifest")
            archive.writestr("META-INF/CERT.RSA", b"SYNTHETIC public signature")
            archive.writestr("META-INF/CERT.SF", b"SYNTHETIC signature metadata")
        self.assertEqual(signing.archive_payload(self.app), baseline)
        with zipfile.ZipFile(self.app, "a") as archive:
            archive.writestr("META-INF/runtime.version", b"SYNTHETIC runtime metadata must remain")
        self.assertNotEqual(signing.archive_payload(self.app), baseline)
        malicious = self.root / "bad.zip"
        write_zip(malicious, {"../private": b"SYNTHETIC"})
        with self.assertRaises(signing.SigningError):
            signing.archive_payload(malicious, apk=False)


if __name__ == "__main__":
    unittest.main()
