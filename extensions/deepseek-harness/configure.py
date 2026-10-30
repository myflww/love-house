"""Portable controller helper; never reads Harness credentials or conversation files."""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import struct
import sys
import time
from pathlib import Path

SUPPORTED = ("0.2.1-rc.3", "0.2.1-rc.5")
OWNER = "neural-knowledge-host"
BEGIN = "# BEGIN NEURAL-KNOWLEDGE-HOST MANAGED\n"
END = "# END NEURAL-KNOWLEDGE-HOST MANAGED\n"
ROOT = Path(__file__).resolve().parent
FINGERPRINT_FILE = ROOT / "host-contract-fingerprints.json"


def _legacy_entries(profile):
    """Recognize only the known packaged bridge; never return env/credential data."""
    found = []
    for filename in ("cordis.patch.yml", "cordis.yml"):
        path = profile / filename
        if not path.exists() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        lines = path.read_text("utf-8").splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^(\s*)-\s+(?:id|name)\s*:", line)
            if not match:
                continue
            indent = len(match.group(1))
            end = index + 1
            while end < len(lines):
                current = lines[end]
                if current.strip() and not current.lstrip().startswith("#") and len(current) - len(current.lstrip()) <= indent:
                    break
                end += 1
            block = "\n".join(lines[index:end])
            logical = re.sub(r"\\\r?\n[ \t]*", "", block)  # YAML double-quoted line continuation
            server = re.search(r"['\"]?serverName['\"]?\s*:\s*['\"]?([A-Za-z0-9_-]{1,32})", block)
            identity = re.search(r"(?m)^\s*(?:-\s+)?id\s*:\s*['\"]?([A-Za-z0-9_.:-]+)['\"]?\s*(?:#.*)?$", block)
            if ("@deepseek-ai/dsh-mcp-client" in block and server and identity and
                    any(name + ".app/Contents/Resources/backend/harness_bridge.py" in logical for name in ("知识星图", "爱之屋"))):
                binding = re.search(r"--library-id['\"]?\s*\n\s*-\s*['\"]?([a-z0-9][a-z0-9_-]{0,63})", block)
                target_id = binding.group(1) if binding else "default"
                found.append({"target_library_id": target_id, "explicit_library_binding": bool(binding), "id": identity.group(1), "server_name": server.group(1),
                              "source_file": str(path), "mode": "manual_mcp",
                              "target_library": "固定存档：" + target_id + "；不会跟随画面切库或自动切到新的宿主连接"})
    return found


def _path(value):
    return Path(os.path.expandvars(str(value).strip().strip('"'))).expanduser().resolve()


def _profile_status(profile):
    """Recognize the legacy root or the official initProfile manifest, read-only.

    dsh-app-boot.initProfile creates package.json/cordis.patch.yml; the launcher
    generates its empty cordis.yml later. A normal npm package is not a profile.
    """
    root_config = profile / "cordis.yml"
    if root_config.is_file() and not root_config.is_symlink():
        return True, "cordis-root"
    manifest = profile / "package.json"
    try:
        if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 1024 * 1024:
            return False, None
        data = json.loads(manifest.read_text("utf-8"))
        dsh = data.get("dsh") if isinstance(data, dict) else None
        settings = dsh.get("profile") if isinstance(dsh, dict) else None
        bundles = settings.get("bundles") if isinstance(settings, dict) else None
        if (isinstance(data, dict) and data.get("private") is True and isinstance(bundles, list) and len(bundles) <= 1024
                and all(isinstance(bundle, str) and 0 < len(bundle.strip()) <= 512 for bundle in bundles)):
            return True, "dsh-profile-manifest"
    except (OSError, ValueError, TypeError, RecursionError):
        pass
    return False, None


def _windows_registry_apps():
    """Read installation inventory only; never start Harness or inspect credentials."""
    if sys.platform != "win32":
        return []
    import winreg
    result = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for suffix in ("", "WOW6432Node\\"):
            try:
                with winreg.OpenKey(hive, "Software\\" + suffix + "Microsoft\\Windows\\CurrentVersion\\Uninstall") as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, index)) as entry:
                                name = winreg.QueryValueEx(entry, "DisplayName")[0]
                                if not isinstance(name, str) or not ("deepseek" in name.lower() and "harness" in name.lower()):
                                    continue
                                location = winreg.QueryValueEx(entry, "InstallLocation")[0]
                                if isinstance(location, str) and location.strip():
                                    result.append(_path(location))
                        except OSError:
                            continue
            except OSError:
                continue
    return result


def _app_candidates():
    if sys.platform == "win32":
        yield from _windows_registry_apps()
        roots = [Path.home() / "AppData/Local/Programs", Path.home() / "AppData/Local"]
        for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(variable):
                root = _path(os.environ[variable])
                roots.extend((root / "Programs", root) if variable == "LOCALAPPDATA" else (root,))
        for root in dict.fromkeys(roots):
            for name in ("DeepSeek Harness", "deepseek-harness", "@deepseek-ai/dsh-desktop", "dsh-desktop"):
                yield root / name
    else:
        yield Path("/Applications/DeepSeek Harness.app")
        yield Path.home() / "Applications/DeepSeek Harness.app"


def _asar_read(archive, name, headers=None):
    """Read a bounded static entry directly; no extraction or executable loading."""
    if archive.is_symlink():
        return None
    with archive.open("rb") as stream:
        cached = headers.get(str(archive)) if headers is not None else None
        if cached:
            header_size, header = cached
        else:
            prefix = stream.read(16)
            if len(prefix) != 16:
                return None
            pickle_size, header_size, payload_size, json_size = struct.unpack("<4I", prefix)
            if (pickle_size != 4 or not 8 <= header_size <= 32 * 1024 * 1024
                    or payload_size + 4 != header_size or not 0 < json_size <= header_size - 8):
                return None
            header = json.loads(stream.read(json_size))
            if headers is not None:
                headers[str(archive)] = (header_size, header)
        entry = header
        for part in name.split("/"):
            entry = entry.get("files", {}).get(part, {})
        if entry.get("link") or entry.get("unpacked") or type(entry.get("size")) is not int:
            return None
        size = entry["size"]
        offset = int(entry.get("offset", "-1"))
        start = 8 + header_size + offset
        if not 0 < size <= 4 * 1024 * 1024 or offset < 0 or start + size > archive.stat().st_size:
            return None
        stream.seek(start)
        return stream.read(size)


def _asar_json(archive, name):
    raw = _asar_read(archive, name)
    return json.loads(raw) if raw else None


def _resource_read(resources, name, headers=None):
    loose = resources / "app" / name
    if loose.is_file():
        if not loose.resolve().is_relative_to(resources.resolve()) or loose.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("资源路径越界或文件过大")
        return loose.read_bytes()
    archive = resources / "app.asar"
    return _asar_read(archive, name, headers) if archive.is_file() else None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _normalized_metadata(metadata, keys):
    version = metadata.get("version")
    def normalize(value):
        if isinstance(value, str):
            return "$HOST_VERSION" if value == version else value
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value
    return normalize({key: metadata[key] for key in keys if key in metadata})


def _contract_probe(app, version):
    """Unknown releases qualify only when their installed code matches our reviewed contract."""
    if not FINGERPRINT_FILE.is_file():
        return {"status": "unverified", "message": "缺少已验证契约指纹，未自动配置新版宿主"}
    expected = json.loads(FINGERPRINT_FILE.read_text("utf-8"))
    diagnostics = []
    headers = {}  # A probe-local cache; never reuse metadata after a host update.
    for resources in (app / "resources", app / "Contents/Resources"):
        if not resources.is_dir():
            continue
        failures = []
        for name, package in expected["packages"].items():
            prefix = "dsh/node_modules/" + name + "/"
            try:
                raw = _resource_read(resources, prefix + "package.json", headers)
                metadata = json.loads(raw) if raw else {}
                if metadata.get("name") != name or metadata.get("version") != version:
                    failures.append(name + ": 缺少官方SDK元数据或混合版本")
                    continue
                actual = hashlib.sha256(_canonical(_normalized_metadata(metadata, expected["metadata_keys"]))).hexdigest()
                if actual != package["metadata_sha256"]:
                    failures.append(name + ": 模块入口或依赖契约已变化")
                for filename, digest in package["files"].items():
                    code = _resource_read(resources, prefix + filename, headers)
                    if code is None or hashlib.sha256(code).hexdigest() != digest:
                        failures.append(name + "/" + filename + ": 运行代码指纹不同或缺失")
            except (OSError, ValueError, TypeError, AttributeError, RecursionError):
                failures.append(name + ": 无法静态读取已安装SDK")
        try:
            cordis = _resource_read(resources, "dsh/node_modules/@deepseek-ai/cordis/package.json", headers)
            data = json.loads(cordis) if cordis else {}
            if data.get("name") != "@deepseek-ai/cordis" or data.get("version") != expected["cordis_version"]:
                failures.append("@deepseek-ai/cordis: 核心版本与已验证契约不同或缺失")
        except (OSError, ValueError, TypeError, AttributeError):
            failures.append("@deepseek-ai/cordis: 无法静态读取核心版本")
        if not failures:
            descriptor = {"schema": "love-house-harness-contract/v1", "host_version": version,
                          "contract_id": expected["contract_id"], "resources_path": str(resources.resolve())}
            return {"status": "fingerprint_match", "message": "已安装SDK运行代码与已验证契约完全一致；按契约自动兼容此版本",
                    "descriptor": descriptor, "reference_versions": expected["reference_versions"]}
        diagnostics.extend(failures)
    return {"status": "contract_changed", "message": "新版宿主契约无法匹配，未自动配置；请验证变化后的接口",
            "diagnostics": diagnostics[:12] or ["未找到官方SDK静态资源"]}


def _app_version(app):
    shell_version, version, source = None, None, None
    # A user may explicitly select the official npm CLI package on Linux/macOS.
    # Its exact verified releases use the same host plugin contract. Unknown CLI
    # versions remain unsupported until their installed dependency layout is audited.
    direct = app / "package.json"
    try:
        metadata = json.loads(direct.read_text("utf-8")) if direct.is_file() and direct.stat().st_size <= 1024 * 1024 else None
        if (isinstance(metadata, dict) and metadata.get("name") == "@deepseek-ai/dsh"
                and isinstance(metadata.get("version"), str)
                and isinstance(metadata.get("bin"), dict) and metadata["bin"].get("dsh") == "lib/bin.js"
                and (app / "lib/bin.js").is_file()):
            return metadata["version"], metadata["version"], "package.json (official npm CLI metadata)"
    except (OSError, ValueError, TypeError, UnicodeError):
        pass
    info = app / "Contents/Info.plist"
    if info.is_file():
        with info.open("rb") as stream:
            metadata = plistlib.load(stream)
        shell_version = metadata.get("CFBundleShortVersionString") or metadata.get("CFBundleVersion")
    # The packaged runtime version is authoritative. A release shell can carry
    # an extended build version, which does not change the bundled agent contract.
    entries = (("dsh/node_modules/@deepseek-ai/dsh-agent/package.json", "@deepseek-ai/dsh-agent"),
               ("dsh/package.json", "@deepseek-ai/dsh-desktop-runtime"),
               ("package.json", "@deepseek-ai/dsh-desktop"))
    for resources in (app / "resources", app / "Contents/Resources"):
        for name, expected in entries:
            try:
                loose = resources / "app" / name
                raw = _resource_read(resources, name)
                data = json.loads(raw) if raw else None
                if isinstance(data, dict) and data.get("name") == expected and isinstance(data.get("version"), str):
                    value = data["version"]
                    if expected == "@deepseek-ai/dsh-desktop":
                        shell_version = value
                    version, source = value, ("resources/app/" if loose.is_file() else "resources/app.asar/") + name
                    return version, shell_version, source
            except (OSError, ValueError, TypeError, AttributeError, RecursionError):
                continue
    return shell_version, shell_version, "Contents/Info.plist" if shell_version else None


def detect(app_path=None, profile_dir=None):
    candidates = [_path(app_path)] if app_path else _app_candidates()
    app, version, shell_version, version_source = None, None, None, None
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".exe":
            candidate = candidate.parent
        if not candidate.is_dir():
            continue
        try:
            found_version, found_shell, found_source = _app_version(candidate)
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
            found_version, found_shell, found_source = None, None, None
        if found_version or any((candidate / name).exists() for name in ("DeepSeek Harness.exe", "deepseek-harness.exe", "Contents/Info.plist")):
            app, version, shell_version, version_source = candidate, found_version, found_shell, found_source
            break
    home = _path(os.environ["DSH_HOME"]) if os.environ.get("DSH_HOME") else Path.home() / ".dsh"
    profile = _path(profile_dir) if profile_dir else home / "profiles/desktop"
    profile_exists, profile_format = _profile_status(profile)
    compatibility = (_contract_probe(app, version) if app and version
                     else {"status": "undetected", "message": "未找到可识别的官方Harness版本元数据"})
    if version in SUPPORTED:
        # Old verified releases retain their legacy configuration contract; a
        # full installed SDK also receives the descriptor so subsequent updates
        # are checked against actual code when the plugin next loads.
        compatibility = {**compatibility, "status": "verified_version", "message": "已验证的精确宿主版本"}
    return {"detected": app is not None, "app_path": str(app) if app else None,
            "version": version, "shell_version": shell_version, "version_source": version_source,
            "supported": version in SUPPORTED or compatibility["status"] == "fingerprint_match",
            "compatibility": compatibility,
            "supported_versions": list(SUPPORTED), "profile_dir": str(profile),
            "profile_source": "explicit" if profile_dir else "DSH_HOME" if os.environ.get("DSH_HOME") else "desktop-default",
            "profile_exists": profile_exists, "profile_format": profile_format,
            "legacy_manual_entries": _legacy_entries(profile),
            "credentials_read": False, "plugin_built": (ROOT / "dist/index.js").exists()}


def _private(path, content):
    if path.is_symlink():
        raise ValueError("拒绝替换符号链接配置")
    temporary = path.with_name(path.name + "." + str(time.time_ns()) + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _patch(source, block, owner, config_file):
    begin = "# BEGIN " + owner.upper() + " MANAGED\n"
    end = "# END " + owner.upper() + " MANAGED\n"
    # Migrate the old single block only when it references this exact connection.
    if BEGIN in source and END in source:
        old = source[source.index(BEGIN):source.index(END) + len(END)]
        if config_file.name in old and '"managed_by": "'+OWNER+'"' in old:
            source = source.replace(old, block, 1)
            return source
    if begin in source or end in source:
        if source.count(begin) != 1 or source.count(end) != 1:
            raise ValueError("自有配置标记不完整，未修改宿主设置")
        start = source.index(begin)
        finish = source.index(end, start) + len(end)
        return source[:start] + block + source[finish:]
    if re.search(r"(?:id\s*:\s*|\"id\"\s*:\s*\")['\"]?"+re.escape(owner)+r"(?:['\"]|\s|$)", source):
        raise ValueError("同名插件条目不属于此配置器，未覆盖")
    visible = [line for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not visible or visible == ["[]"]:
        comments = "\n".join(line for line in source.splitlines() if line.lstrip().startswith("#"))
        return (comments + "\n" if comments else "") + block
    if not visible[0].lstrip().startswith("-") or any(line.strip() in ("---", "...") for line in visible):
        raise ValueError("宿主patch不是单文档操作列表，已保留原文；请手动加载独立Overlay")
    return source + ("\n" if not source.endswith("\n") else "") + block


def configure(connection_config, apply=False, app_path=None):
    """Root controller contract. Tokens enter in memory, never in returned JSON."""
    extra = connection_config.get("host_options", {})
    if not isinstance(extra, dict):
        extra = {}
    detected = detect(app_path or extra.get("app_path"), extra.get("profile_dir"))
    supplied = connection_config.get("config", connection_config)
    connection = {"connection_id": supplied.get("connection_id", supplied.get("connectionId")),
                  "connection_token": supplied.get("connection_token", supplied.get("connectionToken")),
                  "library_id": supplied.get("library_id", supplied.get("libraryId")),
                  "session_scope": supplied.get("session_scope", supplied.get("sessionScope", "connection")),
                  "connection_host": supplied.get("connection_host", supplied.get("connectionHost", "harness")),
                  "enabled": connection_config.get("connection", {}).get("enabled", True),
                  "runtime_dir": supplied.get("runtime_dir", supplied.get("runtimeDir", "~/Library/Application Support/NeuralKnowledge/.runtime"))}
    for key in ("base_url", "allow_remote"):
        if key in supplied:
            connection[key] = supplied[key]
    if connection['connection_host'] not in ('harness','agent'):
        raise ValueError("宿主插件只支持Harness或Agent连接")
    if any(not isinstance(connection[k], str) or not connection[k].strip() for k in ("connection_id", "connection_token", "library_id")):
        raise ValueError("缺少后端创建的连接标识、token或library_id")
    profile = _path(extra.get("profile_dir", detected["profile_dir"]))
    profile_exists, profile_format = _profile_status(profile)
    detected.update(profile_dir=str(profile), profile_exists=profile_exists, profile_format=profile_format)
    detected["legacy_manual_entries"] = _legacy_entries(profile)
    installation = profile / ".neural-knowledge"
    identity = hashlib.sha256(connection["connection_id"].encode()).hexdigest()[:16]
    owner = OWNER + "-" + identity
    config_file = installation / ("connection-" + identity + ".json")
    plugin_config = {"managed_by": OWNER, "connection_file": str(config_file), "host_version": detected["version"]}
    if detected["compatibility"].get("descriptor"):
        plugin_config["host_contract"] = detected["compatibility"]["descriptor"]
    entry = {"id": owner, "name": (installation / "index.js").as_uri(), "config": plugin_config}
    block = "# BEGIN " + owner.upper() + " MANAGED\n- insert: " + json.dumps([entry], ensure_ascii=False) + "\n# END " + owner.upper() + " MANAGED\n"
    patch = profile / "cordis.patch.yml"
    result = {"detected": detected, "supported": detected["supported"], "applied": False,
              "mode": "host_plugin", "library_id": connection["library_id"], "connection_id": connection["connection_id"],
              "plugin_config": plugin_config, "overlay": block, "overlay_file": str(installation / ("overlay-" + identity + ".yml")),
              "patch_file": str(patch), "connection_file": str(config_file), "credentials_read": False,
              "legacy_manual_entries": detected["legacy_manual_entries"],
              "legacy_migration": {"requested": bool(extra.get("migrate_legacy")), "applied": False,
                                   "message": "保留旧手动入口；其采集方式与宿主自动存档不同。未知patch格式不自动重写，请显式检查/停用。"},
              "requires_harness_reload": True,
              "capabilities": {"passive_events": detected["supported"], "raw_roles_and_tool_results": detected["supported"], "context_injection": detected["supported"]}}
    if not detected["supported"]:
        reason = "; ".join(detected["compatibility"].get("diagnostics", [])[:3])
        result.update(message="此版本尚未实证宿主事件契约；" + detected["compatibility"]["message"] + ("：" + reason if reason else ""), fallback="api_proxy")
        if apply:
            raise ValueError(result["message"])
        return result
    if not apply:
        return result
    if not (ROOT / "dist/index.js").exists():
        raise ValueError("宿主插件尚未构建，未更改Harness设置")
    if not profile_exists or patch.is_symlink() or installation.is_symlink():
        raise ValueError("宿主profile不存在或目标是符号链接，未更改配置")
    source = patch.read_text("utf-8") if patch.exists() else "[]\n"
    candidate = _patch(source, block, owner, config_file)
    marker = installation / "managed.json"
    if installation.exists() and any(installation.iterdir()) and not marker.exists():
        raise ValueError("插件安装目录已有未知文件，未覆盖")
    installation.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private(marker, json.dumps({"managed_by": OWNER, "version": "0.4.0"}))
    for name in ("index.js", "configure.js", "proxy.js", "THIRD_PARTY_LICENSES.txt"):
        origin, target = ROOT / "dist" / name, installation / name
        if origin.exists() and origin.resolve() != target.resolve():
            shutil.copy2(origin, target)
    _private(config_file, json.dumps(connection, ensure_ascii=False))
    _private(installation / "package.json", json.dumps({"name": "neural-knowledge-local-adapter", "private": True, "type": "module"}))
    _private(Path(result["overlay_file"]), block)
    _private(marker, json.dumps({"managed_by": OWNER, "version": "0.4.0"}))
    backup = None
    if patch.exists():
        backup = patch.with_name(patch.name + ".neural-knowledge-" + str(time.time_ns()) + ".backup")
        shutil.copy2(patch, backup)
        os.chmod(backup, 0o600)
        if patch.read_text("utf-8") != source:
            raise ValueError("宿主配置在准备期间发生变化，未写入；请重新生成计划")
    _private(patch, candidate)
    return {**result, "applied": True, "backup": str(backup) if backup else None,
            "message": "已更新自有插件条目；需要重载Harness并完成一轮真实新对话，收到存档回执后才算验收"}


def set_enabled(connection_config, enabled, remove=False, app_path=None):
    """Pause at the source without discarding old outbox or other connection bindings."""
    if type(enabled) is not bool or type(remove) is not bool:
        raise ValueError("enabled/remove必须是布尔值")
    if remove:
        enabled = False
    prepared = configure(connection_config, apply=False, app_path=app_path)
    config_file = Path(prepared["connection_file"])
    if not config_file.exists():
        return {"applied": False, "source_capture_disabled": not enabled,
                "message": "本连接没有已安装的私有配置；未修改其他连接", "connection_id": prepared["connection_id"]}
    if config_file.is_symlink():
        raise ValueError("拒绝写入链接的私有配置")
    private = json.loads(config_file.read_text("utf-8"))
    if private.get("connection_id") != prepared["connection_id"]:
        raise ValueError("私有配置属于另一连接，未修改")
    private["enabled"] = enabled
    _private(config_file, json.dumps(private, ensure_ascii=False))
    removed, backup = False, None
    if remove:
        patch = Path(prepared["patch_file"])
        if patch.is_symlink():
            raise ValueError("拒绝更改链接的宿主配置；源采集已禁用")
        if patch.exists():
            source = patch.read_text("utf-8")
            block = prepared["overlay"]
            begin = block.splitlines(keepends=True)[0]
            end = block.splitlines(keepends=True)[-1]
            if source.count(begin) == 1 and source.count(end) == 1:
                start, finish = source.index(begin), source.index(end) + len(end)
                candidate = source[:start] + source[finish:]
                backup = patch.with_name(patch.name + ".neural-knowledge-" + str(time.time_ns()) + ".backup")
                shutil.copy2(patch, backup)
                os.chmod(backup, 0o600)
                _private(patch, candidate or "[]\n")
                removed = True
    return {"applied": True, "enabled": enabled, "source_capture_disabled": not enabled,
            "connection_id": prepared["connection_id"], "managed_entry_removed": removed,
            "backup": str(backup) if backup else None, "outbox_preserved": True,
            "message": "本连接私有enabled已更新；插件每次采集/注入/心跳/投递前重读，旧队列保留"}


if __name__ == "__main__":
    raw = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    request = json.loads(raw) if raw else {}
    action = sys.argv[1] if len(sys.argv) > 1 else "detect"
    if action in ("disable", "enable", "disconnect"):
        result = set_enabled(request, enabled=action == "enable", remove=action == "disconnect", app_path=request.get("app_path"))
    else:
        result = detect(request.get("app_path"), request.get("profile_dir")) if action == "detect" else configure(request, apply=action == "apply", app_path=request.get("app_path"))
    print(json.dumps(result, ensure_ascii=False))
