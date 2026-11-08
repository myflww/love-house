#!/usr/bin/env python3
"""Validate fixed Android 0.10.6 evidence; append four assets only with --publish.

No private keys are used, and existing release assets, tags and other releases
are never created, replaced, moved or deleted. Source/build and acceptance runs
must finish successfully at their reviewed immutable heads before publication.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib

REPOSITORY = "myflww/love-house"
TAG = "v0.10.6rc1"
RELEASE_ID = 435996115
TARGET = "2f391eb29e57ee93dbf6418474371410520f996e"
SOURCE = "732d7df84815e7b360f3bf1820b261747ae1d047"
BRANCH = "codex/android-0106-publish"
APP = "io.github.myflww.lovehouse.preview"
CERT = "ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc"
APK = "LoveHouse-0.10.6rc1-Android.apk"
APK_BYTES = 48430105
APK_HASH = "4d27f0a732c6edc53fbfcdcaac43f573b91327b703e10396e5d0c8435390f018"
TEST_HASH = "7fd6efc07b602d6ccb056550a1fd3149e112ca5175fe94df730b5e61240412f2"
SIGNING = "Android-0106-original-signing-verification.json"
SIGNING_HASH = "e75a3c1b73526c2968ff9e44ad6b8bf6cef36f2c3afdfd8fad7ee5e944c04f6a"
EVIDENCE = "Android-0106-verification.json"
CHECKSUMS = "Android-SHA256SUMS.txt"
ASSET_NAMES = {APK, SIGNING, EVIDENCE, CHECKSUMS}
BASE = "/repos/" + REPOSITORY
RELEASE_API = BASE + "/releases/" + str(RELEASE_ID)
BEGIN = "<!-- love-house-android-0106-original-signing:begin -->"
END = "<!-- love-house-android-0106-original-signing:end -->"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_APP = {"package": APP, "version_code": "4", "version_name": "0.10.6rc1",
                "min_sdk": ["26"], "target_sdk": ["36"]}
TEST_CASES = {
    ("MobileSmokeTest", "offlineBoundaryRejectsExternalOriginsAndUnneededPermissions"),
    ("MobileSmokeTest", "agentConnectionOpensOnlyTheChosenHttpsServiceWithoutLocalHostDetection"),
    ("MobileSmokeTest", "uiCanCreateEditSearchAndOpenTheStarMap"),
    ("MobileSmokeTest", "memoryAndSelectedLibrarySurviveActivityRecreationAndRelaunch"),
    ("MobileSmokeTest", "separateLibrariesAndPortableExportsStayIsolated"),
    ("NativeSafExportTest", "nativeSafWritesUtf8AndCancellationNeverClaimsSuccess"),
    ("AndroidWebViewCompatibilityTest", "providerEitherLoadsTheFullUiOrExplainsTheRequiredUpdate"),
}
FULL_CASES = TEST_CASES | {
    ("AndroidMigrationSmokeTest", "selectedLegacyLibraryMovesOnlyByExplicitNativeActionAndOriginalSurvives"),
    ("AndroidEngineSmokeTest", "bundledEngineRunsSameCoreAndWarmUiWithStrictLocalOrigin"),
    ("AndroidEngineSmokeTest", "personaChoicesCorrectionIsolationAndActivityRestartPersist"),
    ("AndroidEngineSmokeTest", "androidKeystorePersistsOnlyEncryptedScopedCredentials"),
}


class PublicationError(ValueError):
    """Bounded diagnostics; never include token, API response, or memory text."""


def require(value, message):
    if not value:
        raise PublicationError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def typed_equal(left, right):
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(right, sort_keys=True, separators=(",", ":"))


def integer(value):
    return type(value) is int and value > 0


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "JSON has duplicate properties")
            result[key] = value
        return result
    require(isinstance(raw, bytes) and len(raw) <= 2 * 1024 * 1024, "JSON exceeds the evidence budget")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)


def checked_metadata(value):
    require(isinstance(value, dict) and value.get("schema") == "love-house-android-0106-publication/v1",
            "Unknown publication metadata")
    require(value.get("ready") is True and type(value.get("publish_enabled")) is bool,
            "Publication pins have not been explicitly finalized")
    require(value.get("repository") == REPOSITORY and value.get("publication_branch") == BRANCH
            and value.get("source_commit") == SOURCE, "Publication repository, branch or source changed")
    source = value.get("build_run", {})
    require(source == {"id": 42439732197, "head_sha": SOURCE,
                       "head_branch": "codex/android-0106-update", "path": ".github/workflows/android.yml",
                       "required_jobs": ["android (28)", "android (36)"]}, "Frozen build run changed")
    require(value.get("build_artifact") == {"id": 13601002157, "name": "android-unsigned-api-36",
            "bytes": 76345733, "sha256": "b4c7c8bfc01363f5d2a4a5cd60430b0b04af30fe731bdfbaa889b98e070f60fe"},
            "Frozen build artifact changed")
    acceptance = value.get("acceptance_run", {})
    require(integer(acceptance.get("id")) and bool(HEX40.fullmatch(str(acceptance.get("head_sha", ""))))
            and acceptance.get("head_branch") == "codex/android-0106-original-signing"
            and isinstance(acceptance.get("path"), str)
            and acceptance["path"].startswith(".github/workflows/")
            and acceptance["path"].endswith(".yml")
            and acceptance.get("required_jobs") == ["verify (28)", "verify (36)"],
            "Acceptance run pins are incomplete")
    artifacts = value.get("artifacts", {})
    require(set(artifacts) == {"28", "36"}, "Both API artifact pins are required")
    ids = []
    for api in (28, 36):
        item = artifacts[str(api)]
        require(isinstance(item, dict) and integer(item.get("id")) and integer(item.get("bytes"))
                and item["bytes"] <= 150 * 1024 * 1024
                and item.get("name") == "original-signed-0106-api-" + str(api)
                and bool(HEX64.fullmatch(str(item.get("sha256", "")))), "API artifact pins are incomplete")
        ids.append(item["id"])
    require(len(set(ids)) == 2, "Two APIs cannot reuse one artifact")
    extra = value.get("extra_qa_apk", {})
    require(integer(extra.get("bytes")) and extra["bytes"] <= 10 * 1024 * 1024
            and bool(HEX64.fullmatch(str(extra.get("sha256", "")))), "Supplemental QA pin is incomplete")
    extra_run = value.get("extra_qa_build_run", {})
    require(integer(extra_run.get("id")) and bool(HEX40.fullmatch(str(extra_run.get("head_sha", ""))))
            and extra_run.get("head_branch") == "codex/android-0106-original-signing"
            and extra_run.get("path") == ".github/workflows/android-0106-build-extraqa.yml"
            and extra_run.get("required_jobs") == ["build"], "Supplemental QA build run pin is incomplete")
    extra_artifact = value.get("extra_qa_build_artifact", {})
    require(integer(extra_artifact.get("id")) and integer(extra_artifact.get("bytes"))
            and extra_artifact["bytes"] <= 10 * 1024 * 1024
            and extra_artifact.get("name") == "android-0106-extraqa-unsigned-input"
            and bool(HEX64.fullmatch(str(extra_artifact.get("sha256", "")))), "Supplemental QA build artifact pin is incomplete")
    receipt = value.get("signing_report", {})
    require(integer(receipt.get("bytes")) and receipt["bytes"] <= 1024 * 1024
            and receipt.get("sha256") == SIGNING_HASH, "Original signing receipt pin changed")
    snapshot = value.get("release_snapshot", {})
    checked_release(snapshot)
    require(isinstance(snapshot.get("body"), str) and BEGIN not in snapshot["body"]
            and END not in snapshot["body"], "Original release body is not a clean pinned snapshot")
    require(isinstance(snapshot.get("assets"), list) and len(snapshot["assets"]) == 11,
            "Expected all eleven original release assets")
    original = {item.get("name"): item for item in snapshot["assets"]}
    require(len(original) == 11 and not ASSET_NAMES.intersection(original), "Original asset names collide")
    for item in original.values():
        require(integer(item.get("id")) and integer(item.get("size")) and item.get("state") == "uploaded"
                and bool(HEX64.fullmatch(str(item.get("digest", ""))[7:]))
                and str(item.get("digest", "")).startswith("sha256:")
                and item.get("browser_download_url") == public_url(item["name"]), "Original asset pin is invalid")
    return value


def checked_release(value):
    require(isinstance(value, dict) and value.get("id") == RELEASE_ID and type(value.get("id")) is int
            and value.get("tag_name") == TAG and value.get("target_commitish") == TARGET
            and value.get("draft") is False and value.get("prerelease") is True,
            "Existing release identity changed")


def checked_tag(value):
    require(value.get("ref") == "refs/tags/" + TAG and value.get("object", {}).get("type") == "commit"
            and value.get("object", {}).get("sha") == TARGET, "Original release tag moved")


def public_url(name):
    return "https://github.com/" + REPOSITORY + "/releases/download/" + TAG + "/" + urllib.parse.quote(name, safe="")


def checked_asset_map(metadata, entries):
    require(isinstance(entries, list) and len(entries) <= 15, "Unexpected release asset listing")
    actual = {item.get("name"): item for item in entries}
    require(len(actual) == len(entries), "Release asset names are duplicated")
    snapshot = {item["name"]: item for item in metadata["release_snapshot"]["assets"]}
    require(set(actual) <= set(snapshot) | ASSET_NAMES, "Unreviewed release asset was added")
    for name, expected in snapshot.items():
        item = actual.get(name, {})
        require(all(item.get(key) == expected[key] for key in
                    ("id", "name", "size", "digest", "browser_download_url", "state"))
                and type(item.get("id")) is int and type(item.get("size")) is int,
                "An original release asset changed")
    return actual


def checked_run(client, pin):
    run = client.api("GET", BASE + "/actions/runs/" + str(pin["id"]))
    require(run.get("id") == pin["id"] and run.get("head_sha") == pin["head_sha"]
            and run.get("head_branch") == pin["head_branch"] and run.get("path") == pin["path"]
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("event") in {"push", "pull_request", "workflow_dispatch"}
            and run.get("head_repository", {}).get("full_name") == REPOSITORY,
            "Pinned workflow is not successful at the reviewed head")
    listing = client.api("GET", BASE + "/actions/runs/" + str(pin["id"]) + "/jobs?per_page=100")
    jobs = listing.get("jobs", [])
    names = [job.get("name") for job in jobs]
    require(listing.get("total_count") == len(jobs) and len(set(names)) == len(names)
            and set(names) == set(pin["required_jobs"])
            and all(job.get("run_id") == pin["id"] and job.get("status") == "completed"
                    and job.get("conclusion") == "success" for job in jobs), "Required workflow jobs did not all succeed")
    return {"id": pin["id"], "head_sha": pin["head_sha"], "path": pin["path"],
            "conclusion": "success", "jobs": [{"id": job["id"], "name": job["name"],
            "conclusion": "success"} for job in jobs]}


def checked_artifact_listing(client, pin, wanted):
    listing = client.api("GET", BASE + "/actions/runs/" + str(pin["id"]) + "/artifacts?per_page=100")
    values = listing.get("artifacts", [])
    require(listing.get("total_count") == len(values) and len(values) <= 100, "Incomplete artifact listing")
    result = {}
    for expected in wanted:
        found = [item for item in values if item.get("id") == expected["id"]]
        require(len(found) == 1, "Pinned workflow artifact is missing")
        item = found[0]
        identity = item.get("workflow_run", {})
        require(item.get("name") == expected["name"] and item.get("size_in_bytes") == expected["bytes"]
                and type(item.get("size_in_bytes")) is int and item.get("digest") == "sha256:" + expected["sha256"]
                and item.get("expired") is False and identity.get("id") == pin["id"]
                and identity.get("head_sha") == pin["head_sha"] and identity.get("head_branch") == pin["head_branch"],
                "Pinned artifact identity or digest changed")
        result[item["id"]] = item
    return result


def checked_archive(raw, expected):
    require(len(raw) == expected["bytes"] and sha256(raw) == expected["sha256"], "Artifact archive bytes changed")
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) < 250 and sum(item.file_size for item in entries) <= 180 * 1024 * 1024,
                "Artifact archive exceeds the evidence budget")
        for item in entries:
            # orig_filename retains Windows backslashes and NUL bytes that
            # ZipInfo.filename may normalize or truncate on the current host.
            path = PurePosixPath(item.orig_filename)
            require(not path.is_absolute() and not stat.S_ISLNK(item.external_attr >> 16)
                    and all(part not in {"..", ".", ""} and ":" not in part and "\\" not in part and "\0" not in part for part in path.parts),
                    "Artifact archive contains unsafe paths")
            if item.is_dir():
                continue
            name = path.name
            require(name.casefold() not in {key.casefold() for key in result}, "Artifact archive contains ambiguous filenames")
            result[name] = archive.read(item)
    return result


def checked_signing_receipt(raw, metadata):
    pin = metadata["signing_report"]
    require(len(raw) == pin["bytes"] and sha256(raw) == SIGNING_HASH, "Original signing receipt bytes changed")
    report = strict_json(raw)
    require(report.get("schema") == "love-house-android-0106-original-signing/v1"
            and report.get("source_commit") == SOURCE
            and report.get("source_commit_check") == "matched_explicit_expected_commit_and_developer_handoff"
            and report.get("application_id") == APP and report.get("version_name") == "0.10.6rc1"
            and type(report.get("version_code")) is int and report["version_code"] == 4
            and report.get("certificate_sha256") == CERT and report.get("same_original_signer") is True
            and report.get("payload_preserved") is True and report.get("signature_and_metadata") == "passed"
            and report.get("device_upgrade_verified") is False and report.get("published") is False
            and report.get("independent_rebuild_verified") is False,
            "Original signing receipt does not prove the frozen payload and signer")
    signed = report.get("signed", {})
    main, test = signed.get("apk", {}), signed.get("test_apk", {})
    require(main.get("bytes") == APK_BYTES and type(main.get("bytes")) is int and main.get("sha256") == APK_HASH
            and main.get("identity") == EXPECTED_APP and main.get("certificate_sha256") == CERT
            and main.get("qa_only") is False and test.get("sha256") == TEST_HASH
            and test.get("bytes") == 914423 and type(test.get("bytes")) is int
            and test.get("certificate_sha256") == CERT and test.get("qa_only") is True,
            "Original signing receipt APK identity differs")
    return report


def parsed_probe(raw, mode, api):
    require(len(raw) <= 1024 * 1024, "Probe transcript exceeds the evidence budget")
    text = raw.decode("utf-8")
    require(re.findall(r"^INSTRUMENTATION_CODE: (-?\d+)\s*$", text, re.M) == ["-1"]
            and not re.search(r"INSTRUMENTATION_FAILED|shortMsg=|Process crashed|FAILURES!!!", text),
            "Supplemental probe transcript failed or targets another API/mode")
    expected = {"mode": mode, "protocol": "love-house-original-upgrade-0106/v1", "ok": "true",
                "api_level": str(api), "original_certificate": "true",
                "version_code": "3" if mode == "seed" else "4", "model_calls": "0"}
    for key, value in expected.items():
        require(re.findall(r"^INSTRUMENTATION_RESULT: " + key + r"=([^\r\n]*)\s*$", text, re.M) == [value],
                "Supplemental probe has an incomplete or repeated identity receipt")
    require(not re.search(r"^INSTRUMENTATION_RESULT: (?:error_stage|exception)=", text, re.M),
            "Supplemental probe includes a failure receipt")
    return {"mode": mode, "api_level": api, "protocol": expected["protocol"], "version_code": int(expected["version_code"]),
            "ok": True, "original_certificate": True, "model_calls": 0}


def checked_instrumentation(raw, api):
    require(len(raw) <= 4 * 1024 * 1024, "Instrumentation transcript exceeds the evidence budget")
    text = raw.decode("utf-8")
    started, passed, declared, status = set(), set(), set(), {}
    for line in text.splitlines():
        if line.startswith("INSTRUMENTATION_STATUS: "):
            key, separator, value = line[len("INSTRUMENTATION_STATUS: "):].partition("=")
            if separator:
                require(key not in status, "Repeated instrumentation status field")
                status[key] = value
        elif line.startswith("INSTRUMENTATION_STATUS_CODE: "):
            code = line.split(": ", 1)[1]
            identity = (status.get("class", ""), status.get("test", ""))
            require(all(identity) and code in {"0", "1"}, "Instrumentation contains a failed or skipped test")
            require("numtests" in status and status["numtests"].isdigit(), "Instrumentation does not declare its complete count")
            declared.add(int(status["numtests"]))
            if code == "1":
                require(identity not in started, "Instrumentation test started repeatedly")
                started.add(identity)
            else:
                require(identity in started and identity not in passed, "Instrumentation test has no unique start")
                passed.add(identity)
            status = {}
    expected = {("io.github.myflww.lovehouse." + cls, name) for cls, name in (FULL_CASES if api == 36 else TEST_CASES)}
    require(passed == started == expected and declared == {len(expected)}
            and re.findall(r"^OK \((\d+) tests?\)\s*$", text, re.M) == [str(len(expected))]
            and re.findall(r"^INSTRUMENTATION_CODE: (-?\d+)\s*$", text, re.M) == ["-1"]
            and not re.search(r"INSTRUMENTATION_FAILED|shortMsg=|Process crashed|FAILURES!!!", text),
            "Actual frozen instrumentation coverage is incomplete")
    return [{"class": cls, "test": name} for cls, name in sorted(expected)]


def checked_png(raw):
    require(8 < len(raw) <= 20 * 1024 * 1024 and raw.startswith(b"\x89PNG\r\n\x1a\n"), "Actual screenshot is not a bounded PNG")
    offset = 8
    first = True
    while offset + 12 <= len(raw):
        size = int.from_bytes(raw[offset:offset + 4], "big")
        kind = raw[offset + 4:offset + 8]
        end = offset + 8 + size
        require(end + 4 <= len(raw) and zlib.crc32(raw[offset + 4:end]) & 0xffffffff == int.from_bytes(raw[end:end + 4], "big"),
                "Actual screenshot PNG chunk is truncated or corrupt")
        if first:
            require(kind == b"IHDR" and size == 13 and all(struct.unpack(">II", raw[offset + 8:offset + 16])),
                    "Actual screenshot dimensions are missing")
            first = False
        offset = end + 4
        if kind == b"IEND":
            require(size == 0 and offset == len(raw), "Actual screenshot PNG has an invalid end")
            return
    raise PublicationError("Actual screenshot PNG is incomplete")


def checked_evidence(files, api, metadata):
    require(APK in files and len(files[APK]) == APK_BYTES and sha256(files[APK]) == APK_HASH,
            "API job did not test the exact signed application")
    report = strict_json(files.get("verification.json", b"{}"))
    require(report.get("schema") == "love-house-android-original-signed-0106-acceptance/v1"
            and report.get("ok") is True and report.get("source_commit") == SOURCE
            and type(report.get("api_level")) is int and report["api_level"] == api
            and report.get("tested_apk") == {"bytes": APK_BYTES, "sha256": APK_HASH}
            and report.get("frozen_test_apk") == {"bytes": 914423, "sha256": TEST_HASH}
            and report.get("extra_qa_apk") == metadata["extra_qa_apk"]
            and report.get("certificate_sha256") == CERT
            and type(report.get("model_calls")) is int and report["model_calls"] == 0,
            "Acceptance report does not bind the signed application, QA and API")
    upgrade = report.get("upgrade_preservation", {})
    expected_upgrade = {"passed": True, "from_version_code": 3, "to_version_code": 4,
                        "libraries": 2, "in_place": True, "after_restart": True}
    require(upgrade == expected_upgrade and all(type(upgrade[key]) is type(value) for key, value in expected_upgrade.items()),
            "Two original libraries did not survive the actual in-place upgrade and restart")
    old = report.get("old_apk_identity", {})
    require(old == {"package": APP, "version_code": "3", "version_name": "0.8.0rc2",
                    "min_sdk": ["26"], "target_sdk": ["36"], "certificate_sha256": CERT},
            "Upgrade report does not identify the original public old application")
    full = api == 36
    require(report.get("instrumentation_scope") == ("full_engine_and_legacy" if full else "legacy_and_provider_upgrade_only")
            and report.get("full_engine_verified") is full and report.get("partial") is (not full),
            "Unexpected partial or full-engine acceptance scope")
    counts = {"tests": 11 if full else 7, "failures": 0, "errors": 0, "skipped": 0}
    require(report.get("instrumentation") == counts
            and all(type(report["instrumentation"][key]) is int for key in counts), "Frozen instrumentation count or result changed")
    webview = report.get("webview", {})
    require(isinstance(webview.get("package"), str) and bool(re.fullmatch(r"[A-Za-z0-9_.]+", webview["package"]))
            and isinstance(webview.get("version"), str) and bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}", webview["version"]))
            and integer(webview.get("major")) and int(webview["version"].split(".")[0]) == webview["major"]
            and ((webview["major"] >= 109) if full else (webview["major"] < 109)), "WebView scope or version is inconsistent")
    supplemental = report.get("supplemental", {})
    modes = ["seed", "verify", "verify_restart", "credential_seed", "credential_delete"]
    if full:
        modes += ["migrate", "persisted"]
    require(supplemental.get("passed") is True and supplemental.get("modes") == modes
            and supplemental.get("migration") == ("passed" if full else "requires_modern_webview")
            and supplemental.get("complete_engine_export_restore_saf") == ("passed" if full else "requires_modern_webview")
            and supplemental.get("credential_process_restart_delete") == "passed", "Required supplemental acceptance is incomplete")
    identities = report.get("identities", {})
    main_identity = identities.get("apk", {})
    require({key: main_identity.get(key) for key in EXPECTED_APP} == EXPECTED_APP
            and main_identity.get("certificate_sha256") == CERT, "Accepted main APK manifest identity changed")
    test_identity = identities.get("test_apk", {})
    require(test_identity.get("package") == APP + ".test"
            and test_identity.get("runner") == "androidx.test.runner.AndroidJUnitRunner"
            and test_identity.get("target_package") == APP and test_identity.get("version_code") == ""
            and test_identity.get("version_name") == "" and test_identity.get("certificate_sha256") == CERT
            and test_identity.get("min_sdk") == ["26"] and test_identity.get("target_sdk") == ["36"],
            "Accepted frozen test runner changed")
    extra_identity = identities.get("extra_qa", {})
    require(extra_identity.get("package") == "io.github.myflww.lovehouse.extraqa"
            and extra_identity.get("runner") == "io.github.myflww.lovehouse.upgradeqa.UpgradeProbeInstrumentation"
            and extra_identity.get("target_package") == APP and extra_identity.get("certificate_sha256") == CERT
            and extra_identity.get("version_code") == "1" and extra_identity.get("version_name") == "1"
            and extra_identity.get("min_sdk") == ["26"] and extra_identity.get("target_sdk") == ["36"]
            and report.get("extra_qa_identity") == extra_identity, "Accepted supplemental QA runner changed")
    transcripts = report.get("transcripts", {})
    require(isinstance(transcripts, dict) and "instrumentation.txt" in transcripts
            and len(transcripts) == len(modes) + 1, "Every probe and instrumentation transcript must be bound")
    require(set(transcripts) == {mode + "-probe.txt" for mode in modes} | {"instrumentation.txt"},
            "Transcript filenames do not match the fixed acceptance stages")
    probes = {}
    cases = None
    for name, digest in transcripts.items():
        require(name in files and bool(HEX64.fullmatch(str(digest))) and sha256(files[name]) == digest,
                "An acceptance transcript hash differs")
        text = files[name].decode("utf-8")
        if name == "instrumentation.txt":
            cases = checked_instrumentation(files[name], api)
        else:
            stage = name.removesuffix("-probe.txt")
            mode = "verify" if stage == "verify_restart" else stage
            result = parsed_probe(files[name], mode, api)
            result["transcript"] = name
            probes[stage] = result
    require(set(probes) == set(modes), "Supplemental transcript coverage is incomplete")
    require(typed_equal(supplemental.get("results"), [probes[mode] for mode in modes]),
            "Supplemental report differs from actual probe receipts")
    require(isinstance(report.get("frozen_test_names"), list)
            and sorted(report["frozen_test_names"], key=lambda item: (item["class"], item["test"])) == cases,
            "Reported frozen test identities differ from the raw runner")
    screenshots = report.get("screenshots", [])
    expected_images = {"android-smoke.png", "android-engine-smoke.png"} if full else {"android-smoke.png"}
    require(isinstance(screenshots, list) and len(screenshots) == len(expected_images)
            and {item.get("name") for item in screenshots} == expected_images, "Actual scope screenshots are missing")
    for screenshot in screenshots:
        raw = files.get(screenshot["name"], b"")
        require(type(screenshot.get("bytes")) is int and screenshot["bytes"] == len(raw)
                and screenshot.get("sha256") == sha256(raw), "Actual screenshot bytes changed")
        checked_png(raw)
    # Only reviewed fields, never arbitrary transcript text, are published.
    return {"api_level": api, "source_commit": SOURCE, "tested_apk": report["tested_apk"],
            "frozen_test_apk": report["frozen_test_apk"], "extra_qa_apk": report["extra_qa_apk"],
            "certificate_sha256": CERT, "upgrade_preservation": upgrade,
            "instrumentation_scope": report["instrumentation_scope"], "full_engine_verified": full,
            "partial": not full, "instrumentation": counts,
            "webview": {key: webview[key] for key in ("package", "version", "major")},
            "supplemental": {key: supplemental[key] for key in
                ("modes", "passed", "migration", "complete_engine_export_restore_saf", "credential_process_restart_delete")},
            "transcripts": transcripts, "frozen_test_names": cases,
            "screenshots": [{key: image[key] for key in ("name", "bytes", "sha256")} for image in screenshots], "model_calls": 0}


def collect_assets(metadata, archives, workflow_evidence):
    require(set(archives) == {28, 36}, "Exactly two API artifact archives are required")
    reports = {}
    receipt = None
    app = None
    for api in (28, 36):
        files = checked_archive(archives[api], metadata["artifacts"][str(api)])
        raw = files.get(SIGNING, files.get("original-signing-verification.json", b""))
        checked_signing_receipt(raw, metadata)
        require(receipt is None or receipt == raw, "API jobs did not use the same original signing receipt")
        receipt = raw
        reports[str(api)] = checked_evidence(files, api, metadata)
        require(app is None or app == files[APK], "API jobs did not test the same application bytes")
        app = files[APK]
    public = {"schema": "love-house-android-0106-public-verification/v1", "tag": TAG,
              "source_commit": SOURCE, "application_id": APP, "version_name": "0.10.6rc1", "version_code": 4,
              "minimum_sdk": 26, "target_sdk": 36, "abis": ["arm64-v8a", "x86_64"],
              "full_engine_minimum_webview_major": 109, "certificate_sha256": CERT,
              "signed_apk": {"name": APK, "bytes": APK_BYTES, "sha256": APK_HASH},
              "original_signing_receipt_sha256": SIGNING_HASH, "workflows": workflow_evidence,
              "build_artifact": metadata["build_artifact"], "acceptance_artifacts": metadata["artifacts"],
              "extra_qa_build_artifact": metadata["extra_qa_build_artifact"],
              "emulators": reports, "physical_android_phone_tested": False, "real_model_calls": 0,
              "api28_scope": "legacy_offline_and_webview_update_gate_only",
              "api36_scope": "full_engine_and_legacy_with_explicit_migration_export_restore_saf_and_keystore_restart",
              "operating_limits": ["64_bit_android_only", "full_engine_requires_webview_109_or_newer",
                                   "no_continuous_background_reception_guarantee", "cross_device_connections_require_accessible_own_service"],
              "original_release_assets": metadata["release_snapshot"]["assets"]}
    assets = {APK: app, SIGNING: receipt,
              EVIDENCE: (json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")}
    assets[CHECKSUMS] = "".join(sha256(raw) + "  " + name + "\n" for name, raw in sorted(assets.items())).encode("ascii")
    return assets


def appended_body(metadata):
    url = "https://github.com/" + REPOSITORY + "/actions/runs/" + str(metadata["acceptance_run"]["id"])
    section = (BEGIN + "\n## Android 0.10.6rc1 原签名安装包\n\n"
               "本节更新原正文中移动版 0.8.0rc2 的状态；Windows、macOS 与历史发布附件保持不变。"
               "Android 构建源码请使用[冻结提交 `732d7df`](https://github.com/myflww/love-house/tree/" + SOURCE + ")。\n\n"
               "[下载 Android APK](" + public_url(APK) + ")。Android 8.0+，仅支持 64 位 arm64-v8a / x86_64；"
               "完整记忆引擎需要 Android System WebView 109 或更新版本。使用原发行证书签名，"
               "包名保持 `" + APP + "`，versionCode 4，可覆盖旧 0.8.0rc2；升级前请备份，保留原应用数据。\n\n"
               "实际原签名旧包经过双库写入、覆盖安装与关闭后重启核对。Android 9 / API28 的旧 WebView "
               "验证了旧离线入口和内核更新提示，7 项测试无跳过；没有声称已在该旧内核运行完整引擎。"
               "Android 16 / API36 完整引擎 11 项测试无跳过，另验证明确迁移、重复迁移去重、导出恢复、"
               "系统文件保存及合成凭据跨进程重启和删除。均为模拟器验收，未做实体手机或真实付费模型测试。\n\n"
               "关闭完整界面后不保证持续接收，系统省电或结束进程可能停止本机接收；跨设备接入仍需可访问的自有服务。QA-only 和未签名包不作为用户安装包提供。\n\n"
               "APK SHA-256：`" + APK_HASH + "`。原证书 SHA-256：`" + CERT + "`。"
               "请使用新增 `Android-SHA256SUMS.txt` 核对，原有 `SHA256SUMS.txt` 保持原样。"
               "[实际覆盖升级与测试记录](" + url + ")，本页另附原签名报告和分系统验收报告。\n" + END)
    return metadata["release_snapshot"]["body"] + "\n\n" + section + "\n"


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        require(request.get_method() == "GET" and parsed.scheme == "https" and not parsed.username and not parsed.password
                and (parsed.hostname in {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                                        "github-releases.githubusercontent.com"}
                     or str(parsed.hostname).endswith(".blob.core.windows.net")), "Unexpected binary download redirect")
        # Reconstruct the request so repository bearer tokens never reach storage.
        return urllib.request.Request(newurl, headers={"User-Agent": "LoveHouse-Android-0106-Publisher"})


class GitHub:
    def __init__(self, token):
        require(isinstance(token, str) and bool(token), "A repository workflow token is required")
        self.token = token
        self.opener = urllib.request.build_opener(SafeRedirect())

    def api(self, method, path, *, payload=None, content=None, binary_bytes=None):
        read_allowed = path.startswith(BASE + "/actions/") or path in {RELEASE_API, BASE + "/git/ref/tags/" + TAG}
        read_allowed |= path == RELEASE_API + "/assets?per_page=100"
        write_upload = path.startswith(RELEASE_API + "/assets?name=")
        require((method == "GET" and read_allowed) or (method == "POST" and write_upload and payload is None)
                or (method == "PATCH" and path == RELEASE_API and isinstance(payload, dict) and set(payload) == {"body"}),
                "Request is outside the append-only publication interface")
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "LoveHouse-Android-0106-Publisher"}
        if payload is not None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if content is not None and payload is None:
            headers["Content-Type"] = "application/octet-stream"
        # Artifact ZIP endpoints require GitHub's JSON API Accept header even
        # though they redirect to ZIP bytes. The storage redirect has no token.
        origin = "https://uploads.github.com" if write_upload else "https://api.github.com"
        request = urllib.request.Request(origin + path, headers=headers, data=content, method=method)
        try:
            with self.opener.open(request, timeout=180) as response:
                raw = response.read((binary_bytes + 1) if binary_bytes is not None else 2 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            # The route contains only reviewed repository identifiers. Emit no
            # response body, redirect URL, request header or token.
            route = path.split("?", 1)[0].removeprefix(BASE)
            raise PublicationError("GitHub " + method + " " + route + " returned HTTP " + str(error.code)) from None
        except urllib.error.URLError:
            raise PublicationError("GitHub transport could not complete a reviewed repository request") from None
        if binary_bytes is not None:
            require(len(raw) == binary_bytes, "Artifact download size differs")
            return raw
        return strict_json(raw)

    def anonymous(self, url, size):
        require(url in {public_url(name) for name in ASSET_NAMES}, "Anonymous download is outside the four reviewed assets")
        request = urllib.request.Request(url, headers={"User-Agent": "LoveHouse-Android-0106-Public-Download"})
        try:
            with self.opener.open(request, timeout=180) as response:
                raw = response.read(size + 1)
        except (urllib.error.HTTPError, urllib.error.URLError):
            raise PublicationError("Anonymous public download failed") from None
        require(len(raw) == size, "Anonymous public download size differs")
        return raw


def checked_current_release(client, metadata):
    checked_tag(client.api("GET", BASE + "/git/ref/tags/" + TAG))
    release = client.api("GET", RELEASE_API)
    checked_release(release)
    require(release.get("body") in {metadata["release_snapshot"]["body"], appended_body(metadata)},
            "Release text changed outside the reviewed append")
    return release, checked_asset_map(metadata, client.api("GET", RELEASE_API + "/assets?per_page=100"))


def publish(client, metadata, assets):
    require(set(assets) == ASSET_NAMES, "Only the four reviewed public assets may be appended")
    require(len(assets[APK]) == APK_BYTES and sha256(assets[APK]) == APK_HASH
            and sha256(assets[SIGNING]) == SIGNING_HASH, "Public APK or original receipt bytes changed")
    release, existing = checked_current_release(client, metadata)
    # Check every collision before making any write. Existing names are accepted
    # only when their metadata and unauthenticated bytes match exactly.
    for name, raw in assets.items():
        if name in existing:
            item = existing[name]
            require(integer(item.get("id")) and type(item.get("size")) is int and item.get("size") == len(raw)
                    and item.get("digest") == "sha256:" + sha256(raw) and item.get("state") == "uploaded"
                    and item.get("browser_download_url") == public_url(name), "An Android asset name conflicts")
            require(client.anonymous(public_url(name), len(raw)) == raw, "Existing Android asset bytes conflict")
    # Upload executable last, so a partial network failure cannot leave a newly
    # recommended APK without its verification documents and checksums.
    ordered = sorted(ASSET_NAMES - {APK}) + [APK]
    for name in ordered:
        if name in existing:
            continue
        checked_current_release(client, metadata)
        raw = assets[name]
        item = client.api("POST", RELEASE_API + "/assets?name=" + urllib.parse.quote(name, safe=""), content=raw)
        require(item.get("name") == name and integer(item.get("id")) and type(item.get("size")) is int
                and item.get("size") == len(raw) and item.get("digest") == "sha256:" + sha256(raw)
                and item.get("state") == "uploaded" and item.get("browser_download_url") == public_url(name),
                "Uploaded asset identity differs")
        require(client.anonymous(public_url(name), len(raw)) == raw, "Uploaded asset failed anonymous byte verification")
    latest, final = checked_current_release(client, metadata)
    require(set(final) == {item["name"] for item in metadata["release_snapshot"]["assets"]} | ASSET_NAMES,
            "Complete append-only public asset set is missing")
    require(latest["body"] == release["body"], "Release text changed during upload; no body edit applied")
    desired = appended_body(metadata)
    if latest["body"] != desired:
        patched = client.api("PATCH", RELEASE_API, payload={"body": desired})
        checked_release(patched)
        require(patched.get("body") == desired, "Android release note append failed")
    checked_current_release(client, metadata)
    checks = {}
    for name, raw in sorted(assets.items()):
        downloaded = client.anonymous(public_url(name), len(raw))
        require(downloaded == raw, "Final anonymous asset download differs")
        checks[name] = {"bytes": len(raw), "sha256": sha256(raw), "anonymous_download": "passed"}
    return {"ok": True, "published": True, "release_url": "https://github.com/" + REPOSITORY + "/releases/tag/" + TAG,
            "original_assets_preserved": 11, "public_assets": checks}


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=root / "scripts/android-0106-publication.json")
    parser.add_argument("--output", type=Path, default=root / "build/android0106-publication")
    parser.add_argument("--publish", action="store_true", help="Explicitly append only after all immutable evidence passes")
    args = parser.parse_args(argv)
    try:
        require(args.metadata.is_file() and not args.metadata.is_symlink(), "Publication metadata is not an ordinary file")
        metadata = checked_metadata(strict_json(args.metadata.read_bytes()))
        if args.publish:
            require(metadata["publish_enabled"] is True and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
                    and os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH
                    and os.environ.get("GITHUB_EVENT_NAME") in {"push", "workflow_dispatch"}
                    and str(os.environ.get("GITHUB_RUN_ID", "")).isdigit(), "Publication is not explicitly enabled in the reviewed workflow")
        client = GitHub(os.environ.get("GITHUB_TOKEN", ""))
        checked_current_release(client, metadata)
        workflows = {"build": checked_run(client, metadata["build_run"]),
                     "supplemental_qa_build": checked_run(client, metadata["extra_qa_build_run"]),
                     "acceptance": checked_run(client, metadata["acceptance_run"])}
        checked_artifact_listing(client, metadata["build_run"], [metadata["build_artifact"]])
        checked_artifact_listing(client, metadata["extra_qa_build_run"], [metadata["extra_qa_build_artifact"]])
        checked_artifact_listing(client, metadata["acceptance_run"], list(metadata["artifacts"].values()))
        archives = {api: client.api("GET", BASE + "/actions/artifacts/" + str(metadata["artifacts"][str(api)]["id"]) + "/zip",
                                   binary_bytes=metadata["artifacts"][str(api)]["bytes"]) for api in (28, 36)}
        assets = collect_assets(metadata, archives, workflows)
        require(not args.output.exists() and args.output.resolve().is_relative_to(root.resolve()),
                "Output must be a new owned build directory")
        args.output.mkdir(parents=True)
        for name, raw in assets.items():
            (args.output / name).write_bytes(raw)
        result = publish(client, metadata, assets) if args.publish else {
            "ok": True, "published": False, "validation": "passed", "public_assets": {
                name: {"bytes": len(raw), "sha256": sha256(raw)} for name, raw in sorted(assets.items())}}
        (args.output / "publication-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        result = {"ok": False, "published": False, "error": "Android append-only publication did not complete",
                  "exception": type(exc).__name__}
        if isinstance(exc, PublicationError):
            result["detail"] = str(exc)
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    sys.exit(main())
