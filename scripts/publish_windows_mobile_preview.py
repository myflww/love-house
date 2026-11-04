"""Publish the already tested preview bytes; never rebuild or replace stable assets."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

REPO = "myflww/love-house"
SOURCE = "382c5ee45f66016af7117c2ad5a9c16cc2a75f9e"
MERGE = "730cfb01d70d2eda62104c5ad8e46eac1e355069"
TAG = "v0.8.0rc1"
RUNS = (41021442005, 41021442002, 41021442140, 41021442000,
        41021442251, 41021442101)
ARTIFACTS = (
    (12962400907, 41021442101,
     "0cd0871d516f03a83ff42cbb83de91239f95662490a6c9fbccc41510fd70906b"),
    (12961608750, 41021442101,
     "2c7ca808de1f23a314782cbbf5dc2475652bdaf276eea330c52c184f44225212"),
)
EXPECTED = {
    "LoveHouse-Setup-0.8.0rc1-Windows-x64.exe":
        "313ad4c15da5dd70b79d2da682f7a8c02c8c130cebb72a806dbeaef1e320819b",
    "LoveHouse-0.8.0rc1-Windows-x64.zip":
        "97e35675311edb4db6d51833663155213c97beb224a09c8e0c1f235901c17342",
    "Windows-SHA256SUMS.txt":
        "60ba1d458817489da189ecb2e487091bd05b11157cf00e9a51a2fcc4f9e1bb12",
    "FINAL-PROVENANCE.json":
        "17785de83485fa7cb2c916a88c2f2160846298318d48b49380373aabf6a498db",
    "Windows-test-evidence-382c5ee.zip":
        "2c7ca808de1f23a314782cbbf5dc2475652bdaf276eea330c52c184f44225212",
    "LoveHouse-0.8.0rc1-Original-Key-Portable-382c5ee.zip":
        "321f26138739efe006ac40ac921fcb9768dcfc6c6657ce3f891a5edddb9b7051",
}


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def api(path: str):
    return json.loads(gh("api", f"repos/{REPO}/{path}"))


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(path: Path, expected: str):
    if sha(path) != expected:
        raise RuntimeError(f"SHA256 mismatch: {path.name}")


def verify_tag(publication: str, *, required: bool = False):
    matches = api(f"git/matching-refs/tags/{TAG}")
    exact = next((ref for ref in matches if ref["ref"] == f"refs/tags/{TAG}"), None)
    if exact is None:
        if required:
            raise RuntimeError("Published source tag is missing")
        return
    obj = exact["object"]
    for _ in range(5):
        if obj["type"] != "tag":
            break
        obj = api(f"git/tags/{obj['sha']}")["object"]
    if obj["type"] != "commit" or obj["sha"] != publication:
        raise RuntimeError("Existing source tag points at another commit; refusing to overwrite")


def main():
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("Unexpected publication repository")
    if os.environ.get("GITHUB_REF") != "refs/heads/codex/mobile-agent-080":
        raise RuntimeError("Unexpected publication branch")
    publication = os.environ["GITHUB_SHA"]
    # Only add publication material to the tested source. Reject any production drift.
    comparison = api(f"compare/{SOURCE}...{publication}")
    if comparison.get("status") != "ahead" or comparison.get("total_commits", 0) > 10:
        raise RuntimeError("Publication commit is not a small descendant of tested source")
    allowed = ("release-handoff/0.8.0rc1/",)
    named = {".github/workflows/publish-windows-mobile-preview.yml",
             "scripts/publish_windows_mobile_preview.py", "docs/WINDOWS-MOBILE-080RC1.md"}
    files = comparison.get("files", [])
    if not files or len(files) >= 300 or any(
        f["filename"] not in named and not f["filename"].startswith(allowed) for f in files
    ):
        raise RuntimeError("Production source changed after tested candidate")
    for run_id in RUNS:
        run = api(f"actions/runs/{run_id}")
        if (run.get("head_sha") != SOURCE or run.get("status") != "completed"
                or run.get("conclusion") != "success"):
            raise RuntimeError(f"Original CI did not pass for exact source: {run_id}")

    with tempfile.TemporaryDirectory(prefix="love-house-publish-") as folder:
        output = Path(folder)
        for artifact_id, run_id, expected in ARTIFACTS:
            artifact = api(f"actions/artifacts/{artifact_id}")
            if (artifact.get("expired") or artifact.get("workflow_run", {}).get("id") != run_id
                    or artifact.get("workflow_run", {}).get("head_sha") != SOURCE
                    or artifact.get("digest") != f"sha256:{expected}"):
                raise RuntimeError(f"Artifact provenance mismatch: {artifact_id}")
            archive = output / f"{artifact_id}.zip"
            with archive.open("wb") as stream:
                subprocess.run(["gh", "api", f"repos/{REPO}/actions/artifacts/{artifact_id}/zip"],
                               check=True, stdout=stream)
            verify(archive, expected)
            with zipfile.ZipFile(archive) as zf:
                if zf.testzip():
                    raise RuntimeError("Artifact CRC failed")
                if artifact_id == ARTIFACTS[0][0]:
                    # Copy exactly the three expected installer entries; never extract paths.
                    for name in EXPECTED:
                        if name in zf.namelist():
                            (output / name).write_bytes(zf.read(name))
                else:
                    (output / "Windows-test-evidence-382c5ee.zip").write_bytes(archive.read_bytes())
            archive.unlink()
        handoff = Path("release-handoff/0.8.0rc1")
        for name in ("FINAL-PROVENANCE.json", "LoveHouse-0.8.0rc1-Original-Key-Portable-382c5ee.zip"):
            (output / name).write_bytes((handoff / name).read_bytes())
        for name, digest in EXPECTED.items():
            verify(output / name, digest)
        provenance = json.loads((output / "FINAL-PROVENANCE.json").read_text())
        if provenance["head_commit"] != SOURCE or provenance["checkout_merge_commit"] != MERGE:
            raise RuntimeError("Windows provenance does not identify exact tested source")
        portable = output / "LoveHouse-0.8.0rc1-Original-Key-Portable-382c5ee.zip"
        with zipfile.ZipFile(portable) as zf:
            if zf.testzip():
                raise RuntimeError("Portable signing handoff CRC failed")
            for item in json.loads(zf.read("FILES-SHA256.json"))["files"]:
                data = zf.read(item["path"])
                if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise RuntimeError("Portable handoff payload mismatch")
        (output / "Preview-SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in EXPECTED.items()), encoding="utf-8")
        (output / "WINDOWS-MOBILE-080RC1.md").write_bytes(Path("docs/WINDOWS-MOBILE-080RC1.md").read_bytes())
        expected_assets = {p.name: sha(p) for p in output.iterdir()}

        # Resume only our own draft for this exact publication. Never clobber an existing release.
        releases = api("releases?per_page=100")
        verify_tag(publication)
        existing = next((r for r in releases if r["tag_name"] == TAG), None)
        if existing:
            if not existing["draft"] or existing["target_commitish"] != publication:
                raise RuntimeError("Release already exists; no overwrite permitted")
        else:
            gh("release", "create", TAG, "--draft", "--prerelease", "--target", publication,
               "--title", "爱之屋 0.8.0rc1 · Windows 修复与移动端预览",
               "--notes-file", "docs/WINDOWS-MOBILE-080RC1.md")
        release = next(r for r in api("releases?per_page=100") if r["tag_name"] == TAG)
        assets = {a["name"]: a for a in release["assets"]}
        if set(assets) - set(expected_assets):
            raise RuntimeError("Unexpected existing asset; refusing to publish")
        for name, digest in expected_assets.items():
            if name in assets:
                if assets[name].get("digest") != f"sha256:{digest}":
                    raise RuntimeError(f"Existing asset mismatch: {name}")
            else:
                gh("release", "upload", TAG, str(output / name))
        uploaded = {a["name"]: a for a in api(f"releases/{release['id']}")["assets"]}
        if set(uploaded) != set(expected_assets) or any(
            uploaded[name].get("digest") != f"sha256:{digest}"
            for name, digest in expected_assets.items()
        ):
            raise RuntimeError("Remote uploaded bytes do not match verified local bytes")
        verify_tag(publication)
        gh("release", "edit", TAG, "--draft=false", "--prerelease", "--latest=false")
        final = api(f"releases/{release['id']}")
        if final["draft"] or not final["prerelease"]:
            raise RuntimeError("Published release state is incorrect")
        verify_tag(publication, required=True)
        print(final["html_url"])


if __name__ == "__main__":
    main()
