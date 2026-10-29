"""Portable controller helper; never reads Harness credentials or conversation files."""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import sys
import time
from pathlib import Path

SUPPORTED = ("0.2.1-rc.3",)
OWNER = "neural-knowledge-host"
BEGIN = "# BEGIN NEURAL-KNOWLEDGE-HOST MANAGED\n"
END = "# END NEURAL-KNOWLEDGE-HOST MANAGED\n"
ROOT = Path(__file__).resolve().parent


def _legacy_entries(profile):
    """Recognize only the known packaged bridge; never return env/credential data."""
    found = []
    for filename in ("cordis.patch.yml", "cordis.yml"):
        path = profile / filename
        if not path.exists() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        lines = path.read_text("utf-8").splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^(\s*)-\s+id:\s*['\"]?([A-Za-z0-9_.:-]+)['\"]?\s*(?:#.*)?$", line)
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
            server = re.search(r"serverName:\s*['\"]?([A-Za-z0-9_-]{1,32})", block)
            if ("@deepseek-ai/dsh-mcp-client" in block and server and
                    "知识星图.app/Contents/Resources/backend/harness_bridge.py" in block):
                found.append({"id": match.group(2), "server_name": server.group(1),
                              "source_file": str(path), "mode": "manual_mcp",
                              "target_library": "旧个人库服务；没有本连接library_id绑定，不能推定跟随当前选库"})
    return found


def detect(app_path=None, profile_dir=None):
    app = Path(app_path).expanduser().resolve() if app_path else next((p for p in (
        Path("/Applications/DeepSeek Harness.app"), Path.home() / "Applications/DeepSeek Harness.app") if p.exists()), None)
    version = None
    if app and (app / "Contents/Info.plist").exists():
        with (app / "Contents/Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        version = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
    profile = Path(profile_dir).expanduser().resolve() if profile_dir else Path.home() / ".dsh/profiles/desktop"
    return {"detected": app is not None, "app_path": str(app) if app else None,
            "version": version, "supported": version in SUPPORTED,
            "supported_versions": list(SUPPORTED), "profile_dir": str(profile),
            "profile_exists": (profile / "cordis.yml").exists(),
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
    detected = detect(app_path, extra.get("profile_dir"))
    supplied = connection_config.get("config", connection_config)
    connection = {"connection_id": supplied.get("connection_id", supplied.get("connectionId")),
                  "connection_token": supplied.get("connection_token", supplied.get("connectionToken")),
                  "library_id": supplied.get("library_id", supplied.get("libraryId")),
                  "session_scope": supplied.get("session_scope", supplied.get("sessionScope", "connection")),
                  "enabled": connection_config.get("connection", {}).get("enabled", True),
                  "runtime_dir": supplied.get("runtime_dir", supplied.get("runtimeDir", "~/Library/Application Support/NeuralKnowledge/.runtime"))}
    for key in ("base_url", "allow_remote"):
        if key in supplied:
            connection[key] = supplied[key]
    if any(not isinstance(connection[k], str) or not connection[k].strip() for k in ("connection_id", "connection_token", "library_id")):
        raise ValueError("缺少后端创建的连接标识、token或library_id")
    profile = Path(extra.get("profile_dir", detected["profile_dir"])).expanduser().resolve()
    detected.update(profile_dir=str(profile), profile_exists=(profile / "cordis.yml").exists())
    detected["legacy_manual_entries"] = _legacy_entries(profile)
    installation = profile / ".neural-knowledge"
    identity = hashlib.sha256(connection["connection_id"].encode()).hexdigest()[:16]
    owner = OWNER + "-" + identity
    config_file = installation / ("connection-" + identity + ".json")
    plugin_config = {"managed_by": OWNER, "connection_file": str(config_file), "host_version": detected["version"]}
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
        result.update(message="此版本尚未实证宿主事件契约；可显式使用API代理，只记录经过代理的流量，不冒充完整宿主自动存档", fallback="api_proxy")
        if apply:
            raise ValueError(result["message"])
        return result
    if not apply:
        return result
    if not (ROOT / "dist/index.js").exists():
        raise ValueError("宿主插件尚未构建，未更改Harness设置")
    if not (profile / "cordis.yml").exists() or patch.is_symlink() or installation.is_symlink():
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
        result = detect(request.get("app_path")) if action == "detect" else configure(request, apply=action == "apply", app_path=request.get("app_path"))
    print(json.dumps(result, ensure_ascii=False))
