#!/usr/bin/env python3
"""Sign BOTH frozen Android release inputs with the ORIGINAL private key.

Run on the computer which already holds that key. Passwords are entered with
echo disabled and passed only through apksigner stdin. No key generation,
network request, upload, old-app uninstall or automatic device installation.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import warnings
import zipfile

from verify_android_release import badging_identity, instrumentation_identity, signer_digest

SCHEMA = "love-house-android-signing-input/v1"
APP_ID = "io.github.myflww.lovehouse.preview"
ORIGINAL_CERT = "ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc"
MAX_APK_BYTES = 150 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_ZIP_TOTAL = 512 * 1024 * 1024


REPORT = "Android-original-signing-verification.json"


class SigningError(ValueError):
    """Controlled error: never contains a password, tool output or private path."""


def run(command, *, passwords=None, require_success=True):
    try:
        result = subprocess.run([str(item) for item in command], input=passwords,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=180, check=False)
    except (OSError, subprocess.SubprocessError):
        raise SigningError("An Android tool could not complete; no signed handoff was delivered") from None
    if require_success and result.returncode:
        raise SigningError("An Android tool rejected the operation; no signed handoff was delivered")
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


def _unique_object(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise SigningError("Input manifest contains a repeated field")
        value[name] = item
    return value


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _input_file(root, record, maximum):
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise SigningError("Input artifact metadata has unexpected or missing fields")
    name = record["path"]
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        raise SigningError("Input artifact paths must be portable relative paths")
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise SigningError("Input artifact path escapes the handoff directory")
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents
                                if parent != root and parent.is_relative_to(root)):
        raise SigningError("Input artifact paths must not contain symbolic links")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise SigningError("A frozen handoff artifact is missing")
    if type(record["bytes"]) is not int or not 0 < record["bytes"] <= maximum:
        raise SigningError("Input artifact size is outside the reviewed budget")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record["sha256"])):
        raise SigningError("Input artifact SHA-256 is invalid")
    if path.stat().st_size != record["bytes"] or _digest(path) != record["sha256"]:
        raise SigningError("Input artifact differs from the frozen size or SHA-256")
    return path


def load_manifest(path, expected_source, expected_version, expected_code):
    if (not isinstance(expected_version, str)
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.-]*', expected_version)
            or type(expected_code) is not int or not 0 < expected_code < 2100000000):
        raise SigningError("Supply the exact reviewed portable Android version name and code")
    if not re.fullmatch(r"[0-9a-f]{40}", str(expected_source)) or expected_source == "0" * 40:
        raise SigningError("Supply the nonzero source commit confirmed by the build handoff")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise SigningError("Signing input manifest is missing or exceeds its size budget")
    try:
        value = json.loads(path.read_text("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError):
        raise SigningError("Signing input manifest is not valid UTF-8 JSON") from None
    expected_fields = {"schema", "source_commit", "application_id", "version_name", "version_code",
                       "certificate_sha256", "apk", "test_apk", "source_archive"}
    if not isinstance(value, dict) or set(value) != expected_fields or value["schema"] != SCHEMA:
        raise SigningError("Signing input manifest has unexpected or missing fields")
    if value["source_commit"] != expected_source:
        raise SigningError("Source commit differs from the explicitly confirmed build handoff")
    if (value["application_id"], value["version_name"], value["version_code"], value["certificate_sha256"]) != (
            APP_ID, expected_version, expected_code, ORIGINAL_CERT) or type(value["version_code"]) is not int:
        raise SigningError("Signing input manifest is not the explicitly expected original-signer upgrade")
    root = path.resolve().parent
    inputs = {name: _input_file(root, value[name], MAX_SOURCE_BYTES if name == "source_archive" else MAX_APK_BYTES)
              for name in ("apk", "test_apk", "source_archive")}
    if len(set(inputs.values())) != 3 or value["apk"]["sha256"] == value["test_apk"]["sha256"]:
        raise SigningError("App, QA instrumentation and source archive must be distinct inputs")
    # Inspect without extracting. The source archive hash binds this handoff to
    # the developer-supplied source snapshot; it is not an independent rebuild.
    archive_payload(inputs["source_archive"], apk=False)
    for name in ("apk", "test_apk"):
        archive_payload(inputs[name])
    return value, inputs


def archive_payload(path, *, apk=True):
    entries = {}
    total = 0
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > 20000:
            raise SigningError("Archive contains too many entries")
        seen = set()
        for item in archive.infolist():
            name = item.filename
            if name in seen or "\\" in name or ":" in name or "\0" in name:
                raise SigningError("Archive contains ambiguous paths")
            seen.add(name)
            trimmed = name[:-1] if name.endswith("/") else name
            if not trimmed or PurePosixPath(trimmed).is_absolute() or any(
                    part in ("", ".", "..") for part in trimmed.split("/")):
                raise SigningError("Archive contains a nonportable path")
            if (item.external_attr >> 16) & 0o170000 == 0o120000 or item.flag_bits & 1:
                raise SigningError("Archive contains a symlink or encrypted entry")
            total += item.file_size
            if item.file_size > MAX_APK_BYTES or total > MAX_ZIP_TOTAL:
                raise SigningError("Archive uncompressed data exceeds the reviewed budget")
            if item.is_dir():
                continue
            digest = hashlib.sha256()
            length = 0
            with archive.open(item) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    length += len(block)
                    if length > item.file_size:
                        raise SigningError("Archive entry exceeds its declared size")
                    digest.update(block)
            if length != item.file_size:
                raise SigningError("Archive entry is incomplete")
            # apksigner may replace V1 signature files. Everything else,
            # including the manifest, DEX and embedded engine must stay exact.
            signature = re.fullmatch(r"META-INF/[^/]+\.(?:SF|RSA|DSA|EC)", name, re.I)
            if apk and (name.upper() == "META-INF/MANIFEST.MF" or signature):
                continue
            entries[name] = {"bytes": length, "sha256": digest.hexdigest()}
    if not entries or (apk and "AndroidManifest.xml" not in entries):
        raise SigningError("Input archive is empty or is not an Android package")
    return entries


def apk_identity(aapt, path, version, code, *, instrumentation=False):
    _, text = run([aapt, "dump", "badging", path])
    value = badging_identity(text)
    # Gradle's actual androidTest manifest has no version attributes; aapt
    # reports both as empty strings. Do not pretend it is the release app.
    expected = (APP_ID + ".test", "", "") if instrumentation else (APP_ID, str(code), version)
    if (value["package"], value["version_code"], value["version_name"]) != expected:
        raise SigningError("APK package or version differs from its fixed app/QA identity")
    if value["min_sdk"] != ["26"] or value["target_sdk"] != ["36"]:
        raise SigningError("APK SDK metadata differs from the reviewed Android build")
    if instrumentation:
        _, xml = run([aapt, "dump", "xmltree", path, "AndroidManifest.xml"])
        instrumentation_identity(xml)
    return value


def sign(args, *, prompt=getpass.getpass):
    manifest_path = args.manifest.expanduser().absolute()
    value, inputs = load_manifest(manifest_path, args.expected_source_commit, args.expected_version_name, args.expected_version_code)
    version, version_code = value["version_name"], value["version_code"]
    output_app = f"LoveHouse-{version}-Android.apk"
    output_test = f"LoveHouse-{version}-Android-QA-ONLY.apk"
    manifest_hash = _digest(manifest_path)
    output = args.output_dir.expanduser().absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise SigningError("Choose a fresh output directory beneath an existing parent")
    if output.parent.is_symlink():
        raise SigningError("Output parent must not be a symbolic link")
    tools = args.build_tools.expanduser().resolve()
    java = Path(args.java).expanduser().resolve() if args.java else Path(shutil.which("java") or "")
    keystore = args.keystore.expanduser().resolve()
    suffix = ".exe" if os.name == "nt" else ""
    aapt, zipalign = tools / ("aapt" + suffix), tools / ("zipalign" + suffix)
    jar = tools / "lib/apksigner.jar"
    if not isinstance(args.alias, str) or not args.alias.strip() or any(char in args.alias for char in "\0\r\n"):
        raise SigningError("Supply the existing original signing-key alias")
    for path in (java, keystore, aapt, zipalign, jar):
        if not path.is_file():
            raise SigningError("Required local Java, Android tools or original keystore is unavailable")
    public_tool_hash = _digest(jar)
    identities, payloads = {}, {}
    for name in ("apk", "test_apk"):
        identities[name] = apk_identity(aapt, inputs[name], version, version_code, instrumentation=name == "test_apk")
        run([zipalign, "-c", "-P", "16", "4", inputs[name]])
        code, _ = run([java, "-Dfile.encoding=UTF-8", "-jar", jar, "verify", inputs[name]], require_success=False)
        if name == "apk" and code == 0:
            raise SigningError("Release input is already signed; use the frozen unsigned release APK")
        payloads[name] = archive_payload(inputs[name])
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        store_password = prompt("Original keystore password (hidden): ")
        key_password = prompt("Original key password (hidden; Enter = same): ") or store_password
    if not store_password or any(char in password for password in (store_password, key_password) for char in "\r\n\0"):
        raise SigningError("Password is empty or cannot be passed as one hidden stdin line")
    passwords = (store_password + "\n" + key_password + "\n").encode("utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix=".love-house-release-sign-", dir=output.parent) as temporary:
            stage = Path(temporary)
            signed_records = {}
            for name, filename in (("apk", output_app), ("test_apk", output_test)):
                target = stage / filename
                run([java, "-Dfile.encoding=UTF-8", "-jar", jar, "sign", "--ks", keystore,
                     "--ks-key-alias", args.alias, "--ks-pass", "stdin", "--key-pass", "stdin",
                     "--pass-encoding", "utf-8", "--v4-signing-enabled", "false", "--out", target, inputs[name]],
                    passwords=passwords)
                _, certificate = run([java, "-Dfile.encoding=UTF-8", "-jar", jar, "verify", "--verbose", "--print-certs", target])
                if signer_digest(certificate) != ORIGINAL_CERT:
                    raise SigningError("Signer is not the ORIGINAL public certificate; nothing was delivered")
                if apk_identity(aapt, target, version, version_code, instrumentation=name == "test_apk") != identities[name]:
                    raise SigningError("Signed APK metadata changed unexpectedly")
                run([zipalign, "-c", "-P", "16", "4", target])
                if archive_payload(target) != payloads[name]:
                    raise SigningError("Signing changed the APK payload beyond signature metadata")
                signed_records[name] = {"path": filename, "bytes": target.stat().st_size,
                                        "sha256": _digest(target), "certificate_sha256": ORIGINAL_CERT,
                                        "identity": identities[name], "qa_only": name == "test_apk"}
            # Detect replacement of any handoff artifact during password entry
            # or signing. Never emit a receipt for bytes not actually checked.
            for name in inputs:
                if inputs[name].stat().st_size != value[name]["bytes"] or _digest(inputs[name]) != value[name]["sha256"]:
                    raise SigningError("A frozen input changed during signing")
            if _digest(manifest_path) != manifest_hash:
                raise SigningError("Signing input manifest changed during signing")
            result = {"schema": "love-house-android-original-signing/v1", "source_commit": value["source_commit"],
                      "source_commit_check": "matched_explicit_expected_commit_and_developer_handoff",
                      "independent_rebuild_verified": False, "input_manifest_sha256": manifest_hash,
                      "application_id": APP_ID, "version_name": version, "version_code": version_code,
                      "certificate_sha256": ORIGINAL_CERT, "apksigner_jar_sha256": public_tool_hash,
                      "source_archive": value["source_archive"], "inputs": {key: value[key] for key in ("apk", "test_apk")},
                      "signed": signed_records, "same_original_signer": True, "payload_preserved": True,
                      "signature_and_metadata": "passed", "device_upgrade_verified": False, "published": False}
            (stage / REPORT).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            output.mkdir()  # Never replace an existing handoff, even an empty one.
            created = []
            try:
                for filename in (output_app, output_test, REPORT):
                    path = output / filename
                    with path.open("xb") as stream:
                        created.append(path)
                        with (stage / filename).open("rb") as source:
                            shutil.copyfileobj(source, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
            except BaseException:
                for path in created:
                    path.unlink(missing_ok=True)
                try:
                    output.rmdir()
                except OSError:
                    pass
                raise
            return result
    finally:
        passwords = None
        store_password = ""
        key_password = ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="Frozen Android-signing-input.json")
    parser.add_argument("--expected-source-commit", required=True, help="Exact nonzero commit confirmed in the source/build handoff")
    parser.add_argument("--expected-version-name", required=True, help="Exact reviewed version name")
    parser.add_argument("--expected-version-code", required=True, type=int, help="Exact increasing Android version code")
    parser.add_argument("--build-tools", required=True, type=Path, help="Official Android SDK build-tools/36.0.0 directory")
    parser.add_argument("--java", type=Path, help="Java 17+ executable; otherwise use PATH")
    parser.add_argument("--keystore", required=True, type=Path, help="Existing ORIGINAL private keystore on this computer; never copied")
    parser.add_argument("--alias", required=True, help="Existing original key alias; no new key or alias is generated")
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory for signed app, QA-only instrumentation and public receipt")
    args = parser.parse_args()
    try:
        result = sign(args)
    except (SigningError, ValueError, OSError, zipfile.BadZipFile, EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        parser.exit(1, "Signing did not deliver two verified original-signer APKs. Check the frozen handoff, local tools and original key; no release was published.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
