from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from nkb.errors import ValidationError
from nkb.service.updates import (API_URL, MAX_BYTES, UpdateChecker, fetch_releases,
                                 repository_url, select_release, version_key)


def release(tag="v0.6.0", *, target="macOS-arm64", preview=False, draft=False, suffix="zip"):
    name = f"LoveHouse-{tag[1:]}-{target}.{suffix}"
    return {"tag_name": tag, "prerelease": preview, "draft": draft, "name": "爱之屋 " + tag,
            "body": "版本说明\n<script>plain text only</script>", "published_at": "2026-10-30T01:00:00Z",
            "html_url": "https://github.com/myflww/love-house/releases/tag/" + tag,
            "assets": [{"state": "uploaded", "name": name,
                        "browser_download_url": "https://github.com/myflww/love-house/releases/download/" + tag + "/" + name}]}


class ReleaseSelectionTests(unittest.TestCase):
    def test_semver_compares_numeric_parts_and_prereleases(self):
        self.assertGreater(version_key("v0.10.0"), version_key("0.9.99"))
        self.assertGreater(version_key("0.6.0"), version_key("0.6.0-rc.100"))
        self.assertGreater(version_key("0.6.0-rc.10"), version_key("0.6.0-rc.2"))
        self.assertGreater(version_key("0.6.0-rc"), version_key("0.6.0-9"))
        self.assertEqual(version_key("0.6.0+mac.1"), version_key("v0.6.0+mac.2"))
        self.assertLess(version_key("v0.5.1rc1"), version_key("0.5.1"))
        self.assertEqual(version_key("v0.5.1rc1"), version_key("0.5.1-rc.1"))
        self.assertLess(version_key("0.5.1alpha2"), version_key("0.5.1beta1"))
        self.assertLess(version_key("0.5.1b2"), version_key("0.5.1rc1"))
        for invalid in (None, "", "vlatest", "0.6", "01.0.0", "0.6.0-01", "0.6.0-rc..1", "a" * 101):
            self.assertIsNone(version_key(invalid))

    def test_windows_only_rc_and_newer_wrong_arch_are_never_mac_updates(self):
        rows = [release("v0.7.0-rc.1", target="Windows-x64", preview=True),
                release("v0.6.9", target="macOS-x64"), release("v0.6.0")]
        selected, other = select_release(rows, "macos", "arm64", "preview")
        self.assertEqual(selected["version"], "0.6.0")
        self.assertEqual(other, "v0.7.0-rc.1")
        stable, other = select_release(rows, "macos", "arm64")
        self.assertEqual(stable["version"], "0.6.0")
        self.assertEqual(other, "v0.6.9")

    def test_release_channel_drafts_and_asset_architecture_are_filtered(self):
        rows = [release("v9.0.0", draft=True), release("v0.8.0-rc.1", preview=True), release("v0.7.0")]
        self.assertEqual(select_release(rows, "macos", "arm64")[0]["version"], "0.7.0")
        self.assertEqual(select_release(rows, "macos", "arm64", "preview")[0]["version"], "0.8.0-rc.1")
        windows = release(target="Windows-x64", suffix="exe")
        self.assertIsNotNone(select_release([windows], "windows", "x64")[0])
        self.assertIsNone(select_release([windows], "windows", "arm64")[0])
        self.assertIsNotNone(select_release([release(target="macOS-universal")], "macos", "arm64")[0])
        self.assertIsNone(select_release([release(target="macOS")], "macos", "arm64")[0])

    def test_existing_python_style_windows_rc_is_supported_only_in_matching_channel_and_platform(self):
        rows = [release("v0.5.1rc1", target="Windows-x64", preview=True)]
        self.assertEqual(select_release(rows, "windows", "x64", "preview")[0]["version"], "0.5.1rc1")
        self.assertIsNone(select_release(rows, "windows", "x64", "stable")[0])
        self.assertIsNone(select_release(rows, "macos", "arm64", "preview")[0])

    def test_only_public_repo_links_and_usable_installers_are_returned(self):
        row = release()
        row["assets"].insert(0, {"name": "LoveHouse-macOS-arm64.zip.sha256", "browser_download_url": "https://evil.example/steal"})
        self.assertEqual(select_release([row], "macos", "arm64")[0]["asset_name"], row["assets"][1]["name"])
        for url in ("https://github.com.evil.example/myflww/love-house/releases/tag/v1.0.0",
                    "https://user@github.com/myflww/love-house/releases/tag/v1.0.0",
                    "http://github.com/myflww/love-house/releases/tag/v1.0.0",
                    "https://github.com/myflww/other/releases/tag/v1.0.0",
                    "https://github.com/myflww/love-house/releases/tag/v1.0.0?token=bad",
                    "https://github.com/myflww/love-house/releases/tag/../../other",
                    "https://github.com/myflww/love-house/releases/tag/%2e%2e/other",
                    "https://github.com/myflww/love-house/releases/tag/%0aheader"):
            self.assertEqual(repository_url(url, "release"), "")
        row["assets"][1]["browser_download_url"] = "https://evil.example/binary.exe"
        self.assertIsNone(select_release([row], "macos", "arm64")[0])


class UpdateCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 100000.0
        self.calls = []
        self.rows = [release()]
        self.instances = []

    def tearDown(self):
        for instance in self.instances:
            instance.stop()
        self.temp.cleanup()

    def transport(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.rows

    def checker(self, **kwargs):
        options = dict(version="0.5.0", system="Darwin", machine="arm64", transport=self.transport, clock=lambda: self.now)
        options.update(kwargs)
        result = UpdateChecker(self.root, **options)
        self.instances.append(result)
        return result

    def test_constructor_never_contacts_network_and_first_check_is_platform_specific(self):
        checker = self.checker()
        self.assertEqual(self.calls, [])
        self.assertEqual(checker.status()["status"], "not_checked")
        result = checker.check()
        self.assertEqual(self.calls, [(API_URL, {"timeout": 5, "max_bytes": MAX_BYTES})])
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["available"])
        self.assertFalse(result["auto_install"])
        self.assertEqual(result["current_version"], "0.5.0")
        self.assertEqual(result["platform"], "macos")
        self.assertNotIn("library", json.dumps(self.calls))

    def test_same_or_older_compatible_release_does_not_offer_a_downgrade(self):
        result = self.checker(version="0.6.0").check()
        self.assertEqual(result["status"], "up_to_date")
        self.assertFalse(result["available"])
        self.assertFalse(self.checker(version="0.7.0-rc.1").status()["available"])

    def test_manual_rate_limit_and_daily_automatic_cache_survive_restart(self):
        checker = self.checker()
        checker.check()
        checker.check()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(checker.status()["retry_after"], 60)
        self.now += 60
        checker.check()
        self.assertEqual(len(self.calls), 2)
        second = self.checker()
        self.assertEqual(second.status()["release"]["version"], "0.6.0")
        second.check(manual=False)
        self.assertEqual(len(self.calls), 2)
        self.now += 86400
        second.check(manual=False)
        self.assertEqual(len(self.calls), 3)

    def test_offline_preserves_cached_release_and_uses_retry_interval(self):
        checker = self.checker()
        checker.check()
        self.now += 86400
        checker.transport = lambda *a, **k: (_ for _ in ()).throw(OSError("SECRET_FAKE_PATH must not escape"))
        result = checker.check(manual=False)
        self.assertEqual(result["status"], "offline")
        self.assertTrue(result["cached"])
        self.assertTrue(result["available"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(self.checker().status()["status"], "offline")
        calls = []
        checker.transport = lambda *a, **k: calls.append(1) or self.rows
        self.now += 899
        checker.check(manual=False)
        self.assertEqual(calls, [])
        self.now += 1
        self.assertEqual(checker.check(manual=False)["status"], "available")

    def test_auto_check_can_be_disabled_persistently_but_manual_still_works(self):
        checker = self.checker()
        checker.settings({"auto_check": False})
        checker.check(manual=False)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.checker().status()["settings"]["auto_check"])
        self.assertTrue(checker.check()["available"])
        for bad in ({"url": "https://evil.example"}, {"auto_check": "yes"}, {"channel": "nightly"}):
            with self.assertRaises(ValidationError):
                checker.settings(bad)

    def test_failed_setting_write_is_reported_instead_of_claiming_auto_check_was_disabled(self):
        checker = self.checker()
        with patch.object(checker.storage, "save", side_effect=OSError("FAKE private path")):
            with self.assertRaisesRegex(ValidationError, "原设置已保留"):
                checker.settings({"auto_check": False})
        self.assertTrue(checker.status()["settings"]["auto_check"])

    def test_request_is_async_and_inflight_requests_are_coalesced(self):
        entered, unblock = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            self.calls.append(args[0]); entered.set(); unblock.wait(3); return self.rows
        checker = self.checker(transport=delayed)
        result = checker.request_check()
        self.assertTrue(entered.wait(1))
        self.assertTrue(result["checking"])
        checker.request_check()
        self.assertEqual(len(self.calls), 1)
        unblock.set()
        checker._request_thread.join(2)
        self.assertEqual(checker.status()["status"], "available")

    def test_channel_switch_discards_inflight_old_channel_result(self):
        entered, unblock = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            entered.set(); unblock.wait(3); return self.rows
        checker = self.checker(transport=delayed)
        checker.settings({"auto_check": False})
        checker.request_check()
        self.assertTrue(entered.wait(1))
        checker.settings({"channel": "preview"})
        unblock.set();checker._request_thread.join(2)
        self.assertIsNone(checker.status()["release"])
        self.assertIsNone(checker.status()["checked_at"])

    def test_corrupt_or_untrusted_cached_files_do_not_prevent_startup(self):
        (self.root / "updates.json").write_text("not json", "utf-8")
        self.assertEqual(self.checker().status()["status"], "not_checked")
        checker = self.checker();checker.check()
        data = json.loads((self.root / "updates.json").read_text("utf-8"))
        data["release"]["asset_url"] = "https://evil.example/fake.exe"
        (self.root / "updates.json").write_text(json.dumps(data), "utf-8")
        self.assertIsNone(self.checker().status()["release"])

    def test_malformed_or_rate_limited_api_gets_safe_clear_status(self):
        self.assertEqual(self.checker(transport=lambda *a, **k: {"bad": True}).check()["status"], "invalid_response")
        self.now += 60
        def limited(*a, **k):
            raise urllib.error.HTTPError(API_URL, 403, "FAKE token and private path", {}, None)
        result = self.checker(transport=limited).check()
        self.assertEqual(result["status"], "rate_limited")
        self.assertNotIn("FAKE", json.dumps(result))

    def test_default_transport_fixed_url_bounded_body_and_no_credentials(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                self.limit = limit
                return b"[]"
        reply = Reply()
        with patch("nkb.service.updates.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = reply
            self.assertEqual(fetch_releases(API_URL, timeout=5, max_bytes=100), [])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, API_URL)
            self.assertIsNone(request.data)
            self.assertNotIn("Authorization", dict(request.header_items()))
            self.assertNotIn("Cookie", dict(request.header_items()))
            self.assertEqual(reply.limit, 101)
        with self.assertRaises(ValueError):
            fetch_releases("https://evil.example", timeout=5, max_bytes=100)


class UpdateHTTPTests(unittest.TestCase):
    def setUp(self):
        from nkb.service.host import MemoryHost, make_controller
        self.temp = tempfile.TemporaryDirectory()
        self.host = MemoryHost(self.temp.name)
        self.host.updates.stop()
        self.host.updates = UpdateChecker(self.temp.name, version="0.5.0", system="Darwin", machine="arm64",
                                          transport=lambda *a, **k: [release()])
        self.host.updates.settings({"auto_check": False})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_controller(self.host))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.host.stop(); self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        headers = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request("http://127.0.0.1:" + str(self.server.server_port) + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_status_manual_and_settings_routes_use_existing_local_guards(self):
        code, status = self.request("/api/updates")
        self.assertEqual(code, 200)
        self.assertEqual(status["status"], "not_checked")
        code, _ = self.request("/api/updates/check", {})
        self.assertEqual(code, 200)
        if self.host.updates._request_thread:
            self.host.updates._request_thread.join(2)
        self.assertTrue(self.request("/api/updates")[1]["available"])
        self.assertEqual(self.request("/api/updates/settings", {"channel": "preview"})[0], 200)
        self.assertEqual(self.request("/api/updates/settings", {"url": "https://evil.example"})[0], 400)
        self.assertEqual(self.request("/api/updates", headers={"Authorization": "Bearer FAKE_MEMORY_TOKEN"})[0], 403)
        self.assertEqual(self.request("/api/updates/settings", {"auto_check": True}, {"Origin": "https://evil.example"})[0], 403)


class UpdateUITests(unittest.TestCase):
    def test_shipped_page_inlines_one_update_component_before_button_hints(self):
        from nkb.viz.builder import template
        html = template()
        marker = 'data-nkb-component="update-checker-ui.js"'
        self.assertEqual(html.count(marker), 1)
        self.assertLess(html.index(marker), html.index('data-nkb-component="button-hints.js"'))

    @unittest.skipUnless(shutil.which("node"), "Node is optional for UI behavior checks")
    def test_actual_ui_startup_manual_settings_offline_platform_links_and_races(self):
        script = Path(__file__).parent / "js/update-checker-ui.test.cjs"
        result = subprocess.run([shutil.which("node"), "--test", "--test-reporter=tap", str(script)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 7", result.stdout)


if __name__ == "__main__":
    unittest.main()
