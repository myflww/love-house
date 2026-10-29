"""Consumer startup regressions, with isolated fake data and no model or keys."""
from __future__ import annotations

import errno
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
sys.path.insert(0, str(ROOT))
import windows_diagnostics as diagnostics
import windows_prerequisites as prerequisites


def load_windows():
    spec = importlib.util.spec_from_file_location("love_house_startup_shell", ROOT / "desktop/windows_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windows = load_windows()


class SafeStartupDiagnosticsTests(unittest.TestCase):
    def test_unwritable_data_log_falls_back_and_reports_its_actual_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "not-a-directory"
            blocked.write_text("FAKE owned test fixture", encoding="utf-8")
            fallback = root / "temp"
            log = diagnostics.StartupLog(blocked / "logs/startup.log")
            with patch.object(diagnostics.tempfile, "gettempdir", return_value=str(fallback)):
                result = log.write("failure", **diagnostics.failure_record(PermissionError(13, "FAKE secret")))
            self.assertIsNotNone(result)
            self.assertTrue(log.path.is_relative_to(fallback))
            self.assertIn('"type": "PermissionError"', log.tail()[0])
            self.assertNotIn("FAKE secret", log.path.read_text("utf-8"))
            self.assertEqual(blocked.read_text("utf-8"), "FAKE owned test fixture")

    def test_neither_log_location_writable_does_not_replace_original_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "file"
            blocker.write_bytes(b"FAKE fixture")
            log = diagnostics.StartupLog(blocker / "startup.log")
            with patch.object(diagnostics.tempfile, "gettempdir", return_value=str(blocker)):
                self.assertIsNone(log.write("failure", type="PermissionError"))
            self.assertEqual(log.tail(), [])
            self.assertEqual(blocker.read_bytes(), b"FAKE fixture")

    def test_failure_record_excludes_user_filename_message_and_environment_values(self):
        private = "FAKE_CHAT_API_KEY_MUST_NOT_LEAK"
        try:
            raise PermissionError(errno.EACCES, private, "C:/FAKE-user/" + private + ".json")
        except PermissionError as exc:
            record = diagnostics.failure_record(exc)
        text = json.dumps(record)
        self.assertNotIn(private, text)
        self.assertNotIn("FAKE-user", text)
        self.assertNotIn("file", record)
        self.assertEqual(record["kind"], "data_directory_unwritable")
        self.assertEqual(record["errno"], errno.EACCES)
        self.assertTrue(record["at"]["file"].endswith("test_windows_startup_regressions.py"))
        self.assertFalse(Path(record["at"]["file"]).is_absolute())

    def test_classification_does_not_infer_runtime_from_arbitrary_error_text(self):
        cases = [
            (diagnostics.AlreadyRunning(), "already_running"),
            (diagnostics.WebView2Unavailable({}), "webview2_unavailable"),
            (diagnostics.DotNetUnavailable({}), "dotnet_unavailable"),
            (diagnostics.NativeStartupTimeout(), "webview2_initialization_timeout"),
            (ModuleNotFoundError("FAKE missing DLL"), "packaged_dependency_missing"),
            (OSError(errno.ENOSPC, "FAKE disk full"), "storage_failure"),
            (ValueError("WebView2 .NET CLR FAKE secret"), "unexpected"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(diagnostics.classify(error), expected)
        clr_error = type("InitializationException", (Exception,), {"__module__": "System.Runtime", "HResult": -2146232576})
        record = diagnostics.failure_record(clr_error("FAKE unsafe CLR exception details"))
        self.assertEqual(record["kind"], "clr_initialization_failed")
        self.assertIsInstance(record["hresult"], int)
        self.assertNotIn("unsafe", json.dumps(record))

    def test_diagnostics_uses_actual_loader_result_instead_of_residual_registry(self):
        missing = {"available": False, "version": None, "source": "loader", "code": "runtime_unavailable"}
        stale = {"available": True, "version": "120.0.0.0", "registry_hits": 1}
        with patch.object(prerequisites, "runtime_status", return_value=missing), \
             patch.object(prerequisites, "dotnet_status", return_value={"ok": True, "release": 533509}), \
             patch.object(diagnostics, "webview2_status", return_value=stale):
            facts = diagnostics.startup_facts()
        self.assertEqual(facts["webview2"], missing)
        self.assertEqual(facts["webview2_discovery"], stale)
        # This assertion exercises Windows wording even on Linux CI. Native
        # non-Windows reports correctly say that WebView2 is not applicable.
        with patch.object(diagnostics.sys, "platform", "win32"):
            self.assertIn("runtime_unavailable", diagnostics.diagnostic_report(facts))

    def test_unversioned_or_old_runtime_files_do_not_count_as_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in ("not-a-version", "0.0.0.0", "7.0.0.0"):
                executable = root / "Microsoft/EdgeWebView/Application" / version / "msedgewebview2.exe"
                executable.parent.mkdir(parents=True)
                executable.write_bytes(b"FAKE runtime")
            self.assertEqual(diagnostics.file_channels({"LOCALAPPDATA": str(root)}), [])

    def test_frozen_relative_traceback_maps_only_known_code_and_keeps_error_location(self):
        def failure(filename):
            namespace = {}
            exec(compile("def fail():\n    raise ValueError('FAKE private error details')\n", filename, "exec"), namespace)
            try:
                namespace["fail"]()
            except ValueError as exc:
                return diagnostics.failure_record(exc)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(diagnostics.sys, "frozen", True, create=True), \
             patch.object(diagnostics.sys, "_MEIPASS", directory, create=True):
            for filename in ("desktop/windows_app.py", "desktop\\windows_app.py", "windows_diagnostics.py"):
                with self.subTest(filename=filename):
                    record = failure(filename)
                    self.assertEqual(record["at"]["file"], "desktop/" + filename.replace("\\", "/").split("/")[-1])
                    self.assertEqual(record["at"]["function"], "fail")
                    self.assertEqual(record["at"]["line"], 2)
                    self.assertNotIn("private", json.dumps(record))
            mapped = SimpleNamespace(__file__=str(Path(directory) / "nkb/service/_startup_fixture.py"))
            with patch.dict(sys.modules, {"nkb.service._startup_fixture": mapped}):
                self.assertEqual(failure("nkb/service/_startup_fixture.py")["at"]["file"], "nkb/service/_startup_fixture.py")
            for filename in ("../desktop/windows_app.py", "nkb/FAKE_private_document.py", "FAKE_private_document.py", str(Path(directory) / "private.py")):
                with self.subTest(rejected=filename):
                    self.assertNotIn("at", failure(filename))


class ControllerStartupRegressionTests(unittest.TestCase):
    def test_second_instance_cleanup_preserves_first_writer_health_and_ready(self):
        with tempfile.TemporaryDirectory(prefix="love-house-writer-test-") as directory:
            first = windows.ControllerRuntime(directory, testing=True).start()
            try:
                original = first.ready.read_bytes()
                second = windows.ControllerRuntime(directory, testing=True)
                with self.assertRaises(windows.AlreadyRunning):
                    second.start()
                second.stop()
                self.assertEqual(first.ready.read_bytes(), original)
                with urlopen(first.url + "api/health", timeout=5) as response:
                    self.assertTrue(json.load(response)["ok"])
                self.assertTrue(first.thread.is_alive())
            finally:
                first.stop()
            self.assertFalse(first.ready.exists())
            restarted = windows.ControllerRuntime(directory, testing=True).start()
            restarted.stop()

    def test_cleanup_before_service_thread_start_never_calls_blocking_shutdown(self):
        with tempfile.TemporaryDirectory(prefix="love-house-start-test-") as directory:
            runtime = windows.ControllerRuntime(directory, testing=True)
            runtime.lock.acquire()
            server = MagicMock()
            runtime.server = server
            runtime.thread = threading.Thread(target=lambda: None)
            runtime.stop()
            server.shutdown.assert_not_called()
            server.server_close.assert_called_once()
            self.assertIsNone(runtime.lock.file)

    def test_thread_start_failure_closes_socket_and_releases_writer(self):
        with tempfile.TemporaryDirectory(prefix="love-house-start-test-") as directory:
            runtime = windows.ControllerRuntime(directory, testing=True)
            host = MagicMock()
            host.manager.demo_suppressed = True
            server = MagicMock()
            server.server_port = 12345
            thread = MagicMock()
            thread.start.side_effect = RuntimeError("FAKE thread unavailable")
            thread.is_alive.return_value = False
            thread.ident = None
            with patch.object(windows, "MemoryHost", return_value=host), \
                 patch.object(windows, "ThreadingHTTPServer", return_value=server), \
                 patch.object(windows.threading, "Thread", return_value=thread):
                with self.assertRaises(RuntimeError):
                    runtime.start()
            server.shutdown.assert_not_called()
            server.server_close.assert_called_once()
            host.stop.assert_called_once()
            self.assertIsNone(runtime.lock.file)
            reacquired = windows.DesktopLock(Path(directory) / ".desktop-writer.lock")
            reacquired.acquire()
            reacquired.release()

    def test_lock_disk_failure_is_not_reported_as_another_running_instance(self):
        if sys.platform != "win32":
            self.skipTest("Windows msvcrt lock path")
        import msvcrt
        with tempfile.TemporaryDirectory() as directory:
            lock = windows.DesktopLock(Path(directory) / "writer.lock")
            with patch.object(msvcrt, "locking", side_effect=OSError(errno.EIO, "FAKE disk error")):
                with self.assertRaises(OSError) as caught:
                    lock.acquire()
            self.assertNotIsInstance(caught.exception, windows.AlreadyRunning)
            self.assertEqual(caught.exception.errno, errno.EIO)

    def test_foreign_python_clr_browser_environment_does_not_reach_native_child(self):
        environment = {"PYTHONHOME": "FAKE_PRIVATE_HOME", "PYTHONPATH": "FAKE_PRIVATE_PATH",
                       "PYTHONNET_RUNTIME": "FAKE_bad_runtime", "PYTHONNET_CORECLR_RUNTIME_CONFIG": "FAKE_private_json",
                       "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER": "FAKE_wrong_browser",
                       "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--FAKE-secret",
                       "PYWEBVIEW_GUI": "FAKE_legacy_gui", "LOCALAPPDATA": "FAKE_data_dir",
                       "PATH": "FAKE_system_path", "LOVE_HOUSE_UNRELATED": "FAKE_keep"}
        with patch.dict(os.environ, environment, clear=True):
            removed = windows.sanitize_native_environment()
            self.assertEqual(dict(os.environ), {k: environment[k] for k in ("LOCALAPPDATA", "PATH", "LOVE_HOUSE_UNRELATED")})
        self.assertEqual(set(removed), set(environment) - {"LOCALAPPDATA", "PATH", "LOVE_HOUSE_UNRELATED"})
        self.assertNotIn("FAKE", json.dumps(removed))


class Signal:
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self

    def fire(self, *arguments):
        for callback in self.callbacks:
            callback(*arguments)


class NativeInitializationRegressionTests(unittest.TestCase):
    def test_explicit_repair_reinstalls_even_when_version_probe_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'repair.json'
            with patch.object(sys, 'argv', ['LoveHouse.exe', '--repair-runtime', '--report', str(report), '--data-dir', directory]), \
                 patch.object(windows, 'repair_runtime', return_value={'ok': True, 'code': 'repaired'}) as repair:
                self.assertEqual(windows.main(), 0)
            repair.assert_called_once_with(force=True)
            self.assertTrue(json.loads(report.read_text('utf-8'))['process_complete'])

    def fake_window(self):
        window = MagicMock()
        window.events = SimpleNamespace(loaded=Signal(), initialized=Signal(), closed=Signal())
        return window

    def test_async_webview_initialization_failure_is_bounded_and_releases_controller(self):
        destroyed = threading.Event()
        window = self.fake_window()
        window.destroy.side_effect = destroyed.set
        browser = SimpleNamespace(settings={}, create_window=MagicMock(return_value=window))
        def gui_loop(**arguments):
            self.assertTrue(destroyed.wait(3), "Startup watchdog did not close the uninitialized window")
        browser.start = gui_loop
        class ExpiredStartup:
            def set(self):
                pass
            def wait(self, timeout):
                return False
        threads = SimpleNamespace(Event=ExpiredStartup, Thread=threading.Thread, Lock=threading.Lock)
        controller = MagicMock()
        controller.start.return_value = controller
        controller.url = "http://127.0.0.1:12345/"
        result = {}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(windows, "threading", threads), \
             patch.object(windows, "ControllerRuntime", return_value=controller), \
             patch.object(windows, "dotnet_status", return_value={"ok": True}), \
             patch.object(windows, "runtime_status", return_value={"available": True, "code": "ok"}), \
             patch.dict(sys.modules, {"webview": browser}):
            with self.assertRaises(windows.NativeStartupTimeout):
                windows.run_window(directory, result=result)
        self.assertTrue(result["startup_timeout"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["controller_stopped"])
        self.assertFalse(result["process_complete"])
        window.destroy.assert_called_once()
        controller.stop.assert_called_once()

    def test_loaded_event_completes_startup_without_watchdog_destroy(self):
        window = self.fake_window()
        browser = SimpleNamespace(settings={}, create_window=MagicMock(return_value=window))
        browser.start = lambda **arguments: window.events.loaded.fire()
        controller = MagicMock()
        controller.start.return_value = controller
        controller.url = "http://127.0.0.1:12345/"
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(windows, "ControllerRuntime", return_value=controller), \
             patch.object(windows, "dotnet_status", return_value={"ok": True}), \
             patch.object(windows, "runtime_status", return_value={"available": True, "code": "ok"}), \
             patch.dict(sys.modules, {"webview": browser}):
            result = windows.run_window(directory)
        self.assertTrue(result["ok"])
        self.assertTrue(result["controller_stopped"])
        window.destroy.assert_not_called()
        controller.stop.assert_called_once()

    def test_existing_writer_is_reported_before_any_renderer_or_framework_probe(self):
        controller = MagicMock()
        controller.start.side_effect = windows.AlreadyRunning()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(windows, "ControllerRuntime", return_value=controller), \
             patch.object(windows, "dotnet_status") as framework, \
             patch.object(windows, "runtime_status") as runtime:
            with self.assertRaises(windows.AlreadyRunning):
                windows.run_window(directory)
        framework.assert_not_called()
        runtime.assert_not_called()
        controller.stop.assert_not_called()

    def test_portable_runtime_repair_requires_consent_and_failure_cannot_launch_again(self):
        for consent in (False, True):
            with self.subTest(consent=consent), tempfile.TemporaryDirectory() as directory:
                with patch.object(sys, "argv", ["LoveHouse.exe", "--data-dir", directory]), \
                     patch.object(windows.sys, "platform", "win32"), \
                     patch.object(windows, "run_window", side_effect=windows.WebView2Unavailable({"available": False})), \
                     patch.object(windows, "bundled_installer_status", return_value={"verified": True}), \
                     patch.object(windows, "ask_yes_no", return_value=consent), \
                     patch.object(windows, "repair_runtime", return_value={"ok": False, "code": "repair_not_available"}) as repair, \
                     patch.object(windows, "notify"), \
                     patch.object(windows, "open_target") as opened:
                    self.assertEqual(windows.main(), 1)
                self.assertEqual(repair.call_count, int(consent))
                opened.assert_not_called()
                log = (Path(directory) / "logs/startup.log").read_text("utf-8")
                if consent:
                    self.assertIn("repair_not_available", log)


if __name__ == "__main__":
    unittest.main()
