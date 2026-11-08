"""Adversarial checks for immutable CI evidence and append-only release writes."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import urllib.parse
import urllib.request
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "publish_android_0106.py"
if not SCRIPT.exists():
    SCRIPT = HERE.parent / "scripts/publish_android_0106.py"
spec = importlib.util.spec_from_file_location("android0106publisher", SCRIPT)
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)
METADATA = HERE / "android-0106-publication.json"
if not METADATA.exists():
    METADATA = HERE.parent / "scripts/android-0106-publication.json"


def fixture_metadata():
    value = json.loads(METADATA.read_text("utf-8"))
    value.update(ready=True, publish_enabled=False)
    value["acceptance_run"]["id"] = 123456789
    value["acceptance_run"]["head_sha"] = "1" * 40
    value["extra_qa_apk"] = {"bytes": 10, "sha256": "2" * 64}
    for api in (28, 36):
        value["artifacts"][str(api)].update(id=api + 100, bytes=10, sha256="3" * 64)
    return value


def probe_text(mode, api):
    values = {"mode": mode, "protocol": "love-house-original-upgrade-0106/v1", "ok": "true",
              "api_level": str(api), "original_certificate": "true", "version_code": "3" if mode == "seed" else "4", "model_calls": "0"}
    return ("\n".join("INSTRUMENTATION_RESULT: " + key + "=" + val for key, val in values.items())
            + "\nINSTRUMENTATION_CODE: -1\n").encode()


def runner_text(api):
    cases = sorted(pub.FULL_CASES if api == 36 else pub.TEST_CASES)
    lines = []
    for cls, name in cases:
        for code in (1, 0):
            lines.extend(["INSTRUMENTATION_STATUS: class=io.github.myflww.lovehouse." + cls,
                          "INSTRUMENTATION_STATUS: test=" + name,
                          "INSTRUMENTATION_STATUS: numtests=" + str(len(cases)),
                          "INSTRUMENTATION_STATUS_CODE: " + str(code)])
    lines += ["OK (" + str(len(cases)) + " tests)", "INSTRUMENTATION_CODE: -1"]
    return ("\n".join(lines) + "\n").encode()


def png_bytes():
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + chunk(b"IEND", b""))


def fixture_evidence(api, metadata):
    full = api == 36
    modes = ["seed", "verify", "verify_restart", "credential_seed", "credential_delete"] + (["migrate", "persisted"] if full else [])
    files = {pub.APK: b"test-public-apk", "instrumentation.txt": runner_text(api)}
    results = []
    for stage in modes:
        mode = "verify" if stage == "verify_restart" else stage
        name = stage + "-probe.txt"
        files[name] = probe_text(mode, api)
        results.append({"mode": mode, "api_level": api, "protocol": "love-house-original-upgrade-0106/v1",
                        "version_code": 3 if mode == "seed" else 4, "ok": True,
                        "original_certificate": True, "model_calls": 0, "transcript": name})
    extra_identity = {"package": "io.github.myflww.lovehouse.extraqa", "version_code": "1", "version_name": "1",
                      "min_sdk": ["26"], "target_sdk": ["36"], "certificate_sha256": pub.CERT,
                      "runner": "io.github.myflww.lovehouse.upgradeqa.UpgradeProbeInstrumentation", "target_package": pub.APP}
    images = []
    for name in (["android-smoke.png", "android-engine-smoke.png"] if full else ["android-smoke.png"]):
        files[name] = png_bytes()
        images.append({"name": name, "bytes": len(files[name]), "sha256": pub.sha256(files[name])})
    report = {"schema": "love-house-android-original-signed-0106-acceptance/v1", "ok": True,
              "source_commit": pub.SOURCE, "api_level": api, "model_calls": 0,
              "tested_apk": {"bytes": len(files[pub.APK]), "sha256": pub.sha256(files[pub.APK])},
              "frozen_test_apk": {"bytes": 914423, "sha256": pub.TEST_HASH}, "extra_qa_apk": metadata["extra_qa_apk"],
              "certificate_sha256": pub.CERT,
              "old_apk_identity": {"package": pub.APP, "version_code": "3", "version_name": "0.8.0rc2",
                                   "min_sdk": ["26"], "target_sdk": ["36"], "certificate_sha256": pub.CERT},
              "upgrade_preservation": {"passed": True, "from_version_code": 3, "to_version_code": 4, "libraries": 2,
                                       "in_place": True, "after_restart": True},
              "webview": {"package": "com.google.android.webview", "version": "145.0.1.1" if full else "69.0.1.1", "major": 145 if full else 69},
              "instrumentation_scope": "full_engine_and_legacy" if full else "legacy_and_provider_upgrade_only",
              "full_engine_verified": full, "partial": not full,
              "instrumentation": {"tests": 11 if full else 7, "failures": 0, "errors": 0, "skipped": 0},
              "supplemental": {"modes": modes, "results": results, "passed": True,
                               "migration": "passed" if full else "requires_modern_webview",
                               "complete_engine_export_restore_saf": "passed" if full else "requires_modern_webview",
                               "credential_process_restart_delete": "passed"},
              "identities": {"apk": {**pub.EXPECTED_APP, "certificate_sha256": pub.CERT},
                             "test_apk": {"package": pub.APP + ".test", "version_code": "", "version_name": "",
                                          "min_sdk": ["26"], "target_sdk": ["36"], "certificate_sha256": pub.CERT,
                                          "runner": "androidx.test.runner.AndroidJUnitRunner", "target_package": pub.APP},
                             "extra_qa": extra_identity},
              "extra_qa_identity": extra_identity,
              "transcripts": {name: pub.sha256(raw) for name, raw in files.items() if name.endswith(".txt")},
              "frozen_test_names": [{"class": "io.github.myflww.lovehouse." + cls, "test": name}
                                    for cls, name in sorted(pub.FULL_CASES if full else pub.TEST_CASES)],
              "screenshots": images}
    files["verification.json"] = json.dumps(report).encode()
    return files, report


class FakeGitHub:
    def __init__(self, metadata):
        self.metadata = metadata
        self.release = deepcopy(metadata["release_snapshot"])
        self.assets = {item["name"]: deepcopy(item) for item in self.release.pop("assets")}
        self.contents = {}
        self.writes = []
        self.before_write = None

    def api(self, method, path, **kwargs):
        if method == "GET" and path == pub.RELEASE_API:
            return deepcopy(self.release)
        if method == "GET" and path == pub.BASE + "/git/ref/tags/" + pub.TAG:
            return {"ref": "refs/tags/" + pub.TAG, "object": {"type": "commit", "sha": pub.TARGET}}
        if method == "GET" and path == pub.RELEASE_API + "/assets?per_page=100":
            return list(deepcopy(self.assets).values())
        if self.before_write:
            self.before_write(self)
        self.writes.append((method, path))
        if method == "POST":
            name = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)["name"][0]
            assert name not in self.assets
            raw = kwargs["content"]
            self.contents[name] = raw
            self.assets[name] = {"id": 999000 + len(self.assets), "name": name, "size": len(raw),
                                 "digest": "sha256:" + pub.sha256(raw), "state": "uploaded",
                                 "browser_download_url": pub.public_url(name)}
            return deepcopy(self.assets[name])
        if method == "PATCH":
            assert set(kwargs["payload"]) == {"body"}
            self.release["body"] = kwargs["payload"]["body"]
            return deepcopy(self.release)
        raise AssertionError("Unexpected fake request")

    def anonymous(self, url, size):
        name = urllib.parse.unquote(url.rsplit("/", 1)[1])
        raw = self.contents[name]
        assert len(raw) == size
        return raw


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.metadata = fixture_metadata()

    def test_placeholder_metadata_never_enables_publication(self):
        draft = deepcopy(self.metadata)
        draft["ready"] = False
        with self.assertRaises(pub.PublicationError): pub.checked_metadata(draft)
        draft["ready"] = True
        draft["acceptance_run"]["head_sha"] = "PENDING"
        with self.assertRaises(pub.PublicationError): pub.checked_metadata(draft)
        self.assertIs(pub.checked_metadata(self.metadata), self.metadata)

    def test_frozen_source_build_artifact_or_two_api_identity_cannot_change(self):
        for field, mutation in [("source_commit", "f" * 40), ("build_run", {**self.metadata["build_run"], "id": 42439732198}),
                                ("build_artifact", {**self.metadata["build_artifact"], "sha256": "e" * 64})]:
            bad = deepcopy(self.metadata); bad[field] = mutation
            with self.subTest(field=field), self.assertRaises(pub.PublicationError): pub.checked_metadata(bad)
        bad = deepcopy(self.metadata); bad["artifacts"]["36"]["id"] = bad["artifacts"]["28"]["id"]
        with self.assertRaises(pub.PublicationError): pub.checked_metadata(bad)

    def test_existing_original_assets_cannot_be_changed_or_removed(self):
        entries = deepcopy(self.metadata["release_snapshot"]["assets"])
        for field, val in [("id", 1), ("size", 1), ("digest", "sha256:" + "0" * 64), ("state", "new"),
                           ("browser_download_url", "https://example.com/download")]:
            bad = deepcopy(entries); bad[0][field] = val
            with self.subTest(field=field), self.assertRaises(pub.PublicationError): pub.checked_asset_map(self.metadata, bad)
        with self.assertRaises(pub.PublicationError): pub.checked_asset_map(self.metadata, entries[1:])
        with self.assertRaises(pub.PublicationError): pub.checked_asset_map(self.metadata, entries + [entries[0]])

    def test_an_unreviewed_extra_asset_or_moved_tag_is_rejected(self):
        entries = deepcopy(self.metadata["release_snapshot"]["assets"])
        with self.assertRaises(pub.PublicationError): pub.checked_asset_map(self.metadata, entries + [{"name": "QA-only.apk"}])
        with self.assertRaises(pub.PublicationError): pub.checked_tag({"ref": "refs/tags/" + pub.TAG, "object": {"type": "commit", "sha": "0" * 40}})

    def test_release_body_is_strict_append_and_idempotent(self):
        body = pub.appended_body(self.metadata)
        self.assertTrue(body.startswith(self.metadata["release_snapshot"]["body"].rstrip("\n") + "\n\n"))
        self.assertEqual(body.count(pub.BEGIN), 1)
        self.assertIn("7 项测试", body); self.assertIn("11 项测试", body)
        client = FakeGitHub(self.metadata)
        client.release["body"] = body
        pub.checked_current_release(client, self.metadata)
        client.release["body"] += "concurrent edit"
        with self.assertRaises(pub.PublicationError): pub.checked_current_release(client, self.metadata)

    def test_ci_failed_head_or_job_name_cannot_be_substituted(self):
        pin = self.metadata["acceptance_run"]
        run = {"id": pin["id"], "head_sha": pin["head_sha"], "head_branch": pin["head_branch"], "path": pin["path"],
               "status": "completed", "conclusion": "success", "event": "push", "head_repository": {"full_name": pub.REPOSITORY}}
        jobs = {"total_count": 2, "jobs": [{"id": api, "run_id": pin["id"], "name": "verify (" + str(api) + ")", "status": "completed", "conclusion": "success"} for api in (28, 36)]}
        class Client:
            def api(self, method, path): return deepcopy(jobs if "/jobs?" in path else run)
        self.assertEqual(pub.checked_run(Client(), pin)["head_sha"], pin["head_sha"])
        for field, value in [("conclusion", "failure"), ("head_sha", "e" * 40), ("status", "in_progress")]:
            before = run[field]; run[field] = value
            with self.assertRaises(pub.PublicationError): pub.checked_run(Client(), pin)
            run[field] = before
        jobs["jobs"][1]["name"] = "verify (28)"
        with self.assertRaises(pub.PublicationError): pub.checked_run(Client(), pin)

    def test_raw_instrumentation_rejects_skips_missing_start_or_wrong_cases(self):
        raw = runner_text(36)
        self.assertEqual(len(pub.checked_instrumentation(raw, 36)), 11)
        for changed in [raw.replace(b"INSTRUMENTATION_STATUS_CODE: 0", b"INSTRUMENTATION_STATUS_CODE: -3", 1),
                        raw.replace(b"INSTRUMENTATION_STATUS_CODE: 1", b"INSTRUMENTATION_STATUS_CODE: 0", 1),
                        raw.replace(b"bundledEngineRunsSameCoreAndWarmUiWithStrictLocalOrigin", b"anUnrelatedTest")]:
            with self.assertRaises(pub.PublicationError): pub.checked_instrumentation(changed, 36)

    def test_probe_rejects_other_api_certificate_paid_call_and_duplicate_result(self):
        raw = probe_text("verify", 36)
        pub.parsed_probe(raw, "verify", 36)
        for changed in [raw.replace(b"api_level=36", b"api_level=28"), raw.replace(b"original_certificate=true", b"original_certificate=false"),
                        raw.replace(b"model_calls=0", b"model_calls=1"), raw + b"INSTRUMENTATION_RESULT: ok=true\n"]:
            with self.assertRaises(pub.PublicationError): pub.parsed_probe(changed, "verify", 36)

    def test_explicit_api28_scope_and_full_api36_scope_are_accepted(self):
        for api in (28, 36):
            files, report = fixture_evidence(api, self.metadata)
            with patch.object(pub, "APK_BYTES", len(files[pub.APK])), patch.object(pub, "APK_HASH", pub.sha256(files[pub.APK])):
                result = pub.checked_evidence(files, api, self.metadata)
            self.assertEqual(result["full_engine_verified"], api == 36)
            self.assertEqual(result["partial"], api == 28)

    def test_reporting_success_does_not_hide_missing_upgrade_migration_or_skips(self):
        files, report = fixture_evidence(36, self.metadata)
        mutations = [lambda r: r.update(ok=False), lambda r: r.update(partial=True),
                     lambda r: r["upgrade_preservation"].update(after_restart=False),
                     lambda r: r["upgrade_preservation"].update(libraries=1),
                     lambda r: r["instrumentation"].update(skipped=1),
                     lambda r: r["instrumentation"].update(errors=False),
                     lambda r: r["supplemental"].update(migration="requires_modern_webview"),
                     lambda r: r["supplemental"].update(complete_engine_export_restore_saf="not_tested"),
                     lambda r: r["supplemental"]["results"][0].update(model_calls=False),
                     lambda r: r["identities"]["extra_qa"].update(certificate_sha256="f" * 64),
                     lambda r: r.update(source_commit="e" * 40)]
        with patch.object(pub, "APK_BYTES", len(files[pub.APK])), patch.object(pub, "APK_HASH", pub.sha256(files[pub.APK])):
            for index, mutate in enumerate(mutations):
                bad = deepcopy(report); mutate(bad)
                changed = {**files, "verification.json": json.dumps(bad).encode()}
                with self.subTest(mutation=index), self.assertRaises(pub.PublicationError): pub.checked_evidence(changed, 36, self.metadata)

    def test_api28_cannot_claim_full_engine_on_an_old_webview(self):
        files, report = fixture_evidence(28, self.metadata)
        report.update(full_engine_verified=True, partial=False, instrumentation_scope="full_engine_and_legacy")
        files["verification.json"] = json.dumps(report).encode()
        with patch.object(pub, "APK_BYTES", len(files[pub.APK])), patch.object(pub, "APK_HASH", pub.sha256(files[pub.APK])):
            with self.assertRaises(pub.PublicationError): pub.checked_evidence(files, 28, self.metadata)

    def test_successful_json_cannot_mask_changed_raw_transcripts_or_screenshots(self):
        files, _ = fixture_evidence(36, self.metadata)
        with patch.object(pub, "APK_BYTES", len(files[pub.APK])), patch.object(pub, "APK_HASH", pub.sha256(files[pub.APK])):
            for name in ("migrate-probe.txt", "verify_restart-probe.txt", "instrumentation.txt", "android-engine-smoke.png"):
                changed = {**files, name: files[name] + b"corrupt"}
                with self.subTest(file=name), self.assertRaises(pub.PublicationError): pub.checked_evidence(changed, 36, self.metadata)

    def test_artifact_zip_digest_duplicate_basename_and_traversal_are_rejected(self):
        for names in [["../verification.json"], ["a/verification.json", "b/verification.json"], ["x\\verification.json"]]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as zipped:
                for name in names:
                    item = zipfile.ZipInfo("initial-name")
                    item.filename = name
                    zipped.writestr(item, b"{}")
            raw = buffer.getvalue(); pin = {"bytes": len(raw), "sha256": pub.sha256(raw)}
            with self.subTest(names=names), self.assertRaises(pub.PublicationError): pub.checked_archive(raw, pin)
        with self.assertRaises(pub.PublicationError): pub.checked_archive(b"tampered", {"bytes": 8, "sha256": "a" * 64})

    def fixture_public_assets(self):
        return {pub.APK: b"test-public-apk", pub.SIGNING: b"test-signing-receipt", pub.EVIDENCE: b"{}\n", pub.CHECKSUMS: b"checksums\n"}

    def test_append_preserves_all_originals_and_second_attempt_is_idempotent(self):
        assets = self.fixture_public_assets(); client = FakeGitHub(self.metadata)
        originals = deepcopy(client.assets)
        with patch.object(pub, "APK_BYTES", len(assets[pub.APK])), patch.object(pub, "APK_HASH", pub.sha256(assets[pub.APK])), patch.object(pub, "SIGNING_HASH", pub.sha256(assets[pub.SIGNING])):
            result = pub.publish(client, self.metadata, assets)
            self.assertTrue(result["published"])
            self.assertEqual([client.assets[name] for name in originals], list(originals.values()))
            self.assertEqual(len(client.writes), 5)
            self.assertEqual(client.writes[3][0], "POST")
            self.assertIn(pub.APK, client.writes[3][1])
            client.writes.clear()
            pub.publish(client, self.metadata, assets)
            self.assertEqual(client.writes, [])

    def test_collision_or_concurrent_body_change_never_overwrites_existing_asset(self):
        assets = self.fixture_public_assets(); client = FakeGitHub(self.metadata)
        name = pub.EVIDENCE
        client.assets[name] = {"id": 123, "name": name, "size": 1, "digest": "sha256:" + "0" * 64,
                                "state": "uploaded", "browser_download_url": pub.public_url(name)}
        with patch.object(pub, "APK_BYTES", len(assets[pub.APK])), patch.object(pub, "APK_HASH", pub.sha256(assets[pub.APK])), patch.object(pub, "SIGNING_HASH", pub.sha256(assets[pub.SIGNING])):
            with self.assertRaises(pub.PublicationError): pub.publish(client, self.metadata, assets)
            self.assertEqual(client.writes, [])
            client = FakeGitHub(self.metadata)
            client.before_write = lambda instance: instance.release.update(body=instance.release["body"] + "edit")
            with self.assertRaises(pub.PublicationError): pub.publish(client, self.metadata, assets)
            self.assertFalse(any(method == "PATCH" for method, path in client.writes))

    def test_qa_asset_delete_and_unrelated_api_requests_are_not_supported(self):
        assets = self.fixture_public_assets(); assets["QA-only.apk"] = b"developer only"
        with self.assertRaises(pub.PublicationError): pub.publish(FakeGitHub(self.metadata), self.metadata, assets)
        client = pub.GitHub("synthetic-not-a-real-token")
        for method, path in [("DELETE", pub.RELEASE_API), ("PATCH", pub.BASE + "/git/refs/tags/" + pub.TAG),
                             ("POST", pub.BASE + "/releases"), ("GET", "/user")]:
            with self.subTest(method=method, path=path), self.assertRaises(pub.PublicationError): client.api(method, path)

    def test_binary_redirect_drops_bearer_and_rejects_other_origins(self):
        handler = pub.SafeRedirect()
        request = urllib.request.Request("https://api.github.com/owned-artifact", headers={"Authorization": "Bearer synthetic"})
        redirected = handler.redirect_request(request, None, 302, "", {}, "https://release-assets.githubusercontent.com/file?token=public-sas")
        self.assertFalse(any(key.lower() == "authorization" for key in redirected.headers))
        for url in ["http://release-assets.githubusercontent.com/file", "https://example.com/file", "https://release-assets.githubusercontent.com@evil.com/file"]:
            with self.assertRaises(pub.PublicationError): handler.redirect_request(request, None, 302, "", {}, url)


if __name__ == "__main__":
    unittest.main()
