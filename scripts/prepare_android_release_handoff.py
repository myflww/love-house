#!/usr/bin/env python3
"""Package a frozen, scanned Android release ORIGINAL-signer handoff.

This creates developer inputs, not a signed installable release. It never
reads a keystore/password, signs, uploads, installs, or makes a network request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

import prepare_public_release as public
from sign_android_release import (APP_ID, MAX_APK_BYTES, ORIGINAL_CERT, SCHEMA,
                               archive_payload, load_manifest)
from android_release_identity import release_identity

ROOT = Path(__file__).resolve().parents[1]
INPUT_MANIFEST = "Android-signing-input.json"
REPORT = "Android-handoff-verification.json"
COPY_FILES = (
    "scripts/sign_android_release.py",
    "scripts/android_release_identity.py",
    "scripts/verify_android_release.py",
    "docs/ANDROID-SIGNING-HANDOFF.md",
    "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md",
)


class HandoffError(ValueError):
    """Controlled error, never includes rejected content or a private path."""


def git(root, *arguments):
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        raise HandoffError("Local Git source verification could not complete") from None
    if result.returncode:
        raise HandoffError("Local Git source verification failed")
    return result.stdout.decode("utf-8", errors="strict")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _ordinary(path, *, maximum=None):
    original = Path(path).expanduser().absolute()
    if original.is_symlink() or any(parent.is_symlink() for parent in original.parents):
        raise HandoffError("Handoff paths must not contain symbolic links")
    if not original.is_file():
        raise HandoffError("A required handoff input is missing")
    if maximum is not None and not 0 < original.stat().st_size <= maximum:
        raise HandoffError("Handoff input is empty or exceeds its reviewed size budget")
    return original.resolve()


def _public_path(name):
    path = Path(name)
    return public.is_allowed(path) or name == "PUBLIC_SOURCE_MANIFEST.json"


def frozen_source(root, expected_source=None):
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise HandoffError("Source root must not contain symbolic links")
    if not root.is_dir() or Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
        raise HandoffError("Source must be the exact local Git repository root")
    commit = git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or commit == "0" * 40:
        raise HandoffError("Source has no frozen nonzero commit")
    if expected_source is not None and (not re.fullmatch(r"[0-9a-f]{40}", expected_source)
                                        or expected_source != commit):
        raise HandoffError("Source HEAD differs from the explicitly expected commit")
    changed = [name for name in git(root, "diff", "--name-only", "-z", "HEAD", "--").split("\0") if name]
    untracked = [name for name in git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if name]
    if any(_public_path(name) for name in changed + untracked):
        raise HandoffError("Commit all reviewed public source changes before packaging")
    tracked = set(name for name in git(root, "ls-files", "-z").split("\0") if name)
    files, findings = public.collect(root)
    if findings:
        raise HandoffError("Public source scanning rejected the snapshot")
    # collect intentionally ignores generated build outputs. An ignored file
    # which is nevertheless an allowed source must not sneak into the export.
    if any(path.as_posix() not in tracked for path in files):
        raise HandoffError("An ignored or untracked public source file would enter the snapshot")
    return commit, files


def deterministic_source_zip(source, destination, files):
    names = sorted([path.as_posix() for path in files] + ["PUBLIC_SOURCE_MANIFEST.json"])
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            path = source / name
            if path.is_symlink() or not path.is_file():
                raise HandoffError("Prepared source changed before archive creation")
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            mode = 0o100755 if path.suffix in {".sh", ".command"} else 0o100644
            entry.external_attr = mode << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def file_record(root, relative):
    path = root / relative
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def prepare(source, unsigned_apk, instrumentation_apk, output, *, expected_source=None):
    root = Path(source).expanduser().absolute()
    commit, original_files = frozen_source(root, expected_source)
    version, code = release_identity(root)
    source_name = f"LoveHouse-{version}-Android-source.zip"
    app_name = f"artifacts/LoveHouse-{version}-Android-UNSIGNED.apk"
    test_name = f"artifacts/LoveHouse-{version}-Android-QA-INPUT.apk"
    app = _ordinary(unsigned_apk, maximum=MAX_APK_BYTES)
    test = _ordinary(instrumentation_apk, maximum=MAX_APK_BYTES)
    if app == test or digest(app) == digest(test):
        raise HandoffError("Release and instrumentation APKs must be different reviewed inputs")
    for apk in (app, test):
        if apk.suffix.lower() != ".apk":
            raise HandoffError("Both Android build inputs must be APK files")
        archive_payload(apk)  # Read/CRC/hash only: never extract or execute an APK.
    original_apks = {"apk": {"bytes": app.stat().st_size, "sha256": digest(app)},
                     "test_apk": {"bytes": test.stat().st_size, "sha256": digest(test)}}
    destination = Path(output).expanduser().absolute()
    if (destination.exists() or destination.is_symlink() or not destination.parent.is_dir()
            or any(parent.is_symlink() for parent in destination.parents)):
        raise HandoffError("Choose a fresh output directory beneath an existing real parent")
    # Writing an export inside a source subtree would make that source dirty and
    # could recurse into its own output. Owned build/outputs handoff paths are OK.
    if destination.is_relative_to(root) and destination.relative_to(root).parts[0] in public.ROOT_DIRS:
        raise HandoffError("Use a generated build/outputs directory, not a public source subtree")
    with tempfile.TemporaryDirectory(prefix=".android-release-handoff-", dir=destination.parent) as temporary:
        workspace = Path(temporary)
        clean_source = workspace / "source"
        result = public.prepare(root, clean_source)
        if result.get("ok") is not True:
            raise HandoffError("Public source preparation rejected the snapshot")
        exported, findings = public.collect(clean_source, staged=True)
        findings.extend(public.verify_manifest(clean_source, exported))
        if findings or {path.as_posix() for path in exported} != {path.as_posix() for path in original_files}:
            raise HandoffError("Prepared source or its regenerated public manifest failed verification")
        delivery = workspace / "delivery"
        delivery.mkdir()
        deterministic_source_zip(clean_source, delivery / source_name, exported)
        archive_payload(delivery / source_name, apk=False)
        for relative in COPY_FILES:
            reviewed = clean_source / relative
            if not reviewed.is_file() or reviewed.is_symlink() or public.scan_bytes(Path(relative), reviewed.read_bytes()):
                raise HandoffError("A required signing helper, handoff document or notice failed review")
            target = delivery / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reviewed, target)
        for source_path, relative in ((app, app_name), (test, test_name)):
            target = delivery / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
        manifest = {"schema": SCHEMA, "source_commit": commit, "application_id": APP_ID,
                    "version_name": version, "version_code": code,
                    "certificate_sha256": ORIGINAL_CERT, "apk": file_record(delivery, app_name),
                    "test_apk": file_record(delivery, test_name),
                    "source_archive": file_record(delivery, source_name)}
        for name in ("apk", "test_apk"):
            if any(manifest[name][field] != original_apks[name][field] for field in ("bytes", "sha256")):
                raise HandoffError("An APK changed while the handoff was being prepared")
        _write_json(delivery / INPUT_MANIFEST, manifest)
        load_manifest(delivery / INPUT_MANIFEST, commit, version, code)
        # Source code may not be edited or committed during export. APK outputs
        # are reviewed independently; this is not an independent rebuild proof.
        final_commit, final_files = frozen_source(root, commit)
        if final_commit != commit or final_files != original_files:
            raise HandoffError("Frozen source changed during handoff preparation")
        report = {"schema": "love-house-android-handoff/v1", "source_commit": commit,
                  "source_public_scan": "passed", "source_manifest_verified": True,
                  "source_files": len(exported), "deterministic_source_archive": manifest["source_archive"],
                  "input_apks": {key: manifest[key] for key in ("apk", "test_apk")},
                  "artifact_role": "developer_original_signer_inputs_only",
                  "apk_signature_verified_by_packager": False,
                  "independent_rebuild_verified": False, "original_key_signed": False,
                  "device_upgrade_verified": False, "published": False}
        _write_json(delivery / REPORT, report)
        receipts = [file_record(delivery, path.relative_to(delivery).as_posix())
                    for path in sorted(delivery.rglob("*")) if path.is_file()]
        (delivery / "SHA256SUMS.txt").write_text(
            "".join(item["sha256"] + "  " + item["path"] + "\n" for item in receipts),
            encoding="utf-8", newline="\n")
        # The destination is fresh. Claim it atomically before moving any file;
        # no existing handoff is ever replaced, even if another process created it.
        destination.mkdir()
        created = []
        try:
            for child in sorted(delivery.iterdir()):
                target = destination / child.name
                shutil.move(str(child), str(target))
                created.append(target)
        except BaseException:
            for path in created:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            try:
                destination.rmdir()
            except OSError:
                pass
            raise
    return {"ok": True, "schema": report["schema"], "source_commit": commit,
            "source_files": report["source_files"], "original_key_signed": False,
            "device_upgrade_verified": False, "published": False,
            "files": receipts + [file_record(destination, "SHA256SUMS.txt")]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT, help="Exact clean Git repository root")
    parser.add_argument("--expected-source-commit", help="Optional exact nonzero HEAD commit to confirm")
    parser.add_argument("--unsigned-apk", required=True, type=Path, help="Reviewed unsigned release APK; never a public download")
    parser.add_argument("--instrumentation-apk", required=True, type=Path, help="Reviewed developer QA APK, optionally debug signed")
    parser.add_argument("--output", required=True, type=Path, help="Fresh handoff directory with an existing parent")
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.unsigned_apk, args.instrumentation_apk, args.output,
                         expected_source=args.expected_source_commit)
    except (ValueError, OSError, UnicodeError, zipfile.BadZipFile, subprocess.SubprocessError):
        parser.exit(1, "Handoff preparation failed. Check clean committed source, reviewed inputs and a fresh output directory; nothing was signed, installed or published.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
