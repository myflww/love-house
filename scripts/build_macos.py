#!/usr/bin/env python3
"""Build a self-contained native macOS app; does not install or launch its GUI."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import importlib.util
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "爱之屋"
BUNDLE_ID = "local.neural-knowledge.atlas"


def project_version():
    tree = ast.parse((ROOT / "nkb/_version.py").read_text("utf-8"))
    for statement in tree.body:
        if (isinstance(statement, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__"
                        for target in statement.targets)):
            value = ast.literal_eval(statement.value)
            if isinstance(value, str):
                return value
    raise RuntimeError("Missing literal __version__ in nkb/_version.py")


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def clean_environment(python_home):
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE", "DYLD_LIBRARY_PATH"):
        env.pop(key, None)
    env.update(PYTHONHOME=str(python_home), PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    return env


def harness_overlay(app):
    specification = importlib.util.spec_from_file_location("atlas_harness_bridge", ROOT / "desktop/harness_bridge.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.overlay_for_app(app)


def credential_identity(path):
    """Read the helper's identity without opening Keychain or a provider credential."""
    result = subprocess.run(["/usr/bin/codesign", "-d", "-r-", "--verbose=4", str(path)],
                            check=True, capture_output=True, text=True)
    lines = (result.stdout + result.stderr).splitlines()
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "cdhash": next(line.partition("=")[2] for line in lines if line.startswith("CDHash=")),
            "requirement": next(line for line in lines if "designated =>" in line)}


def smoke_credentials(resources):
    """Exercise only a fresh FAKE Keychain account, never a provider's real key."""
    python = resources / "python/bin/python3.12"
    code = r'''
import json,uuid
from nkb.service.credentials import KeyStore,KeyStoreError
ref={"provider":"FAKE-BUILD-SMOKE","library_id":"FAKE-"+uuid.uuid4().hex,"connection_id":"FAKE-"+uuid.uuid4().hex}
value="FAKE-NOT-A-REAL-KEY-"+uuid.uuid4().hex
store=KeyStore(allow_source_build=False)
metadata=store.set(ref,value,persist=True)
assert set(metadata)=={"storage","key_saved","credential_ready"}
assert metadata["storage"] in ("keychain","session") and metadata["credential_ready"]
assert metadata["key_saved"] is (metadata["storage"]=="keychain")
assert store.get(ref)==value
assert store.get({**ref,"connection_id":"FAKE-OTHER"})==""
try:
    removed=store.delete(ref)
    assert not removed["credential_ready"] and store.get(ref)==""
    cleanup="confirmed"
except KeyStoreError:
    assert metadata["storage"]=="session"
    cleanup="session-cleared; system deletion unavailable, not claimed"
print(json.dumps({"fake_credential_metadata":metadata,"cleanup":cleanup}))
'''
    run([python, "-s", "-c", code], cwd=resources / "backend", env=clean_environment(resources / "python"), timeout=45)


def smoke_test(resources):
    """Disposable Controller acceptance: automatic capture, registry, persona and restart."""
    import sqlite3
    python = resources / "python/bin/python3.12"
    backend = resources / "backend"
    env = clean_environment(resources / "python")
    with tempfile.TemporaryDirectory(prefix="neural-controller-smoke-") as directory:
        temp = Path(directory)
        data_dir = temp / "data"
        ready = data_dir / ".runtime/app.json"
        expected_ids = None
        library_a = library_b = cid = token = old_port = None
        for iteration in range(2):
            with (temp / "backend.log").open("ab") as log:
                child = subprocess.Popen([str(python), "-s", "-u", str(backend / "desktop_server.py"),
                                          "--data-dir", str(data_dir), "--ready-file", str(ready),
                                          "--parent-pid", str(os.getpid())], cwd=backend, env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 25
                    while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(.05)
                    assert ready.exists(), (temp / "backend.log").read_text()
                    state = json.loads(ready.read_text())
                    assert state["service_version"] == "0.4.0"
                    assert state["controller_port"] == state["port"] == state["personal_port"]
                    if old_port is not None:
                        assert old_port == state["controller_port"], "Controller port was not reused"
                    old_port = state["controller_port"]
                    base = f"http://127.0.0.1:{old_port}"

                    def api(path, body=None, library=None, credential=None):
                        headers = {"Content-Type": "application/json"}
                        if library: headers["X-NKB-Library"] = library
                        if credential: headers["Authorization"] = "Bearer " + credential
                        request = Request(base + path, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=headers)
                        with urlopen(request, timeout=12) as response:
                            return json.load(response)

                    def capture(event_id, user):
                        payload = {"session_id": "packaged-session", "event_id": event_id, "event_type": "turn/end",
                                   "record": {"schema": "deepseek-harness-event/v1",
                                              "raw_event": {"type": "turn/end", "attachments": [{"id": "preserved-original"}]},
                                              "normalized": {"type": "turn", "status": "complete", "turn_id": event_id,
                                                             "user": user, "assistant": "助手原始响应（打包自检）"}}}
                        return api(f"/api/connections/{cid}/events", payload, credential=token)

                    assert api("/api/health")["version"] == project_version()
                    with urlopen(base + "/", timeout=5) as response:
                        assert b"<html" in response.read()
                    if iteration == 0:
                        assert api("/api/libraries")["selected_id"] == "default"
                        assert api("/api/graph")["nodes"] == []
                        assert api("/api/connections")["connections"] == []
                        library_a = api("/api/libraries", {"name": "打包测试库甲"})["library"]["id"]
                        library_b = api("/api/libraries", {"name": "打包测试库乙"})["library"]["id"]
                        connection = api("/api/connections", {"name": "打包被动存档", "host": "harness", "library_id": library_a, "session_scope": "connection"})
                        cid, token = connection["connection"]["id"], connection["config"]["connectionToken"]
                        assert capture("persona", "导入人格：\n只由测试用户明确写下的人格原文")["accepted"]
                        capture("style-one", "我希望你说话温柔一点")
                        capture("style-two", "以后请你语气温柔一点")
                        persona = api("/api/persona", library=library_a)
                        assert "明确写下" in persona["manual"] and persona["learned"]
                        api("/api/library/select", {"library_id": library_b})
                        capture("after-switch", "换画面后仍只属于甲库的原文")
                        assert capture("after-switch", "换画面后仍只属于甲库的原文")["duplicate"]
                        assert api("/api/graph", library=library_b)["nodes"] == []
                        assert api("/api/graph")["nodes"] == [], "Unscoped API followed GUI selection"
                        graph = api("/api/graph", library=library_a)
                        expected_ids = {n["id"] for n in graph["nodes"]}
                        assert len(expected_ids) == 4
                        assert next(c for c in api("/api/connections")["connections"] if c["id"] == cid)["library_id"] == library_a
                        organizer = api("/api/organizer", library=library_a)
                        assert organizer["settings"]["enabled"] is False
                        before_preview = {n["id"] for n in api("/api/graph", library=library_a)["nodes"]}
                        preview = api("/api/organizer/preview", {}, library=library_a)
                        assert preview["will_call_model"] is False
                        assert {n["id"] for n in api("/api/graph", library=library_a)["nodes"]} == before_preview
                        try:
                            api("/api/organizer/run", {}, library=library_a)
                        except HTTPError as error:
                            assert error.code == 400
                        else:
                            raise AssertionError("Disabled organizer falsely queued a run")
                        print("Bundled organizer: disabled by default, preview read-only, paused run rejected; no model request")
                        print("Bundled Controller: two blank libraries + passive complete events + fixed binding + persona import/learning OK")
                    else:
                        graph = api("/api/graph", library=library_a)
                        assert {n["id"] for n in graph["nodes"]} == expected_ids
                        assert all(n["meta"]["assistant_reply"] == "助手原始响应（打包自检）" for n in graph["nodes"])
                        assert len(api("/api/activity", library=library_a)["events"]) == 4
                        assert api("/api/graph", library=library_b)["nodes"] == []
                        assert api("/api/graph")["nodes"] == []
                        print("Bundled restart: stable Controller port, library isolation, original dialogue and activity restored")
                    duplicate = subprocess.run([str(python), "-s", str(backend / "desktop_server.py"),
                                                "--data-dir", str(data_dir), "--ready-file", str(temp / "duplicate.json")],
                                               cwd=backend, env=env, capture_output=True, timeout=10)
                    assert duplicate.returncode != 0 and not (temp / "duplicate.json").exists(), "Global writer lock failed"
                    child.terminate(); child.wait(timeout=10)
                    assert child.returncode == 0 and not ready.exists()
                    try: urlopen(base + "/api/health", timeout=.4)
                    except OSError: pass
                    else: raise AssertionError("Controller remained open after stop")
                finally:
                    if child.poll() is None:
                        child.kill(); child.wait()
        with sqlite3.connect(data_dir / "capture.sqlite3") as db:
            rows = db.execute("SELECT payload FROM receipts ORDER BY received").fetchall()
        assert len(rows) == 4
        assert all(json.loads(row[0])["record"]["raw_event"]["attachments"][0]["id"] == "preserved-original" for row in rows)
        print("Bundled raw archive: original host attachment references persisted, no model tool calls used")


def smoke_harness(resources):
    """Legacy MCP stays tools_only and fixed to --library-id, independent of GUI selection."""
    python = resources / "python/bin/python3.12"
    backend = resources / "backend"
    env = clean_environment(resources / "python")
    with tempfile.TemporaryDirectory(prefix="neural-legacy-mcp-smoke-") as directory:
        temp = Path(directory); ready = temp / "data/.runtime/app.json"
        with (temp / "backend.log").open("ab") as log:
            child = subprocess.Popen([str(python), "-s", "-u", str(backend / "desktop_server.py"),
                                      "--data-dir", str(temp / "data"), "--ready-file", str(ready),
                                      "--parent-pid", str(os.getpid())], cwd=backend, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 25
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline: time.sleep(.05)
                assert ready.exists(), (temp / "backend.log").read_text()
                port = json.loads(ready.read_text())["controller_port"]
                def api(path, body=None, library=None):
                    headers = {"Content-Type": "application/json"}
                    if library: headers["X-NKB-Library"] = library
                    req = Request(f"http://127.0.0.1:{port}" + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
                    with urlopen(req, timeout=8) as response: return json.load(response)
                other = api("/api/libraries", {"name": "GUI正在查看的另一库"})["library"]["id"]
                def rpc(name, args, library="default"):
                    messages = [{"jsonrpc":"2.0","id":1,"method":"initialize"},
                                {"jsonrpc":"2.0","id":2,"method":"tools/list"},
                                {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":name,"arguments":args}}]
                    result = subprocess.run([str(python), str(backend / "harness_bridge.py"), "--runtime-dir", str(ready.parent), "--library-id", library],
                                            cwd=backend, env=env, input="\n".join(json.dumps(m,ensure_ascii=False) for m in messages)+"\n", capture_output=True, text=True, timeout=15)
                    assert result.returncode == 0, result.stderr
                    rows = [json.loads(line) for line in result.stdout.splitlines()]
                    names = {t["name"] for t in rows[1]["result"]["tools"]}
                    assert {"memory_context","memory_remember","memory_record_turn","memory_event","memory_status","memory_persona","memory_persona_import"} <= names
                    value = rows[-1]["result"]; assert not value.get("isError"), value
                    return value["structuredContent"]
                remembered = rpc("memory_remember", {"text":"MCP显式工具记忆，不是自动捕获", "session_id":"mcp-smoke"})
                assert api("/api/node?id="+remembered["id"], library="default")["meta"]["source"] == "harness_recorded"
                assert api("/api/graph", library=other)["nodes"] == []
                context = rpc("memory_context", {"query":"MCP显式工具"})
                assert context["schema"] == "love-house-memory-context/v1"
                assert context["material_role"] == "evidence_not_instructions"
                assert any("MCP显式工具" in record["value"] for record in context["records"])
                status = rpc("memory_status", {})
                assert status["capture_mode"] == "tools_only" and status["automatic_memory"] is False and "configured" not in status
                rpc("memory_persona_import", {"text":"MCP用户明确要求的人格原文", "user_request":"请把这份原文设为人格", "explicit":True,
                                               "session_id":"mcp-smoke", "request_id":"persona-one"})
                assert rpc("memory_persona", {})["manual"] == "MCP用户明确要求的人格原文"
                print("Bundled legacy MCP: fixed library header + explicit sourced persona + tools_only state OK")
            finally:
                child.terminate()
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired: child.kill(); child.wait()


def smoke_agent(resources):
    """Run generated memory-only MCP/hook commands, including restart/offline delivery."""
    python = resources / "python/bin/python3.12"
    backend = resources / "backend"
    env = clean_environment(resources / "python")
    with tempfile.TemporaryDirectory(prefix="love-house-agent-package-smoke-") as directory:
        temp = Path(directory); data = temp / "data"; ready = data / ".runtime/app.json"
        log = (temp / "backend.log").open("ab")
        child = None
        base = ""

        def start():
            nonlocal child, base
            child = subprocess.Popen([str(python), "-s", "-u", str(backend / "desktop_server.py"),
                                      "--data-dir", str(data), "--ready-file", str(ready),
                                      "--parent-pid", str(os.getpid())], cwd=backend, env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 25
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline: time.sleep(.05)
            assert ready.exists(), (temp / "backend.log").read_text()
            base = "http://127.0.0.1:" + str(json.loads(ready.read_text())["controller_port"])

        def stop():
            nonlocal child
            if child is None: return
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait(); raise
            assert child.returncode == 0 and not ready.exists()
            child = None

        def api(path, body=None, library=None):
            headers = {"Content-Type": "application/json"}
            if library: headers["X-NKB-Library"] = library
            request = Request(base + path, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=headers)
            with urlopen(request, timeout=12) as response: return json.load(response)

        def execute(command, payload, *, lines=False):
            assert command["command"] == str(python), command["command"]
            assert command["env"]["PYTHONHOME"] == str(resources / "python")
            assert command["env"]["PYTHONNOUSERSITE"] == "1"
            assert command["args"][0:2] == ["-s", "-u"]
            assert Path(command["args"][2]).is_file()
            config_path = Path(command["args"][-1])
            assert config_path.is_file() and config_path.stat().st_mode & 0o077 == 0
            public = json.dumps(command)
            assert "api_key" not in public.lower() and "token" not in public.lower()
            result = subprocess.run([command["command"], *command["args"]],
                                    cwd=temp, env={**env, **command["env"]}, input=payload,
                                    text=True, capture_output=True, timeout=20)
            assert result.returncode == 0, result.stderr or result.stdout
            assert not result.stderr, result.stderr
            return [json.loads(line) for line in result.stdout.splitlines()] if lines else json.loads(result.stdout)

        def rpc(name, arguments=None):
            messages = [{"jsonrpc":"2.0","id":1,"method":"initialize"},
                        {"jsonrpc":"2.0","id":2,"method":"tools/list"},
                        {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":name,"arguments":arguments or {}}}]
            rows = execute(mcp, "\n".join(json.dumps(message, ensure_ascii=False) for message in messages) + "\n", lines=True)
            assert rows[0]["result"]["serverInfo"]["name"] == "love-house-agent-memory"
            assert {"memory_status", "memory_context", "memory_record_turn"} <= {tool["name"] for tool in rows[1]["result"]["tools"]}
            value = rows[2]["result"]; assert not value.get("isError"), value
            return value["structuredContent"]

        try:
            start()
            library = api("/api/libraries", {"name":"打包通用Agent记忆库"})["library"]["id"]
            created = api("/api/connections", {"name":"无模型Key的Agent", "host":"agent", "library_id":library, "session_scope":"connection"})
            cid = created["connection"]["id"]
            config = api(f"/api/connections/{cid}/config")
            assert config["configuration_ready"] and config["connection_config_public"]["model_api_key_required"] is False
            assert config["client_api_key"] == "" and config["requires_host_hook_for_automatic_capture"]
            mcp = next(iter(config["mcp_config"]["mcpServers"].values())); hook = config["hook_config"]
            assert Path(mcp["args"][2]) == backend / "agent_memory_bridge.py"
            assert Path(hook["args"][2]) == backend / "agent_memory_hook.py"
            status = rpc("memory_status")
            assert status["connected"] and status["automatic_memory"] is False and status["capture_mode"] == "tools_only"
            rpc("memory_record_turn", {"session_id":"agent-smoke", "request_id":"manual", "user":"真实导入的测试用户原文", "assistant":"真实导入的测试助手原文"})
            assert rpc("memory_status")["automatic_memory"] is False, "Manual tools falsely claimed automatic capture"
            partial = {"session_id":"agent-smoke", "turn_id":"hook", "status":"partial", "user":"原生钩子用户原文", "assistant":"未完成回复"}
            assert execute(hook, json.dumps(partial, ensure_ascii=False))["archive_committed"]
            assert rpc("memory_status")["automatic_memory"] is False, "Partial hook falsely claimed automatic capture"
            complete = {**partial, "status":"complete", "assistant":"原生钩子完整助手回复"}
            result = execute(hook, json.dumps(complete, ensure_ascii=False))
            assert result["accepted"] and result["saved"] and not result["queued"]
            assert rpc("memory_status")["automatic_memory"] is True
            assert len(api("/api/graph", library=library)["nodes"]) == 2
            assert api("/api/graph")["nodes"] == []
            stop()
            offline = {**complete, "turn_id":"offline", "user":"离线钩子原文", "assistant":"离线时的完整回复"}
            queued = execute(hook, json.dumps(offline, ensure_ascii=False))
            assert queued["queued"] and queued["saved"] is False and queued["status"] == "queued_offline"
            start()
            status = rpc("memory_status")  # Starts the real reconnect worker with the same saved configuration.
            assert status["connected"]
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                graph = api("/api/graph", library=library)
                if len(graph["nodes"]) == 3: break
                time.sleep(.1)
            assert len(graph["nodes"]) == 3, "Persisted hook queue did not recover after Controller restart"
            outbox = data / "agent-outbox" / cid
            assert not list(outbox.glob("*.json"))
            assert api("/api/graph")["nodes"] == []
            print("Bundled Agent MCP: generated command/PYTHONHOME works; no vendor key; manual/partial stays tools_only; complete hook records automatically; offline queue/reconnect preserves fixed library")

            single_library = api("/api/libraries", {"name":"打包默认单窗口隐私库"})["library"]["id"]
            single = api("/api/connections", {"name":"默认只记所选窗口", "host":"agent", "library_id":single_library})
            single_cid = single["connection"]["id"]
            assert single["connection"]["session_scope"] == "next_session"
            single_config = api(f"/api/connections/{single_cid}/config")
            assert single_config["connection_config_public"]["window_only"] is True
            assert single_config["connection_config_public"]["bound_session_id"] is None
            single_hook = single_config["hook_config"]
            own = {"session_id":"packaged-window-A", "turn_id":"first-real-turn", "status":"complete",
                   "user":"PACKAGED-OWN-WINDOW-A", "assistant":"Actual reply from the selected packaged window"}
            saved = execute(single_hook, json.dumps(own))
            assert saved["accepted"] and saved["saved"] and not saved["queued"]
            private = Path(single_config["private_path"])
            assert json.loads(private.read_text())["bound_session_id"] == own["session_id"]
            foreign_marker = "PACKAGED-FOREIGN-WINDOW-B-MUST-NEVER-BE-COLLECTED"
            foreign = {**own, "session_id":"packaged-window-B", "turn_id":"foreign-turn", "user":foreign_marker}
            ignored = execute(single_hook, json.dumps(foreign))  # A new real client process reloads the saved local claim.
            assert ignored["status"] == "ignored_scope" and not ignored["accepted"] and not ignored["queued"]
            assert not ignored["saved"] and not ignored["local_queue_committed"]
            assert not list((data / "agent-outbox" / single_cid).glob("*.json"))
            assert all(foreign_marker.encode() not in p.read_bytes() for p in data.rglob("*") if p.is_file())
            stop(); start()
            refreshed = api(f"/api/connections/{single_cid}/config")
            assert refreshed["connection"]["session_scope"] == own["session_id"]
            assert refreshed["connection_config_public"]["bound_session_id"] == own["session_id"]
            assert json.loads(private.read_text())["bound_session_id"] == own["session_id"]
            graph = api("/api/graph", library=single_library)
            assert len(graph["nodes"]) == 1 and "PACKAGED-OWN-WINDOW-A" in graph["nodes"][0]["text"]
            assert api("/api/graph")["nodes"] == []
            print("Bundled default single-window privacy: next_session binds only real hook A; client B ignored before outbox/raw disk; reloaded Controller/config remains A")
        finally:
            try: stop()
            finally: log.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(shutil.which("python3.12") or sys.executable))
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"{APP_NAME}.app")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--native-smoke", action="store_true", help="Run isolated WKWebView self-test; never installs")
    parser.add_argument("--icon", type=Path, default=ROOT / "assets/branding/love-house-icon.png", help="Approved imagegen PNG source; only iconset resizing/encoding is performed")
    args = parser.parse_args()
    icon = args.icon.expanduser().resolve()
    if not icon.is_file():
        raise SystemExit(f"Approved Love House icon PNG is required: {icon}")
    if project_version() != "0.6.0":
        raise SystemExit("Freeze project version at 0.6.0 before creating this desktop candidate")
    extension = ROOT / "extensions/deepseek-harness"
    if not (extension / "dist/index.js").is_file() or not (extension / "configure.py").is_file():
        raise SystemExit("Automatic-capture extension is not built/frozen: dist/index.js and configure.py are required")
    interpreter = args.python.resolve()
    runtime = interpreter.parent.parent
    if not (runtime / "lib/python3.12/os.py").exists():
        raise SystemExit(f"Expected a complete Python 3.12 runtime, found {runtime}")
    app = args.output.resolve()
    installed_helper = Path.home() / "Applications" / f"{APP_NAME}.app" / "Contents/MacOS/NeuralCredential"
    installed_app = installed_helper.parents[2]
    if app == installed_app.resolve() or app.parent in (Path.home() / "Applications", Path("/Applications")):
        raise SystemExit("Create a candidate outside Applications; this builder never installs over a user's app")
    existing_identity = credential_identity(installed_helper) if installed_helper.is_file() else None
    app.parent.mkdir(parents=True, exist_ok=True)
    staging = app.with_name(app.stem + ".building.app")
    if staging.exists():
        shutil.rmtree(staging)
    contents = staging / "Contents"
    resources = contents / "Resources"
    executable = contents / "MacOS/NeuralAtlas"
    executable.parent.mkdir(parents=True)
    resources.mkdir()
    print(f"Bundling runtime: {runtime}")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", ".pytest_cache", "node_modules", ".git")
    shutil.copytree(runtime, resources / "python", symlinks=True, ignore=ignore)
    backend = resources / "backend"
    backend.mkdir()
    shutil.copytree(ROOT / "nkb", backend / "nkb", ignore=ignore)
    shutil.copy2(ROOT / "desktop/server.py", backend / "desktop_server.py")
    shutil.copy2(ROOT / "desktop/harness_bridge.py", backend / "harness_bridge.py")
    for filename in ("agent_memory_bridge.py", "agent_memory_hook.py"):
        shutil.copy2(ROOT / "desktop" / filename, backend / filename)
    target_extension = backend / "extensions/deepseek-harness"
    target_extension.mkdir(parents=True)
    for filename in ("dist", "configure.py", "host-contract.json", "package.json", "README.md", "LICENSE", "samples", "licenses"):
        source = extension / filename
        if source.is_dir():
            shutil.copytree(source, target_extension / filename, ignore=ignore)
        elif source.is_file():
            shutil.copy2(source, target_extension / filename)
    assert not list((backend / "extensions").rglob("node_modules")), "Development dependencies must not ship"
    overlay = "# Generate the connection in Love House > Connect Chat.\n# Paths and private credentials are generated for the current user at runtime.\n"
    (resources / "deepseek-harness-overlay.example.yaml").write_text(overlay, encoding="utf-8")
    (app.parent / "deepseek-harness-overlay.example.yaml").write_text(overlay, encoding="utf-8")
    for license_name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        if (ROOT / license_name).exists():
            shutil.copy2(ROOT / license_name, resources / license_name)
    python_licenses = ROOT / "assets/licenses/python-3.12.14-20260825"
    if not python_licenses.is_dir():
        raise SystemExit("The approved Python runtime licence bundle is required for redistribution")
    shutil.copytree(python_licenses, resources / "Licenses/python-3.12.14-20260825")
    toolbar_source = ROOT / "assets/ui/toolbar-icons"
    if toolbar_source.is_dir():
        toolbar_target = resources / "ToolbarIcons"
        toolbar_target.mkdir()
        toolbar_manifest = {}
        for name in ("fit", "refresh", "files"):
            source = toolbar_source / f"{name}.png"
            if not source.is_file():
                raise SystemExit(f"Pixel toolbar source is incomplete: {source}")
            shutil.copy2(source, toolbar_target / source.name)
            toolbar_manifest[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        (toolbar_target / "manifest.json").write_text(json.dumps(toolbar_manifest, indent=2), encoding="utf-8")
        provenance = toolbar_source / "crop-provenance.json"
        if provenance.is_file():
            shutil.copy2(provenance, toolbar_target / provenance.name)
    font_source = ROOT / "assets/fonts"
    if font_source.is_dir():
        shutil.copytree(font_source, resources / "Fonts", ignore=ignore)
    run(["/usr/bin/xcrun", "swiftc", "-parse-as-library", "-O", "-framework", "AppKit", "-framework", "WebKit",
         "-target", "arm64-apple-macos13.0", ROOT / "desktop/AtlasApp.swift", "-o", executable])
    credential_helper = contents / "MacOS/NeuralCredential"
    run(["/usr/bin/xcrun", "swiftc", "-O", "-framework", "Security", "-framework", "LocalAuthentication", "-target", "arm64-apple-macos13.0",
         ROOT / "desktop/Keychain.swift", "-o", credential_helper])
    run(["/usr/bin/codesign", "--force", "--sign", "-", "--identifier", "local.neural-knowledge.credential-helper.v1", credential_helper])
    with tempfile.TemporaryDirectory(prefix="neural-atlas-icon-") as temporary:
        temp = Path(temporary)
        iconset = temp / "LoveHouse.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = "@2x" if scale == 2 else ""
                target = iconset / f"icon_{size}x{size}{suffix}.png"
                run(["/usr/bin/sips", "-z", str(size * scale), str(size * scale), icon,
                     "--out", target], stdout=subprocess.DEVNULL)
        run(["/usr/bin/iconutil", "-c", "icns", iconset, "-o", resources / "LoveHouse.icns"])
    shutil.copy2(icon, resources / "AppIconSource.png")
    info = {
        "CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": "NeuralAtlas",
        "CFBundlePackageType": "APPL", "CFBundleShortVersionString": project_version(),
        "CFBundleVersion": "9", "CFBundleIconFile": "LoveHouse",
        "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSHumanReadableCopyright": "2026 myflww · PolyForm Noncommercial 1.0.0; third-party notices included",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    entitlements = ROOT / "desktop/entitlements.plist"
    run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", "--entitlements", entitlements, staging])
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", staging])
    if existing_identity is not None:
        assert credential_identity(credential_helper) == existing_identity, "Credential helper identity changed; candidate must preserve existing Keychain ACL"
        print("Credential helper identity preserved: " + json.dumps(existing_identity))
    if not args.skip_smoke:
        smoke_credentials(resources)
        smoke_test(resources)
        smoke_harness(resources)
        smoke_agent(resources)
    if app.exists():
        shutil.rmtree(app)
    staging.rename(app)
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", app])
    if args.native_smoke:
        run([app / "Contents/MacOS/NeuralAtlas", "--smoke-test"], timeout=90)
    total = sum(p.stat().st_size for p in app.rglob("*") if p.is_file() and not p.is_symlink())
    print(json.dumps({"app": str(app), "bundle_id": BUNDLE_ID,
                      "bytes": total, "icon_source_sha256": hashlib.sha256(icon.read_bytes()).hexdigest(),
                      "installed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
