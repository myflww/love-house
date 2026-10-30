"""One desktop writer and a stable multi-library Controller, with no development data."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import signal
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from nkb.core.atlas import atlas_brain
from nkb.service.host import MemoryHost, make_controller
from nkb.storage.jsonfile import JsonFileStorage

SERVICE_VERSION = "0.4.0"
PORT_STATE = "controller-state.json"


def bind_controller(host, data_dir):
    """Prefer the previous successful port; fall back only if it cannot be bound."""
    state_file = Path(data_dir) / PORT_STATE
    try:
        previous = json.loads(state_file.read_text("utf-8")).get("controller_port")
    except (OSError, ValueError, AttributeError):
        previous = None
    candidates = [previous] if type(previous) is int and 1 <= previous <= 65535 else []
    candidates.extend([8768, 0])
    for port in dict.fromkeys(candidates):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_controller(host))
        except OSError:
            if port == 0:
                raise
            continue
        server.daemon_threads = False
        host.controller_port = server.server_port
        try:
            JsonFileStorage(state_file).save({"controller_port": server.server_port,
                                              "service_version": SERVICE_VERSION})
        except Exception:
            server.server_close()
            raise
        return server
    raise RuntimeError("无法启动本机记忆服务")


def main(host_initializer=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--no-demo", action="store_true", help="Do not register the optional visual example")
    parser.add_argument("--library", help=argparse.SUPPRESS)  # Legacy launch flag; never changes bindings.
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.ready_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_file = (args.data_dir / ".desktop-writer.lock").open("a+")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise SystemExit("知识库已由另一爱之屋或旧版知识星图进程打开，请先关闭另一个窗口后重试。") from None
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    host, server, thread = None, None, None
    stopping = threading.Event()
    try:
        host = MemoryHost(args.data_dir, with_demo=False)
        if host_initializer is not None:
            host_initializer(host)
        example = args.data_dir / "framework-example.brain.json"
        if not args.no_demo and not host.manager.demo_suppressed:
            if not example.exists():
                atlas_brain(example).save()
                example.chmod(0o600)
            host.manager.register_demo(example)
        server = bind_controller(host, args.data_dir)
        def stop(signum=None, frame=None):
            stopping.set()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        def watch_parent():
            while not stopping.wait(1):
                if os.getppid() != args.parent_pid:
                    stopping.set()
                    return
        if args.parent_pid:
            threading.Thread(target=watch_parent, daemon=True).start()
        def serve():
            try:
                server.serve_forever(poll_interval=0.1)
            finally:
                stopping.set()
        thread = threading.Thread(target=serve)
        thread.start()
        ready = {"pid": os.getpid(), "port": server.server_port,
                 "controller_instance_id":host.instance_id,
                 "controller_port": server.server_port, "personal_port": server.server_port,
                 "service_version": SERVICE_VERSION, "library": "default",
                 "name": "爱之屋记忆服务", "personal_name": "爱之屋记忆服务",
                 "selected_library": host.manager.selected_id}
        JsonFileStorage(args.ready_file).save(ready)
        args.ready_file.chmod(0o600)
        print(json.dumps({"status": "ready", **ready}, ensure_ascii=False), flush=True)
        stopping.wait()
        print("Desktop Controller stopped cleanly", flush=True)
    finally:
        if server:
            if thread:
                server.shutdown()
            server.server_close()
        if thread:
            thread.join()
        if host:
            host.stop()
        args.ready_file.unlink(missing_ok=True)
        lock_file.close()


if __name__ == "__main__":
    main()
