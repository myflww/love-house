"""Windows 启动事实与可核查的失败诊断。

只读取本机运行时元数据：系统版本、注册表里 WebView2/.NET 的版本号、相关文件是否
存在。不读取记忆、密钥、连接凭据或异常原文，不下载也不安装任何运行时。

这个模块必须能在任何平台上导入，方便在 macOS/Linux 上跑契约测试；真正的注册表
读取只在 win32 上发生。
"""
from __future__ import annotations

import errno
import json
import os
import platform as _platform
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path, PurePosixPath

SCHEMA = "love-house-startup/v1"
LOG_SCHEMA = "love-house-startup-log/v1"
LOG_RELATIVE = Path("logs") / "startup.log"
LOG_MAX_BYTES = 512 * 1024
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

# 微软 WebView2 的四条 Evergreen 通道；任何一条可用都足以显示界面。
WEBVIEW2_CHANNELS = (
    ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "runtime"),
    ("{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}", "beta"),
    ("{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "developer"),
    ("{65C35B14-6C1D-4122-AC46-7148CC9D6497}", "canary"),
)
MIN_WEBVIEW2_VERSION = (86, 0, 622, 0)


class AlreadyRunning(RuntimeError):
    """同一数据目录已被另一个爱之屋进程持有。"""


class WebView2Unavailable(RuntimeError):
    """没有可用的 WebView2 运行时，原生窗口无法显示。"""

    def __init__(self, facts):
        self.facts = facts if isinstance(facts, dict) else {"available": False}
        super().__init__("Microsoft WebView2 Runtime is unavailable")


class DotNetUnavailable(RuntimeError):
    """Required Microsoft .NET Framework could not be confirmed."""

    def __init__(self, facts=None):
        self.facts = facts if isinstance(facts, dict) else {"available": False}
        super().__init__("Microsoft .NET Framework 4.6.2 or later is required")


class NativeStartupTimeout(RuntimeError):
    """WebView2 did not finish initializing within the startup deadline."""


def version_tuple(value):
    """把 120.0.2210.144 这类版本号转成可比较的整数元组；不合法返回 None。"""
    try:
        parts = tuple(int(part) for part in str(value).strip().split(".") if part)
    except (TypeError, ValueError):
        return None
    return parts or None


def _usable(version):
    parts = version_tuple(version)
    return bool(parts) and parts >= MIN_WEBVIEW2_VERSION


def _winreg_module():
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    return winreg


def registry_channels(winreg_module=None):
    """读取不需要管理员权限的 WebView2 通道登记；读不到就返回空列表。"""
    module = winreg_module or _winreg_module()
    if module is None:
        return []
    found = []
    for channel, name in WEBVIEW2_CHANNELS:
        for hive_name, hive in (("HKCU", module.HKEY_CURRENT_USER), ("HKLM", module.HKEY_LOCAL_MACHINE)):
            for prefix in ("Software", r"Software\WOW6432Node"):
                path = prefix + "\\Microsoft\\EdgeUpdate\\Clients\\" + channel
                try:
                    with module.OpenKey(hive, path) as key:
                        version = str(module.QueryValueEx(key, "pv")[0])
                except Exception:  # 注册表缺失、无权读取或被策略改写都属于"没找到"
                    continue
                if _usable(version):
                    found.append({"channel": name, "hive": hive_name, "version": version})
    return found


def _file_roots(environ):
    roots = []
    for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        value = environ.get(key)
        if value:
            roots.append(Path(value))
    return roots


def file_channels(environ=None):
    """按标准安装位置查找 msedgewebview2.exe；也接受微软官方的固定版目录变量。"""
    environ = os.environ if environ is None else environ
    found = []
    custom = environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER")
    if custom and (Path(custom) / "msedgewebview2.exe").is_file():
        found.append({"channel": "custom", "source": "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
                      "folder": Path(custom).name})
    for root in _file_roots(environ):
        application = root / "Microsoft" / "EdgeWebView" / "Application"
        try:
            executables = sorted(application.glob("*/msedgewebview2.exe"))
        except OSError:
            executables = []
        for executable in executables:
            if _usable(executable.parent.name):
                found.append({"channel": "runtime", "source": "files",
                              "version": executable.parent.name,
                              "folder": executable.parent.name})
    return found


def bundled_runtime(executable=None):
    """随包放置的固定版运行时目录（<应用目录>/WebView2Runtime），没有就返回 None。"""
    root = Path(executable).resolve().parent if executable else Path(sys.executable).resolve().parent
    folder = root / "WebView2Runtime"
    return folder if (folder / "msedgewebview2.exe").is_file() else None


def runtime_folder():
    """返回可交给 pywebview 的固定版运行时目录；没有返回 None。"""
    custom = os.environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER")
    if custom and (Path(custom) / "msedgewebview2.exe").is_file():
        return Path(custom)
    return bundled_runtime()


def webview2_status(environ=None, registry=None):
    """汇总可用的 WebView2 信息；available 为假时才代表确定没有运行时。"""
    channels = list((registry if registry is not None else registry_channels)())
    channels += file_channels(environ)
    folder = runtime_folder()
    if folder is not None and not any(item.get("channel") == "custom" for item in channels):
        channels.append({"channel": "bundled", "source": "app", "folder": folder.name})
    versions = sorted((str(item["version"]) for item in channels if item.get("version")),
                      key=lambda value: version_tuple(value) or ())
    best = versions[-1] if versions else None
    available = bool(channels) or folder is not None
    return {
        "available": available,
        "version": best,
        "channels": channels,
        "registry_hits": sum(1 for item in channels if item.get("hive")),
        "file_hits": sum(1 for item in channels if item.get("source") == "files"),
        "custom_folder": folder is not None,
    }


def dotnet_status(winreg_module=None):
    """读取 .NET Framework 4.x 的 Release；pywebview 需要 4.6.2（394802）以上。"""
    module = winreg_module or _winreg_module()
    empty = {"release": None, "version": None, "ok": None}
    if module is None:
        return empty
    try:
        with module.OpenKey(module.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as key:
            release = int(module.QueryValueEx(key, "Release")[0])
            try:
                version = str(module.QueryValueEx(key, "Version")[0])
            except OSError:
                version = None
    except Exception:
        return empty
    return {"release": release, "version": version, "ok": release >= 394802}


def system_facts():
    """公开的系统事实；不含用户名、目录内容或会话信息。"""
    facts = {
        "platform": sys.platform,
        "machine": _platform.machine(),
        "os": _platform.platform(),
        "python": _platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    if sys.platform == "win32":
        try:
            version = sys.getwindowsversion()
            facts["windows_build"] = [int(version.major), int(version.minor), int(version.build)]
            facts["windows_service_pack"] = version.service_pack or ""
        except Exception:
            facts["windows_build"] = None
    return facts


def startup_facts(data_dir=None):
    """一次性收集启动判断需要的全部事实。"""
    try:
        from .windows_prerequisites import runtime_status, dotnet_status as framework_status
    except ImportError:
        from windows_prerequisites import runtime_status, dotnet_status as framework_status
    facts = system_facts()
    facts["webview2"] = runtime_status()
    facts["webview2_discovery"] = webview2_status()
    facts["dotnet"] = framework_status()
    if data_dir is not None:
        facts["data_dir"] = str(data_dir)
        facts["log"] = str(startup_log_path(data_dir))
    return facts


_WINDOWS_CODE_FILES = frozenset({
    "windows_app.py", "windows_diagnostics.py", "windows_prerequisites.py",
    "agent_memory_bridge.py", "agent_memory_hook.py",
})


def _controlled_code_path(filename):
    """Map source and PyInstaller co_filename values to safe app locations.

    Frozen code objects may retain a relative source filename while __file__
    points into _MEIPASS. Resolving that filename against cwd loses its origin
    and can leak a user-chosen working directory. Accept only known entry files
    or already loaded nkb modules whose bundle mapping agrees.
    """
    if not getattr(sys, "frozen", False):
        root = Path(__file__).resolve().parents[1]
        source = Path(filename).resolve()
        return source.relative_to(root).as_posix() if source.is_relative_to(root) and source.suffix == ".py" else None
    frozen_root = getattr(sys, "_MEIPASS", None)
    if not frozen_root:
        return None
    root = Path(frozen_root).resolve()
    native = Path(filename)
    if native.is_absolute():
        source = native.resolve()
        if not source.is_relative_to(root):
            return None
        filename = source.relative_to(root).as_posix()
    candidate = PurePosixPath(str(filename).replace("\\", "/"))
    if candidate.is_absolute() or any(part in ("..", ".") or ":" in part for part in candidate.parts):
        return None
    if candidate.name in _WINDOWS_CODE_FILES and candidate.parts in ((candidate.name,), ("desktop", candidate.name)):
        return "desktop/" + candidate.name
    if not candidate.parts or candidate.parts[0] != "nkb" or candidate.suffix != ".py":
        return None
    components = (*candidate.parts[:-1], candidate.stem)
    if any(not component.isidentifier() for component in components):
        return None
    module_name = ".".join(components[:-1] if components[-1] == "__init__" else components)
    module = sys.modules.get(module_name)
    origin = getattr(module, "__file__", None)
    if origin and Path(origin).resolve() == (root / str(candidate)).resolve():
        return candidate.as_posix()
    return None


def failure_record(exc):
    """安全异常摘要：只保留类型、错误码和出错位置，不保留异常原文。"""
    frames = traceback.extract_tb(exc.__traceback__)
    record = {"type": type(exc).__name__, "kind": classify(exc)}
    for attribute in ("errno", "winerror"):
        value = getattr(exc, attribute, None)
        record[attribute] = value if type(value) is int else None
    # OSError.filename can be a user supplied document name, or even secret text.
    # Only positions in this application's controlled Python source are emitted.
    for frame in reversed(frames):
        source = _controlled_code_path(frame.filename)
        if source is not None:
            record["at"] = {"file": source,
                            "function": frame.name, "line": frame.lineno}
            break
    for attribute in ("hresult", "HResult"):
        value = getattr(exc, attribute, None)
        if type(value) is int:
            record["hresult"] = value & 0xFFFFFFFF
            break
    return record


def classify(exc):
    if isinstance(exc, AlreadyRunning):
        return "already_running"
    if isinstance(exc, WebView2Unavailable):
        return "webview2_unavailable"
    if isinstance(exc, DotNetUnavailable):
        return "dotnet_unavailable"
    if isinstance(exc, NativeStartupTimeout):
        return "webview2_initialization_timeout"
    if isinstance(exc, PermissionError):
        return "data_directory_unwritable"
    if isinstance(exc, (ImportError, ModuleNotFoundError)) or getattr(exc, "winerror", None) in (126, 127, 193):
        return "packaged_dependency_missing"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (errno.ENOSPC, errno.EROFS, errno.EIO):
        return "storage_failure"
    # Do not inspect exception messages: CLR errors may contain environment
    # values, file paths or text from the page being initialized.
    if type(exc).__module__.startswith(("System", "Python.Runtime", "clr_loader")):
        return "clr_initialization_failed"
    return "unexpected"


def _plain(value, depth=0):
    if depth > 4:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in list(value)[:20]]
    if isinstance(value, dict):
        return {str(key)[:40]: _plain(item, depth + 1) for key, item in list(value.items())[:40]}
    return None


def startup_log_path(data_dir):
    return Path(data_dir) / LOG_RELATIVE


class StartupLog:
    """只写本机事实的启动日志；写入失败绝不影响启动。"""

    def __init__(self, path, max_bytes=LOG_MAX_BYTES):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def write(self, event, **fields):
        record = {"schema": LOG_SCHEMA, "time": round(time.time(), 3), "event": str(event)[:80]}
        for key, value in fields.items():
            record[str(key)[:40]] = _plain(value)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock:
            fallback = Path(tempfile.gettempdir()) / "LoveHouse" / "logs" / ("startup-" + str(os.getpid()) + ".log")
            for target in dict.fromkeys((self.path, fallback)):
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and target.stat().st_size + len((line + "\n").encode("utf-8")) > self.max_bytes:
                        target.replace(target.with_name(target.stem + ".1.log"))
                    with target.open("a", encoding="utf-8") as stream:
                        stream.write(line + "\n")
                    self.path = target
                    return record
                except OSError:
                    continue
        return None

    def tail(self, count=30):
        try:
            return self.path.read_text("utf-8").splitlines()[-count:]
        except OSError:
            return []


def _describe_webview2(status):
    if not status.get("available"):
        if sys.platform != "win32":
            return "非 Windows，不适用"
        return "不可用（" + str(status.get("code") or "未通过运行时探测") + "）"
    version = status.get("version") or "版本未知"
    channels = sorted({item.get("channel", "?") for item in status.get("channels", [])})
    return version + "（" + ("、".join(channels) or str(status.get("source") or "运行时")) + "）"


def _display_path(value):
    """Keep diagnostic paths useful without embedding the account directory."""
    if value is None:
        return "None"
    target = Path(value)
    bases = [(Path.home(), "%USERPROFILE%"), (Path(tempfile.gettempdir()), "%TEMP%")]
    if os.environ.get("LOCALAPPDATA"):
        bases.append((Path(os.environ["LOCALAPPDATA"]), "%LOCALAPPDATA%"))
    for base, label in sorted(bases, key=lambda item: len(str(item[0])), reverse=True):
        try:
            return label + "/" + target.relative_to(base).as_posix()
        except ValueError:
            continue
    return str(target)


def diagnostic_report(facts, log_lines=()):
    """生成给人看的诊断文本；只含本机运行时事实。"""
    webview2 = facts.get("webview2", {})
    dotnet = facts.get("dotnet", {})
    build = facts.get("windows_build")
    lines = [
        "爱之屋启动诊断 / Love House startup diagnostics",
        "",
        "生成时间：" + time.strftime("%Y-%m-%d %H:%M:%S"),
        "系统：" + str(facts.get("os")),
        "系统版本号：" + ((".".join(str(part) for part in build)) if build else "非 Windows"),
        "架构：" + str(facts.get("machine")),
        "Python：" + str(facts.get("python")),
        "打包运行：" + ("是" if facts.get("frozen") else "否"),
        "数据目录：" + _display_path(facts.get("data_dir")),
        "启动日志：" + _display_path(facts.get("log")),
        "",
        "WebView2：" + _describe_webview2(webview2),
        "WebView2 版本：" + str(webview2.get("version") or "无"),
        ".NET Framework：" + str(dotnet.get("version") or "读取不到")
        + "（Release " + str(dotnet.get("release")) + "）",
    ]
    if facts.get("renderer"):
        lines.append("pywebview 实际渲染器：" + str(facts["renderer"]))
    if facts.get("error"):
        lines.append("启动错误：" + str(facts["error"]))
    lines += ["", "最近的启动日志："]
    lines += [line for line in log_lines] or ["（没有日志）"]
    lines += ["", "本文件不含记忆、密钥或对话内容，可以直接发给开发者。"]
    return "\n".join(lines) + "\n"
