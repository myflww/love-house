"""Isolated Windows installation metadata fixtures; no real profile or application is run."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("windows_harness_configure", ROOT / "extensions/deepseek-harness/configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


def asar_fixture(path, entries):
    """Chromium pickle header with relative file offsets, like Electron ASAR."""
    header, bodies, offset = {"files": {}}, [], 0
    for name, value in entries.items():
        body = json.dumps(value).encode()
        node = header
        parts = name.split("/")
        for part in parts[:-1]:
            node = node.setdefault("files", {}).setdefault(part, {"files": {}})
        node["files"][parts[-1]] = {"size": len(body), "offset": str(offset)}
        bodies.append(body)
        offset += len(body)
    encoded = json.dumps(header).encode()
    payload = struct.pack("<I", len(encoded)) + encoded
    payload += b"\0" * (-len(payload) % 4)
    header_pickle = struct.pack("<I", len(payload)) + payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<II", 4, len(header_pickle)) + header_pickle + b"".join(bodies))


class WindowsHarnessDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="love-house-win-harness-")
        self.root = Path(self.temporary.name).resolve()
        self.profile = self.root / "fake-profile"
        self.profile.mkdir()
        (self.profile / "cordis.yml").write_text("[]\n")

    def tearDown(self):
        self.temporary.cleanup()

    def app(self, folder="用户 甲/DeepSeek Harness", version="0.2.1-rc.3"):
        directory = self.root / folder
        asar_fixture(directory / "resources/app.asar", {
            "package.json": {"name": "@deepseek-ai/dsh-desktop", "version": version + ".20261030.1"},
            "dsh/node_modules/@deepseek-ai/dsh-agent/package.json": {"name": "@deepseek-ai/dsh-agent", "version": version},
        })
        (directory / "DeepSeek Harness.exe").write_bytes(b"not-an-executable-test-fixture")
        return directory

    def test_explicit_executable_reads_real_asar_layout_and_keeps_runtime_version(self):
        app = self.app()
        before = (app / "resources/app.asar").read_bytes()
        for selected in (app, app / "DeepSeek Harness.exe"):
            detected = configure.detect(str(selected), str(self.profile))
            self.assertTrue(detected["detected"])
            self.assertTrue(detected["supported"])
            self.assertEqual(detected["version"], "0.2.1-rc.3")
            self.assertEqual(detected["app_path"], str(app))
            self.assertIn("dsh-agent/package.json", detected["version_source"])
            self.assertFalse(detected["credentials_read"])
        self.assertEqual((app / "resources/app.asar").read_bytes(), before)

    def test_automatic_windows_standard_path_and_dsh_home_are_discovered(self):
        local = self.root / "Local AppData"
        app = self.app(str(local / "Programs/DeepSeek Harness"))
        home = self.root / "DSH 用户资料"
        profile = home / "profiles/desktop"
        profile.mkdir(parents=True)
        (profile / "cordis.yml").write_text("[]\n")
        with patch.object(configure.sys, "platform", "win32"), patch.object(configure, "_windows_registry_apps", return_value=[]), \
                patch.dict(configure.os.environ, {"LOCALAPPDATA": str(local), "DSH_HOME": str(home)}):
            detected = configure.detect()
        self.assertEqual(detected["app_path"], str(app))
        self.assertEqual(detected["profile_dir"], str(profile))
        self.assertEqual(detected["profile_source"], "DSH_HOME")
        self.assertTrue(detected["supported"])
        self.assertTrue(detected["profile_exists"])

    def test_custom_registry_install_location_is_used(self):
        app = self.app("自选目录/DeepSeek Harness")
        with patch.object(configure.sys, "platform", "win32"), patch.object(configure, "_windows_registry_apps", return_value=[app]):
            detected = configure.detect(profile_dir=self.profile)
        self.assertTrue(detected["supported"])
        self.assertEqual(detected["app_path"], str(app))

    def test_unknown_version_is_detected_but_never_applied(self):
        app = self.app(version="99.0.0-unknown")
        detected = configure.detect(app, self.profile)
        self.assertTrue(detected["detected"])
        self.assertFalse(detected["supported"])
        with self.assertRaisesRegex(ValueError, "尚未实证"):
            configure.configure({"config": {"connection_id": "fake", "connection_token": "fake-token", "library_id": "default"},
                                 "host_options": {"profile_dir": str(self.profile), "app_path": str(app)}}, apply=True)
        self.assertFalse((self.profile / ".neural-knowledge").exists())

    def test_missing_executable_and_malformed_asar_cannot_claim_support(self):
        detected = configure.detect(self.root / "missing.exe", self.profile)
        self.assertFalse(detected["detected"])
        self.assertFalse(detected["supported"])
        empty = self.root / 'not-an-app'
        empty.mkdir()
        self.assertFalse(configure.detect(empty, self.profile)['detected'])
        app = self.app()
        (app / "resources/app.asar").write_bytes(struct.pack("<4I", 4, 0xFFFFFFFF, 0xFFFFFFFB, 0xFFFFFFF0))
        detected = configure.detect(app, self.profile)
        self.assertTrue(detected["detected"])
        self.assertFalse(detected["supported"])
        self.assertIsNone(detected["version"])

    def test_unpacked_windows_runtime_package_is_supported(self):
        app = self.root / "unpacked"
        manifest = app / "resources/app/dsh/package.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "@deepseek-ai/dsh-desktop-runtime", "version": "0.2.1-rc.3"}))
        detected = configure.detect(app, self.profile)
        self.assertTrue(detected["detected"])
        self.assertTrue(detected["supported"])

    def test_source_and_sdk_validated_rc5_is_supported_from_packaged_metadata(self):
        app = self.app(version='0.2.1-rc.5')
        detected = configure.detect(app, self.profile)
        self.assertTrue(detected['detected'])
        self.assertTrue(detected['supported'])
        self.assertEqual(detected['version'],'0.2.1-rc.5')

    def test_python_distribution_receives_the_same_detector(self):
        self.assertEqual((ROOT / "extensions/deepseek-harness/configure.py").read_bytes(),
                         (ROOT / "nkb/service/harness/configure.py").read_bytes())
