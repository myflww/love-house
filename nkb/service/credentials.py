"""Scoped local provider credentials. Public metadata never contains a secret.

The packaged Swift helper uses one fixed macOS Keychain service; Windows uses
its current-user Credential Manager through native WinCred. If secure system
storage is unavailable, the key remains in this process and key_saved is False.
No existing credentials namespace, provider config or environment key is read.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Mapping

SERVICE = "local.neural-knowledge.ai-credentials.v1"
_SESSION: dict[str, str] = {}
_LOCK = threading.RLock()
_BUILT_HELPERS: dict[str, Path | None] = {}
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


class KeyStoreError(RuntimeError):
    """A local credential operation cannot be truthfully confirmed."""


def _account(ref) -> str:
    if isinstance(ref, str):
        if not ref.strip() or len(ref) > 4000:
            raise ValueError("credential ref must be a nonempty stable scope")
        value = {"scope": ref}
    elif isinstance(ref, Mapping):
        value = dict(ref)
        if (not value or any(not isinstance(k, str) or not isinstance(v, (str, type(None))) for k, v in value.items())
                or not value.get("provider") or not value.get("library_id")):
            raise ValueError("credential ref requires provider and library_id; connection_id is an explicit independent scope")
    else:
        raise TypeError("credential ref must be a scope string or mapping")
    material = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((SERVICE + "\0" + material).encode("utf-8")).hexdigest()


def _packaged_helper() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if parent.name == "Contents":
            candidate = parent / "MacOS/NeuralCredential"
            return candidate if candidate.is_file() else None
    return None


def _source_helper(*, allow_build=False) -> Path | None:
    if sys.platform != "darwin":
        return None
    root = _SOURCE_ROOT
    source = root / "desktop/Keychain.swift"
    if not source.is_file():
        return None
    fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    with _LOCK:
        if fingerprint in _BUILT_HELPERS:
            return _BUILT_HELPERS[fingerprint]
        directory = root / "desktop/.build/credentials"
        output = directory / ("NeuralCredential-" + fingerprint)
        if not output.is_file() and not allow_build:
            return None
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not output.is_file():
            temporary = output.with_suffix(".building")
            try:
                result = subprocess.run(["/usr/bin/xcrun", "swiftc", "-O", "-framework", "Security", "-framework", "LocalAuthentication", str(source), "-o", str(temporary)],
                                        capture_output=True, timeout=45, check=False)
                if result.returncode:
                    _BUILT_HELPERS[fingerprint] = None
                    return None
                temporary.chmod(0o700)
                temporary.replace(output)
            except (OSError, subprocess.SubprocessError):
                _BUILT_HELPERS[fingerprint] = None
                return None
            finally:
                temporary.unlink(missing_ok=True)
        _BUILT_HELPERS[fingerprint] = output
        return output


class KeyStore:
    """All callers must supply an explicit provider/library/connection scope.

    A string ref is opaque and must already include the caller's intended scope.
    Mapping refs are canonicalized, so dictionary insertion order is irrelevant.
    get() is internal-only; only metadata() and set()/delete() results belong in UI.
    """

    def __init__(self, helper: str | Path | None = None, *, allow_source_build=True, allow_keychain=True, windows_backend=None):
        self._explicit_helper = Path(helper).expanduser().resolve() if helper is not None else None
        self._allow_source_build = bool(allow_source_build)
        self._allow_keychain = bool(allow_keychain)
        self._windows_backend = windows_backend

    def _helper(self, *, allow_build=False):
        if not self._allow_keychain:
            return None
        if self._explicit_helper is not None:
            return self._explicit_helper if self._explicit_helper.is_file() else None
        packaged = _packaged_helper()
        if packaged is not None:
            return packaged
        # A packaged app must never compile into its own signed resources.
        if any(parent.name == "Contents" for parent in Path(__file__).resolve().parents):
            return None
        return _source_helper(allow_build=allow_build and self._allow_source_build)

    def _call(self, op, account, value=None, *, allow_build=False):
        if not self._allow_keychain:
            return None
        if self._explicit_helper is None and (sys.platform == "win32" or self._windows_backend is not None):
            try:
                if self._windows_backend is None:
                    from .windows_credentials import WindowsCredentialBackend
                    self._windows_backend = WindowsCredentialBackend()
                response = self._windows_backend.call(op, account, value)
                return response if isinstance(response, dict) else None
            except Exception:
                # Do not stringify a backend exception: it may contain a secret.
                return None
        try:
            helper = self._helper(allow_build=allow_build)
        except OSError:
            return None
        if helper is None:
            return None
        request = {"op": op, "account": account}
        if value is not None:
            request["value"] = value
        try:
            # The secret travels only over this private stdin/stdout pipe, never argv or logs.
            result = subprocess.run([str(helper)], input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12, check=False,
                                    env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"})
            if result.returncode or len(result.stdout) > 65536:
                return None
            response = json.loads(result.stdout)
            return response if isinstance(response, dict) else None
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
            return None

    @staticmethod
    def _metadata(storage="none", ready=False, saved=False):
        return {"storage": storage, "key_saved": bool(saved), "credential_ready": bool(ready)}

    def set(self, ref, key, persist=True):
        account = _account(ref)
        if (type(persist) is not bool or not isinstance(key, str) or not key.strip()
                or len(key.encode("utf-8")) > 32768 or any(character in key for character in ("\0", "\r", "\n"))):
            raise ValueError("key must be a nonempty bounded string and persist must be boolean")
        with _LOCK:
            if persist:
                written = self._call("set", account, key, allow_build=True)
                checked = self._call("get", account) if written and written.get("ok") is True else None
                stored = checked.get("value") if checked and checked.get("ok") is True else None
                if isinstance(stored, str) and hmac.compare_digest(stored.encode("utf-8"), key.encode("utf-8")):
                    _SESSION.pop(account, None)
                    return self._metadata("keychain", True, True)
            _SESSION[account] = key
            return self._metadata("session", True, False)

    def get(self, ref) -> str:
        account = _account(ref)
        with _LOCK:
            if account in _SESSION:
                return _SESSION[account]
            response = self._call("get", account)
            value = response.get("value") if response and response.get("ok") is True else None
            return value if isinstance(value, str) else ""

    def metadata(self, ref):
        account = _account(ref)
        with _LOCK:
            if account in _SESSION:
                return self._metadata("session", bool(_SESSION[account]), False)
            response = self._call("get", account)
            ready = bool(response and response.get("ok") is True and isinstance(response.get("value"), str) and response["value"])
            return self._metadata("keychain" if ready else "none", ready, ready)

    def delete(self, ref):
        account = _account(ref)
        with _LOCK:
            _SESSION.pop(account, None)
            if not self._allow_keychain or (sys.platform not in ("darwin", "win32") and self._explicit_helper is None and self._windows_backend is None):
                return self._metadata()
            response = self._call("delete", account)
            if not response or response.get("ok") is not True:
                raise KeyStoreError("本轮临时密钥已清除，但无法确认系统凭据保管库删除；未宣称持久密钥已删除")
            return self._metadata()
