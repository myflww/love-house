"""Portable contracts for Windows prerequisite probing and fail-closed repair."""
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "desktop/windows_prerequisites.py"
spec = importlib.util.spec_from_file_location("tested_windows_prerequisites", MODULE)
prerequisites = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prerequisites)


class FakeKey:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRegistry:
    HKEY_CURRENT_USER = 1
    HKEY_LOCAL_MACHINE = 2
    KEY_READ = 16
    KEY_WOW64_64KEY = 256
    KEY_WOW64_32KEY = 512
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self, values):
        self.values = values
        self.calls = []

    def OpenKey(self, hive, path, reserved, access):
        self.calls.append((hive, path, access))
        try:
            return FakeKey(self.values[hive, access & ~self.KEY_READ])
        except KeyError:
            raise FileNotFoundError from None

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError
        return key.values[name]


class PrerequisiteTests(unittest.TestCase):
    def test_registry_requires_effective_string_version_and_checks_both_views(self):
        registry = FakeRegistry({(1, 256): {"pv": ("0.0.0.0", 1)},
                                 (1, 512): {"pv": ("145.0.1.2", 1)},
                                 (2, 256): {"pv": ("999.0.0.0", 4)},
                                 (2, 512): {"pv": ("not a version", 1)}})
        found = prerequisites.registry_runtime_versions(registry)
        self.assertEqual(found, [{"hive": "HKCU", "view": 512, "version": "145.0.1.2"}])
        self.assertEqual(len(registry.calls), 4)

    def test_dotnet_release_boundary_and_missing_key(self):
        for release, ok in ((394801, False), (394802, True)):
            registry = FakeRegistry({(2, 256): {"Release": (release, 4), "Version": ("4.6.2.0", 1)}})
            self.assertIs(prerequisites.dotnet_status(registry)["ok"], ok)
        self.assertFalse(prerequisites.dotnet_status(FakeRegistry({}))["ok"])

    def test_dotnet_selects_highest_valid_release(self):
        registry = FakeRegistry({(2, 256): {"Release": (394801, 4)},
                                 (2, 512): {"Release": (528040, 4)}})
        status = prerequisites.dotnet_status(registry)
        self.assertEqual(status["release"], 528040)
        self.assertTrue(status["ok"])

    def test_registration_alone_never_proves_runtime_usable(self):
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "registry_runtime_versions", return_value=[{"version": "145.0.1.2"}]), \
             mock.patch.object(prerequisites, "_loader_path", return_value=Path("loader.dll")), \
             mock.patch.object(prerequisites, "_loader_version", return_value=(0x80070002, None)):
            status = prerequisites.runtime_status()
        self.assertFalse(status["available"])
        self.assertEqual(status["code"], "runtime_unavailable")

    def test_actual_loader_probe_is_authoritative_without_registration(self):
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "registry_runtime_versions", return_value=[]), \
             mock.patch.object(prerequisites, "_loader_path", return_value=Path("loader.dll")), \
             mock.patch.object(prerequisites, "_loader_version", return_value=(0, "145.0.1.2")):
            self.assertTrue(prerequisites.runtime_status()["available"])

    def test_loader_missing_and_failure_have_separate_safe_codes(self):
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "registry_runtime_versions", return_value=[]), \
             mock.patch.object(prerequisites, "_loader_path", return_value=None):
            self.assertEqual(prerequisites.runtime_status()["code"], "loader_missing")
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "registry_runtime_versions", return_value=[]), \
             mock.patch.object(prerequisites, "_loader_path", return_value=Path("loader.dll")), \
             mock.patch.object(prerequisites, "_loader_version", side_effect=OSError("secret token")):
            status = prerequisites.runtime_status()
        self.assertEqual(status["code"], "loader_load_failed")
        self.assertNotIn("secret", json.dumps(status))

    def test_source_and_frozen_layouts_find_only_known_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loader = root / "_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll"
            loader.parent.mkdir(parents=True)
            loader.write_bytes(b"fake SDK")
            self.assertEqual(prerequisites._loader_path(root), loader)
            with mock.patch.object(prerequisites.sys, "frozen", True, create=True), \
                 mock.patch.object(prerequisites.sys, "_MEIPASS", str(root / "_internal"), create=True):
                self.assertEqual(prerequisites._loader_path(), loader)

    def test_loader_frees_com_allocated_string(self):
        buffer = ctypes.create_unicode_buffer("145.0.1.2")

        def probe(folder, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.cast(buffer, ctypes.c_void_p)
            return 0

        probe_function = mock.Mock(side_effect=probe)
        free = mock.Mock()
        with mock.patch.object(prerequisites.ctypes, "WinDLL", return_value=types.SimpleNamespace(
                GetAvailableCoreWebView2BrowserVersionString=probe_function), create=True), \
             mock.patch.object(prerequisites.ctypes, "OleDLL", return_value=types.SimpleNamespace(CoTaskMemFree=free), create=True):
            self.assertEqual(prerequisites._loader_version(Path("loader.dll")), (0, "145.0.1.2"))
        self.assertEqual(free.call_count, 1)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="love house 中文 ")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.folder = self.root / "resources/runtime"
        self.folder.mkdir(parents=True)
        self.installer = self.folder / prerequisites.INSTALLER_FILENAME
        self.installer.write_bytes(b"fake signed installer fixture")
        self.digest = hashlib.sha256(self.installer.read_bytes()).hexdigest()
        self.pin = mock.patch.object(prerequisites, "INSTALLER_SHA256", self.digest)
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.manifest = {"schema": prerequisites.INSTALLER_SCHEMA,
                         "filename": prerequisites.INSTALLER_FILENAME,
                         "sha256": self.digest, "publisher": "Microsoft Corporation", "architecture": "x64"}
        self.write_manifest()

    def write_manifest(self):
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_hash_and_signature_both_required(self):
        with mock.patch.object(prerequisites, "_authenticode_status", return_value={"verified": True, "code": "ok"}):
            self.assertTrue(prerequisites.bundled_installer_status(self.root)["verified"])
        with mock.patch.object(prerequisites, "_authenticode_status", return_value={"verified": False, "code": "signature_invalid"}):
            self.assertFalse(prerequisites.bundled_installer_status(self.root)["verified"])
        self.installer.write_bytes(b"tampered")
        with mock.patch.object(prerequisites, "_authenticode_status") as signature:
            self.assertEqual(prerequisites.bundled_installer_status(self.root)["code"], "installer_hash_mismatch")
            signature.assert_not_called()

    def test_manifest_cannot_change_pin_or_redirect_execution(self):
        for key, value in (("sha256", "0" * 64), ("filename", "../../other.exe"),
                           ("publisher", "Other Publisher"), ("architecture", "x86")):
            with self.subTest(key=key):
                original = self.manifest[key]
                self.manifest[key] = value
                self.write_manifest()
                with mock.patch.object(prerequisites, "_authenticode_status") as signature:
                    self.assertEqual(prerequisites.bundled_installer_status(self.root)["code"], "manifest_invalid")
                    signature.assert_not_called()
                self.manifest[key] = original

    def test_signature_requires_valid_status_and_exact_microsoft_publisher(self):
        for status, publisher, expected in (("Valid", "Microsoft Corporation", True),
                                            ("NotTrusted", "Microsoft Corporation", False),
                                            ("Valid", "Other Microsoft Corporation", False)):
            with self.subTest(status=status, publisher=publisher), \
                 mock.patch.object(prerequisites.sys, "platform", "win32"), \
                 mock.patch.object(prerequisites, "_powershell_path", return_value=self.installer), \
                 mock.patch.object(prerequisites.subprocess, "run", return_value=types.SimpleNamespace(
                     returncode=0, stdout=json.dumps({"status": status, "publisher": publisher}).encode())) as run:
                self.assertIs(prerequisites._authenticode_status(self.installer)["verified"], expected)
                args, kwargs = run.call_args
                self.assertNotIn(str(self.installer), args[0][-1])
                self.assertEqual(kwargs["env"]["LOVE_HOUSE_SIGNATURE_TARGET"], str(self.installer.resolve()))
                self.assertEqual(kwargs["timeout"], 30)
                self.assertFalse(kwargs.get("shell", False))

    def test_signature_timeout_and_invalid_output_fail_closed(self):
        for side_effect in (subprocess.TimeoutExpired("powershell", 30), OSError("private secret")):
            with mock.patch.object(prerequisites.sys, "platform", "win32"), \
                 mock.patch.object(prerequisites, "_powershell_path", return_value=self.installer), \
                 mock.patch.object(prerequisites.subprocess, "run", side_effect=side_effect):
                status = prerequisites._authenticode_status(self.installer)
                self.assertFalse(status["verified"])
                self.assertNotIn("secret", json.dumps(status))
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "_powershell_path", return_value=self.installer), \
             mock.patch.object(prerequisites.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=b"garbage")):
            self.assertFalse(prerequisites._authenticode_status(self.installer)["verified"])

    def test_repair_never_executes_unverified_installer(self):
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "runtime_status", return_value={"available": False}), \
             mock.patch.object(prerequisites, "bundled_installer_status", return_value={"verified": False, "code": "signature_invalid"}), \
             mock.patch.object(prerequisites.subprocess, "run") as run:
            self.assertFalse(prerequisites.repair_runtime(self.root)["ok"])
            run.assert_not_called()

    def test_repair_requires_success_exit_and_fresh_loader_success(self):
        for exit_code, available, ok in ((0, True, True), (0, False, False),
                                         (1, True, False), (3010, False, False), (3010, True, True)):
            with self.subTest(exit_code=exit_code, available=available), \
                 mock.patch.object(prerequisites.sys, "platform", "win32"), \
                 mock.patch.object(prerequisites, "runtime_status", side_effect=[{"available": False}, {"available": available}]) as status, \
                 mock.patch.object(prerequisites, "bundled_installer_status", return_value={"verified": True, "code": "ok"}), \
                 mock.patch.object(prerequisites.subprocess, "run", return_value=types.SimpleNamespace(returncode=exit_code)) as run:
                result = prerequisites.repair_runtime(self.root)
                self.assertIs(result["ok"], ok)
                self.assertEqual(status.call_count, 2)
                self.assertEqual(run.call_args.args[0], [str(self.installer.resolve()), "/silent", "/install"])
                self.assertEqual(run.call_args.kwargs["timeout"], 180)

    def test_timeout_does_not_claim_success_even_if_installer_child_completed(self):
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "runtime_status", side_effect=[{"available": False}, {"available": True}]), \
             mock.patch.object(prerequisites, "bundled_installer_status", return_value={"verified": True, "code": "ok"}), \
             mock.patch.object(prerequisites.subprocess, "run", side_effect=subprocess.TimeoutExpired("installer", 1)):
            result = prerequisites.repair_runtime(self.root, timeout=1)
        self.assertEqual(result["code"], "repair_timeout")
        self.assertFalse(result["ok"])

    def test_present_runtime_does_not_trigger_installation_without_force(self):
        with mock.patch.object(prerequisites.sys, "platform", "win32"), \
             mock.patch.object(prerequisites, "runtime_status", return_value={"available": True}), \
             mock.patch.object(prerequisites, "bundled_installer_status") as bundle:
            self.assertTrue(prerequisites.repair_runtime(self.root)["ok"])
            bundle.assert_not_called()

    def test_invalid_timeout_rejected_before_side_effects(self):
        with mock.patch.object(prerequisites, "runtime_status") as status:
            for value in (0, -1, 601, True, "180", float("nan")):
                with self.assertRaises(ValueError):
                    prerequisites.repair_runtime(self.root, timeout=value)
            status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
