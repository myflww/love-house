"""Probe and repair Windows prerequisites without loading CLR or user memory.

Only a pinned, Microsoft-signed offline installer may be executed.  Importing
this module performs no probing, downloading, installation or environment edits.
The public functions return JSON-safe facts, never exception messages or output
from an external process.  The GUI owns user consent before calling repair.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

RUNTIME_CLIENT = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
INSTALLER_FILENAME = "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
INSTALLER_SCHEMA = "love-house-webview2-installer/v1"
INSTALLER_SHA256 = "1c401b327fbc7bb9731b4e350a2194f083cbc3ede46508d52e1cae6610a39bea"
INSTALLER_PUBLISHER = "Microsoft Corporation"
MIN_DOTNET_RELEASE = 394802
MIN_RUNTIME_VERSION = (86, 0, 622, 0)
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)(?:\s+(?:beta|dev|canary))?$", re.I)
_SIGNATURE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$target = [Environment]::GetEnvironmentVariable('LOVE_HOUSE_SIGNATURE_TARGET', 'Process')
$signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature -LiteralPath $target
$publisher = ''
if ($null -ne $signature.SignerCertificate) {
  $publisher = $signature.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
}
@{status=$signature.Status.ToString(); publisher=$publisher} | ConvertTo-Json -Compress
"""


def _version(value):
    if not isinstance(value, str) or len(value) > 80:
        return None
    match = _VERSION.fullmatch(value.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def _winreg():
    if sys.platform != "win32":
        return None
    try:
        import winreg
        return winreg
    except ImportError:
        return None


def _registry_views(module):
    return tuple(dict.fromkeys((getattr(module, "KEY_WOW64_64KEY", 0),
                                getattr(module, "KEY_WOW64_32KEY", 0))))


def registry_runtime_versions(winreg_module=None):
    """Read effective Evergreen registrations in both registry views/hives."""
    module = winreg_module or _winreg()
    if module is None:
        return []
    found = []
    for name, hive in (("HKCU", module.HKEY_CURRENT_USER), ("HKLM", module.HKEY_LOCAL_MACHINE)):
        for view in _registry_views(module):
            try:
                with module.OpenKey(hive, "Software\\Microsoft\\EdgeUpdate\\Clients\\" + RUNTIME_CLIENT,
                                    0, module.KEY_READ | view) as key:
                    value, kind = module.QueryValueEx(key, "pv")
                parts = _version(value)
                if kind == module.REG_SZ and parts and parts > (0, 0, 0, 0):
                    found.append({"hive": name, "view": view, "version": value.strip()})
            except (OSError, TypeError, ValueError):
                continue
    return found


def dotnet_status(winreg_module=None):
    """Report Framework 4.6.2+; a missing Windows key is a failed prerequisite."""
    module = winreg_module or _winreg()
    result = {"available": False, "ok": False, "release": None, "version": None,
              "code": "dotnet_missing"}
    if module is None:
        result.update(ok=None if sys.platform != "win32" else False,
                      code="unsupported_platform" if sys.platform != "win32" else "registry_unavailable")
        return result
    for view in _registry_views(module):
        try:
            with module.OpenKey(module.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
                                0, module.KEY_READ | view) as key:
                release, kind = module.QueryValueEx(key, "Release")
                if kind != module.REG_DWORD or type(release) is not int or release < 0:
                    continue
                try:
                    version = module.QueryValueEx(key, "Version")[0]
                except OSError:
                    version = None
        except (OSError, TypeError, ValueError):
            continue
        if result["release"] is None or release > result["release"]:
            ok = release >= MIN_DOTNET_RELEASE
            result.update(available=ok, ok=ok, release=release,
                          version=version if isinstance(version, str) and re.fullmatch(r"\d+(?:\.\d+){1,3}", version) else None,
                          code="ok" if ok else "dotnet_too_old")
    return result


def _roots(bundle_root=None):
    roots = []
    if bundle_root is not None:
        roots.extend((Path(bundle_root), Path(bundle_root) / "_internal"))
    else:
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            roots.append(Path(frozen_root))
        if getattr(sys, "frozen", False):
            roots.extend((Path(sys.executable).resolve().parent,
                          Path(sys.executable).resolve().parent / "_internal"))
        roots.append(Path(__file__).resolve().parents[1])
    return tuple(dict.fromkeys(roots))


def _loader_path(bundle_root=None):
    relative = Path("webview/lib/runtimes/win-x64/native/WebView2Loader.dll")
    candidates = [root / relative for root in _roots(bundle_root)]
    if bundle_root is None and not getattr(sys, "frozen", False):
        try:
            spec = importlib.util.find_spec("webview")
            if spec and spec.origin:
                candidates.append(Path(spec.origin).parent / "lib/runtimes/win-x64/native/WebView2Loader.dll")
        except (ImportError, AttributeError, ValueError):
            pass
    return next((path for path in candidates if path.is_file()), None)


def _loader_version(path):
    """Use the native SDK ABI; returned PWSTR belongs to CoTaskMemFree."""
    loader = ctypes.WinDLL(str(path.resolve()))
    function = loader.GetAvailableCoreWebView2BrowserVersionString
    function.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]
    function.restype = ctypes.c_long
    free = ctypes.OleDLL("ole32").CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    pointer = ctypes.c_void_p()
    try:
        hresult = int(function(None, ctypes.byref(pointer))) & 0xFFFFFFFF
        value = ctypes.wstring_at(pointer) if pointer.value else None
        return hresult, value
    finally:
        if pointer.value:
            free(pointer)


def runtime_status(bundle_root=None):
    """Verify the installed Runtime through the packaged x64 native Loader.

    Registrations are supporting evidence only.  A successful version probe is
    followed by real WebView2 initialization in the GUI; it is not a GUI test.
    WEBVIEW2 environment policy is managed by the application before this call.
    """
    result = {"available": False, "version": None, "source": "loader", "code": "runtime_missing",
              "registry_versions": []}
    if sys.platform != "win32":
        result.update(source="none", code="unsupported_platform")
        return result
    if struct.calcsize("P") != 8:
        result.update(source="none", code="unsupported_architecture")
        return result
    result["registry_versions"] = registry_runtime_versions()
    loader = _loader_path(bundle_root)
    if loader is None:
        result["code"] = "loader_missing"
        return result
    try:
        hresult, version = _loader_version(loader)
    except (OSError, AttributeError, ValueError) as exc:
        result.update(code="loader_load_failed", exception_type=type(exc).__name__)
        winerror = getattr(exc, "winerror", None)
        if isinstance(winerror, int):
            result["winerror"] = winerror
        return result
    result["hresult"] = hresult
    parts = _version(version)
    if hresult == 0 and parts and parts >= MIN_RUNTIME_VERSION:
        result.update(available=True, version=version.strip(), code="ok")
    elif hresult == 0 and parts:
        result.update(version=version.strip(), code="runtime_too_old")
    elif result["registry_versions"]:
        result["code"] = "runtime_unavailable"
    return result


def _installer_paths(bundle_root=None):
    for root in _roots(bundle_root):
        directory = root / "resources/runtime"
        if (directory / "manifest.json").is_file() or (directory / INSTALLER_FILENAME).is_file():
            return directory / "manifest.json", directory / INSTALLER_FILENAME
    return None, None


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _powershell_path():
    # Resolve the Windows system directory via the OS, never PATH/SystemRoot.
    buffer = ctypes.create_unicode_buffer(32768)
    function = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemDirectoryW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    function.restype = ctypes.c_uint
    length = function(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise OSError("Windows system directory unavailable")
    return Path(buffer.value) / "WindowsPowerShell/v1.0/powershell.exe"


def _authenticode_status(path, timeout=30):
    if sys.platform != "win32":
        return {"verified": False, "code": "signature_unavailable"}
    try:
        executable = _powershell_path()
        if not executable.is_file():
            return {"verified": False, "code": "signature_unavailable"}
        environment = os.environ.copy()
        environment["PSModulePath"] = str(executable.parent / "Modules")
        environment["LOVE_HOUSE_SIGNATURE_TARGET"] = str(path.resolve())
        response = subprocess.run([str(executable), "-NoLogo", "-NoProfile", "-NonInteractive",
                                   "-Command", _SIGNATURE_SCRIPT], env=environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=timeout, check=False, creationflags=0x08000000)
        if response.returncode:
            return {"verified": False, "code": "signature_check_failed"}
        if len(response.stdout) > 16384:
            return {"verified": False, "code": "signature_check_failed"}
        value = json.loads(response.stdout.decode("utf-8-sig"))
        if not isinstance(value, dict):
            return {"verified": False, "code": "signature_check_failed"}
        valid = value.get("status") == "Valid" and value.get("publisher") == INSTALLER_PUBLISHER
        return {"verified": valid, "code": "ok" if valid else "signature_invalid"}
    except subprocess.TimeoutExpired:
        return {"verified": False, "code": "signature_timeout"}
    except (OSError, ValueError, TypeError, UnicodeError, AttributeError):
        return {"verified": False, "code": "signature_check_failed"}


def bundled_installer_status(bundle_root=None):
    """Fail closed unless manifest, fixed hash and Microsoft signature agree."""
    result = {"available": False, "verified": False, "code": "installer_missing"}
    manifest_path, installer = _installer_paths(bundle_root)
    if installer is None or not installer.is_file():
        return result
    result["available"] = True
    try:
        if manifest_path.stat().st_size > 16384:
            result["code"] = "manifest_invalid"
            return result
        manifest = json.loads(manifest_path.read_text("utf-8"))
        required = {"schema": INSTALLER_SCHEMA, "filename": INSTALLER_FILENAME,
                    "sha256": INSTALLER_SHA256, "publisher": INSTALLER_PUBLISHER, "architecture": "x64"}
        if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in required.items()):
            result["code"] = "manifest_invalid"
            return result
        if _sha256(installer) != INSTALLER_SHA256:
            result["code"] = "installer_hash_mismatch"
            return result
    except (OSError, ValueError, UnicodeError):
        result["code"] = "manifest_invalid"
        return result
    signature = _authenticode_status(installer)
    result.update(verified=signature["verified"], code=signature["code"])
    return result


def repair_runtime(bundle_root=None, timeout=180, force=False):
    """Run the verified offline installer, then re-probe; caller obtains consent.

    This never requests elevation, downloads files, or touches personal memory.
    force means retry the installer even when the version API currently works.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        raise ValueError("timeout must be between 1 and 600 seconds")
    before = runtime_status(bundle_root)
    result = {"ok": False, "code": "unsupported_platform", "runtime": before}
    if sys.platform != "win32":
        return result
    if before["available"] and not force:
        result.update(ok=True, code="already_available")
        return result
    installer_status = bundled_installer_status(bundle_root)
    if not installer_status["verified"]:
        result["code"] = installer_status["code"]
        return result
    _, installer = _installer_paths(bundle_root)
    try:
        # Recheck bytes immediately before execution; never shell-expand a path.
        if _sha256(installer) != INSTALLER_SHA256:
            result["code"] = "installer_hash_mismatch"
            return result
        response = subprocess.run([str(installer.resolve()), "/silent", "/install"],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                                  creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        result.update(code="repair_timeout", runtime=runtime_status(bundle_root))
        return result
    except OSError as exc:
        result.update(code="repair_execution_failed", exception_type=type(exc).__name__)
        winerror = getattr(exc, "winerror", None)
        if isinstance(winerror, int):
            result["winerror"] = winerror
        return result
    after = runtime_status(bundle_root)
    restart = response.returncode in (1641, 3010)
    result.update(runtime=after, exit_code=response.returncode, restart_required=restart)
    if response.returncode not in (0, 1641, 3010):
        result["code"] = "repair_failed"
    elif not after["available"]:
        result["code"] = "restart_required" if restart else "repair_not_available"
    else:
        result.update(ok=True, code="repaired")
    return result
