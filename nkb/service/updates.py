"""Small, optional GitHub release checker. Never downloads or installs a package.

The network request contains no memory, identity, connection, or API-key data.
Only the fixed public repository is contacted; UI links are rebuilt/validated
against that repository. Cached release notes are plain text, never HTML.
"""
from __future__ import annotations

import json
import platform
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .._version import __version__
from ..errors import ValidationError
from ..storage.jsonfile import JsonFileStorage

REPOSITORY = "https://github.com/myflww/love-house"
RELEASES_URL = REPOSITORY + "/releases"
API_URL = "https://api.github.com/repos/myflww/love-house/releases?per_page=40"
MAX_BYTES = 2 * 1024 * 1024
CHECK_INTERVAL = 24 * 60 * 60
ERROR_INTERVAL = 15 * 60
MANUAL_INTERVAL = 60
_VERSION = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
_LEGACY_PREVIEW = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(alpha|beta|rc|a|b)(\d+)$", re.IGNORECASE)


def version_key(value):
    """SemVer ordering, including numeric prerelease components (rc.10 > rc.2)."""
    if not isinstance(value, str) or len(value) > 100:
        return None
    # Existing published installers use Python/PEP 440 spellings such as
    # v0.5.1rc1. Keep their ordering compatible with future SemVer tags.
    legacy = _LEGACY_PREVIEW.fullmatch(value)
    if legacy:
        phase = {"a": "alpha", "alpha": "alpha", "b": "beta", "beta": "beta", "rc": "rc"}[legacy[4].lower()]
        value = ".".join(legacy.group(i) for i in (1, 2, 3)) + "-" + phase + "." + str(int(legacy[5]))
    match = _VERSION.fullmatch(value)
    if not match:
        return None
    pre = match[4]
    if pre and any(not item or item.isdigit() and len(item) > 1 and item[0] == "0"
                   for item in pre.split(".")):
        return None
    identifiers = tuple((0, int(item)) if item.isdigit() else (1, item)
                        for item in pre.split(".")) if pre else ()
    return tuple(int(match[i]) for i in (1, 2, 3)) + ((0, identifiers) if pre else (1, ()),)


def target_platform(system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    name = {"darwin": "macos", "macos": "macos", "windows": "windows", "linux": "linux"}.get(system, "other")
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("x86_64", "amd64", "x64") else machine
    return name, arch


def repository_url(value, kind):
    if not isinstance(value, str) or len(value) > 2000:
        return ""
    parts = urlsplit(value)
    decoded_path = unquote(parts.path)
    prefix = "/myflww/love-house/releases/" + ("download/" if kind == "asset" else "tag/")
    if (parts.scheme != "https" or parts.netloc != "github.com" or not parts.path.startswith(prefix)
            or parts.query or parts.fragment or "\\" in value or "\\" in decoded_path
            or any(segment in (".", "..") for segment in decoded_path.split("/"))
            or any(ord(c) < 32 for c in value + decoded_path)):
        return ""
    return value


def _asset_score(name, target, arch):
    lower = name.lower()
    # Prefer distributable packages, never source archives, debug files or checksums.
    if target == "macos":
        if not re.search(r"(?:macos|darwin|osx)", lower) or not lower.endswith((".dmg", ".zip")):
            return 0
        score = 30 if lower.endswith(".dmg") else 20
    elif target == "windows":
        if not re.search(r"(?:windows|win64|win32)", lower) or not lower.endswith((".exe", ".msi", ".zip")):
            return 0
        score = 30 if lower.endswith((".exe", ".msi")) else 20
        if "setup" in lower or "installer" in lower:
            score += 5
    elif target == "linux":
        if "linux" not in lower or not lower.endswith((".appimage", ".deb", ".rpm", ".tar.gz")):
            return 0
        score = 20
    else:
        return 0
    if any(item in lower for item in ("checksum", "sha256", "debug", "symbols", "source")):
        return 0
    asset_arch = "arm64" if re.search(r"(?:arm64|aarch64)", lower) else "x64" if re.search(r"(?:x64|x86_64|amd64)", lower) else "universal" if "universal" in lower else ""
    if asset_arch == arch:
        return score + 10
    if asset_arch == "universal":
        return score + 5
    # An unlabeled or wrong-architecture binary is not a safe update recommendation.
    return 0


def select_release(releases, target, arch, channel="stable"):
    """Select newest compatible release; a Windows-only RC is never a Mac update."""
    if not isinstance(releases, list) or len(releases) > 40:
        raise ValueError("Invalid release response")
    compatible = []
    other_versions = []
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") is not False:
            continue
        tag = item.get("tag_name")
        key = version_key(tag)
        if key is None:
            continue
        preview = item.get("prerelease") is True or key[3][0] == 0
        if channel == "stable" and preview:
            continue
        page = repository_url(item.get("html_url"), "release")
        if not page:
            continue
        assets = item.get("assets")
        if not isinstance(assets, list) or len(assets) > 100:
            continue
        candidates = []
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("state", "uploaded") != "uploaded":
                continue
            name = asset.get("name")
            if not isinstance(name, str) or len(name) > 255:
                continue
            score = _asset_score(name, target, arch)
            url = repository_url(asset.get("browser_download_url"), "asset")
            if score and url:
                candidates.append((score, name, url))
        if not candidates:
            other_versions.append((key, tag))
            continue
        _, asset_name, asset_url = max(candidates)
        release = {"version": tag.lstrip("v"), "tag": tag, "name": str(item.get("name") or tag)[:200],
                   "notes": str(item.get("body") or "")[:16000], "url": page,
                   "asset_name": asset_name, "asset_url": asset_url, "prerelease": preview,
                   "published_at": str(item.get("published_at") or "")[:40]}
        compatible.append((key, release))
    release = max(compatible, key=lambda pair: pair[0])[1] if compatible else None
    other = max(other_versions, key=lambda pair: pair[0])[1] if other_versions else None
    return release, other


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Release API redirected unexpectedly")


def fetch_releases(url, *, timeout, max_bytes):
    if url != API_URL:
        raise ValueError("Only the public Love House release API is allowed")
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "LoveHouse-Version-Check"})
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("Release response too large")
    return json.loads(payload)


class UpdateChecker:
    def __init__(self, root, *, version=__version__, system=None, machine=None, transport=None, clock=None):
        self.version = version
        self.target, self.arch = target_platform(system, machine)
        self.storage = JsonFileStorage(Path(root) / "updates.json")
        self.transport = transport or fetch_releases
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._request_thread = None
        self._checking = False
        self._generation = 0
        self._settings = {"auto_check": True, "channel": "stable"}
        self._cache = {"checked_at": None, "last_attempt": None, "release": None,
                       "other_version": None, "error": None}
        self._load()

    def _load(self):
        try:
            if self.storage.path.stat().st_size > 64000:
                return
            data = self.storage.load()
            if type(data.get("auto_check")) is bool:
                self._settings["auto_check"] = data["auto_check"]
            if data.get("channel") in ("stable", "preview"):
                self._settings["channel"] = data["channel"]
            if data.get("platform") != self.target or data.get("architecture") != self.arch:
                return
            now = self.clock()
            for key in ("checked_at", "last_attempt"):
                value = data.get(key)
                if type(value) in (int, float) and 0 <= value <= now + 300:
                    self._cache[key] = value
            release = data.get("release")
            if isinstance(release, dict) and version_key(release.get("tag")):
                # Re-run the same platform, channel, and URL filters on disk cache.
                selected, _ = select_release([{"draft": False, "tag_name": release["tag"],
                    "prerelease": release.get("prerelease"), "name": release.get("name"),
                    "body": release.get("notes"), "html_url": release.get("url"),
                    "published_at": release.get("published_at"), "assets": [{"name": release.get("asset_name"),
                    "browser_download_url": release.get("asset_url")}]}], self.target, self.arch, self._settings["channel"])
                self._cache["release"] = selected
            other = data.get("other_version")
            if version_key(other):
                self._cache["other_version"] = other
            if data.get("error") in ("offline", "rate_limited", "invalid_response"):
                self._cache["error"] = data["error"]
        except Exception:
            # A damaged update cache never prevents access to memories.
            return

    def _save(self):
        try:
            self.storage.save({"schema": "love-house-updates/v1", **self._settings, **self._cache,
                               "platform": self.target, "architecture": self.arch})
            return True
        except Exception:
            # Update metadata is expendable; user data and app startup are not.
            return False

    def status(self):
        with self._lock:
            now = self.clock()
            release = dict(self._cache["release"]) if self._cache["release"] else None
            current = version_key(self.version)
            available = bool(release and current and version_key(release["version"]) > current)
            other = self._cache["other_version"]
            pending = other if other and current and version_key(other) > current else None
            retry = max(0, int(MANUAL_INTERVAL - (now - self._cache["last_attempt"]))) if self._cache["last_attempt"] is not None else 0
            status = ("checking" if self._checking else self._cache["error"] or
                      ("available" if available else "up_to_date" if self._cache["checked_at"] is not None else "not_checked"))
            return {"current_version": self.version, "platform": self.target, "architecture": self.arch,
                    "settings": dict(self._settings), "status": status, "checking": self._checking,
                    "checked_at": self._cache["checked_at"], "last_attempt": self._cache["last_attempt"],
                    "cached": bool(self._cache["error"] and self._cache["checked_at"] is not None),
                    "available": available, "release": release, "other_platform_version": pending,
                    "retry_after": retry, "releases_url": RELEASES_URL,
                    "privacy": "仅查询公开版本，不发送记忆、对话、连接或模型密钥。", "auto_install": False}

    def settings(self, data):
        if not isinstance(data, dict) or set(data) - {"auto_check", "channel"}:
            raise ValidationError("更新设置只接受自动检查和发布通道")
        if "auto_check" in data and type(data["auto_check"]) is not bool:
            raise ValidationError("自动检查设置必须为开关")
        if "channel" in data and data["channel"] not in ("stable", "preview"):
            raise ValidationError("请选择稳定版或预览版")
        with self._lock:
            previous = dict(self._settings), dict(self._cache), self._generation
            if data.get("channel", self._settings["channel"]) != self._settings["channel"]:
                self._generation += 1
                self._cache.update(checked_at=None, release=None, other_version=None, error=None)
            self._settings.update(data)
            if not self._save():
                self._settings, self._cache, self._generation = previous
                raise ValidationError("更新设置未能保存，请检查本机数据目录权限；原设置已保留")
        if self._settings["auto_check"]:
            self.start()
            self.request_check(manual=False)
        return self.status()

    def _due(self, manual=False):
        if self._stop.is_set() or self._checking:
            return False
        if not manual and not self._settings["auto_check"]:
            return False
        now = self.clock()
        attempted = self._cache["last_attempt"]
        checked = self._cache["checked_at"]
        interval = MANUAL_INTERVAL if manual else ERROR_INTERVAL if self._cache["error"] else CHECK_INTERVAL
        reference = attempted if manual or self._cache["error"] else checked
        # The global minimum also applies when users change release channels.
        return (attempted is None or now - attempted >= MANUAL_INTERVAL) and (reference is None or now - reference >= interval)

    def _begin(self, manual):
        with self._lock:
            if not self._due(manual):
                return None
            self._checking = True
            self._cache["last_attempt"] = self.clock()
            return self._generation, self._settings["channel"]

    def _run(self, request):
        if self._stop.is_set():
            with self._lock:
                self._checking = False
            return
        generation, channel = request
        release = other = error = None
        try:
            releases = self.transport(API_URL, timeout=5, max_bytes=MAX_BYTES)
            release, other = select_release(releases, self.target, self.arch, channel)
        except urllib.error.HTTPError as exc:
            error = "rate_limited" if exc.code in (403, 429) else "offline"
        except (ValueError, TypeError, KeyError, OverflowError):
            error = "invalid_response"
        except Exception:
            error = "offline"
        with self._lock:
            self._checking = False
            if self._stop.is_set() or generation != self._generation:
                return
            self._cache["error"] = error
            if error is None:
                self._cache.update(release=release, other_version=other, checked_at=self.clock())
            self._save()

    def request_check(self, *, manual=True):
        request = self._begin(manual)
        if request is not None:
            thread = threading.Thread(target=self._run, args=(request,), name="love-house-release-check", daemon=True)
            self._request_thread = thread
            thread.start()
        return self.status()

    def check(self, *, manual=True):
        """Synchronous test/CLI seam; HTTP and desktop UI always use request_check."""
        request = self._begin(manual)
        if request is not None:
            self._run(request)
        return self.status()

    def start(self):
        # Invoked by the first desktop update-status request. Headless memory
        # integrations do not make an unrelated network request on construction.
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                return
            def loop():
                while not self._stop.is_set():
                    self.request_check(manual=False)
                    if self._stop.wait(60):
                        return
            self._thread = threading.Thread(target=loop, name="love-house-update-schedule", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        for thread in (self._thread, self._request_thread):
            if thread and thread is not threading.current_thread():
                thread.join(timeout=.2)
