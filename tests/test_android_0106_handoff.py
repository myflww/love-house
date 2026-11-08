"""Frozen source / developer APK handoff checks, with synthetic Git repositories."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_android_0106_handoff as handoff


def apk(path, payload):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"SYNTHETIC inert manifest")
        archive.writestr("classes.dex", payload)


@unittest.skipUnless(shutil.which("git"), "Local Git is required for frozen source verification")
class Android0106HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.app = self.base / "app-release-unsigned.apk"
        self.test = self.base / "app-debug-androidTest.apk"
        apk(self.app, b"SYNTHETIC reviewed engine")
        apk(self.test, b"SYNTHETIC independent test code")
        for relative in handoff.COPY_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("SYNTHETIC reviewed helper or notice\n", encoding="utf-8")
        (self.root / "LICENSE").write_text("# PolyForm Noncommercial License 1.0.0\nSYNTHETIC licence fixture\n")
        (self.root / "README.md").write_text("# SYNTHETIC Android source\n原文资料只在临时测试中。\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("# SYNTHETIC project\n")
        (self.root / ".gitignore").write_text("build/\noutputs/\nandroid/app/build/\nnkb/ignored-source.json\n")
        (self.root / "nkb").mkdir()
        (self.root / "nkb/_version.py").write_text("__version__ = '0.10.6rc1'\n")
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic Handoff QA")
        self.git("config", "user.email", "synthetic-handoff@example.invalid")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True,
                                       encoding="utf-8", stderr=subprocess.DEVNULL).strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic frozen source")
        self.commit_id = self.git("rev-parse", "HEAD")

    def prepare(self, output="handoff", **kwargs):
        return handoff.prepare(self.root, self.app, self.test, self.base / output,
                               expected_source=kwargs.pop("expected_source", self.commit_id), **kwargs)

    def assert_no_output(self, output="handoff"):
        self.assertFalse((self.base / output).exists())
        self.assertEqual(list(self.base.glob(".android-0106-handoff-*")), [])

    def test_clean_snapshot_manifest_checksums_and_expected_apks_are_packaged(self):
        # Ignored build outputs and developer caches are not public source.
        ignored = self.root / "android/app/build/generated/enginePython/personal.json"
        ignored.parent.mkdir(parents=True)
        ignored.write_text('{"SYNTHETIC":"generated, must never enter source.zip"}')
        result = self.prepare()
        output = self.base / "handoff"
        self.assertTrue(result["ok"])
        self.assertFalse(result["original_key_signed"])
        self.assertFalse(result["device_upgrade_verified"])
        self.assertFalse(result["published"])
        self.assertNotIn(str(self.base), json.dumps(result))
        manifest = json.loads((output / handoff.INPUT_MANIFEST).read_text())
        self.assertEqual(manifest["source_commit"], self.commit_id)
        self.assertEqual(manifest["version_code"], 4)
        self.assertEqual(manifest["certificate_sha256"], handoff.ORIGINAL_CERT)
        self.assertEqual((output / manifest["apk"]["path"]).read_bytes(), self.app.read_bytes())
        self.assertEqual((output / manifest["test_apk"]["path"]).read_bytes(), self.test.read_bytes())
        handoff.load_manifest(output / handoff.INPUT_MANIFEST, self.commit_id)
        with zipfile.ZipFile(output / handoff.SOURCE_NAME) as archive:
            names = archive.namelist()
            self.assertIn("PUBLIC_SOURCE_MANIFEST.json", names)
            self.assertIn("nkb/_version.py", names)
            self.assertFalse(any(part in {".git", "build", "outputs", "__pycache__"}
                                 for name in names for part in name.split("/")))
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
            public_manifest = json.loads(archive.read("PUBLIC_SOURCE_MANIFEST.json"))
            for item in public_manifest["files"]:
                data = archive.read(item["path"])
                self.assertEqual(item["bytes"], len(data))
                self.assertEqual(item["sha256"], hashlib.sha256(data).hexdigest())
        lines = (output / "SHA256SUMS.txt").read_text().splitlines()
        for line in lines:
            expected, relative = line.split("  ", 1)
            self.assertEqual(handoff.digest(output / relative), expected)
        self.assertEqual(len(lines), len([p for p in output.rglob("*") if p.is_file()]) - 1)

    def test_source_zip_is_deterministic_for_the_same_frozen_source(self):
        first = self.prepare("first")
        second = self.prepare("second")
        self.assertEqual(first["source_commit"], second["source_commit"])
        self.assertEqual((self.base / "first" / handoff.SOURCE_NAME).read_bytes(),
                         (self.base / "second" / handoff.SOURCE_NAME).read_bytes())

    def test_tracked_public_changes_or_untracked_public_files_fail_before_delivery(self):
        version = self.root / "nkb/_version.py"
        original = version.read_bytes()
        version.write_text("# SYNTHETIC uncommitted change\n")
        with self.assertRaises(handoff.HandoffError):
            self.prepare()
        self.assert_no_output()
        version.write_bytes(original)
        untracked = self.root / "nkb/untracked.py"
        untracked.write_text("# SYNTHETIC unreviewed source\n")
        with self.assertRaises(handoff.HandoffError):
            self.prepare()
        self.assert_no_output()

    def test_ignored_but_allowlisted_source_is_not_silently_included(self):
        (self.root / "nkb/ignored-source.json").write_text('{"SYNTHETIC":"ignored public-looking source"}')
        with self.assertRaises(handoff.HandoffError):
            self.prepare()
        self.assert_no_output()

    def test_wrong_expected_commit_existing_output_and_symlink_inputs_are_rejected(self):
        with self.assertRaises(handoff.HandoffError):
            self.prepare(expected_source="0" * 40)
        self.assert_no_output()
        output = self.base / "handoff"
        output.mkdir()
        keep = output / "KEEP"
        keep.write_bytes(b"Do not replace this previous handoff")
        with self.assertRaises(handoff.HandoffError):
            self.prepare()
        self.assertEqual(keep.read_bytes(), b"Do not replace this previous handoff")
        linked = self.base / "linked.apk"
        try:
            linked.symlink_to(self.app)
        except OSError:
            return
        with self.assertRaises(handoff.HandoffError):
            handoff.prepare(self.root, linked, self.test, self.base / "other")
        self.assert_no_output("other")

    def test_secret_scanner_failure_or_source_symlink_has_no_partial_handoff(self):
        secret = self.root / "nkb/private-value.py"
        secret.write_text("value = 'sk-" + "syntheticprivatecredential" * 2 + "'\n")
        self.commit()
        with self.assertRaises(handoff.HandoffError):
            self.prepare()
        self.assert_no_output()
        secret.unlink()
        self.commit()
        linked = self.root / "nkb/linked.py"
        try:
            linked.symlink_to(self.root / "NOTICE")
        except OSError:
            return
        self.commit()
        with self.assertRaises(handoff.HandoffError):
            self.prepare()
        self.assert_no_output()

    def test_malformed_duplicate_zip_and_identical_apk_inputs_fail_closed(self):
        original = self.app.read_bytes()
        self.app.write_bytes(b"SYNTHETIC not an APK")
        with self.assertRaises(zipfile.BadZipFile):
            self.prepare()
        self.assert_no_output()
        self.app.write_bytes(original)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.app, "a") as archive:
                archive.writestr("classes.dex", b"SYNTHETIC ambiguous second entry")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assert_no_output()
        self.app.write_bytes(self.test.read_bytes())
        with self.assertRaises(handoff.HandoffError):
            self.prepare()
        self.assert_no_output()

    def test_source_edits_during_export_are_detected_and_staging_is_removed(self):
        original_prepare = handoff.public.prepare
        def mutate_after_export(source, destination):
            result = original_prepare(source, destination)
            (self.root / "nkb/_version.py").write_text("# SYNTHETIC concurrent source edit\n")
            return result
        with patch.object(handoff.public, "prepare", side_effect=mutate_after_export):
            with self.assertRaises(handoff.HandoffError):
                self.prepare()
        self.assert_no_output()

    def test_stale_existing_public_manifest_is_regenerated_not_copied(self):
        (self.root / "PUBLIC_SOURCE_MANIFEST.json").write_text('{"schema":"SYNTHETIC stale old index"}')
        self.commit()
        self.prepare()
        with zipfile.ZipFile(self.base / "handoff" / handoff.SOURCE_NAME) as archive:
            manifest = json.loads(archive.read("PUBLIC_SOURCE_MANIFEST.json"))
        self.assertEqual(manifest["schema"], "love-house-public-source/v1")
        self.assertGreater(len(manifest["files"]), 1)


if __name__ == "__main__":
    unittest.main()
