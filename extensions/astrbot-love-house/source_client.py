"""Standard-library SDK for an explicitly registered Agent activity source.

The module may be vendored into a host plugin. It observes nothing by itself;
the host must route only events belonging to its configured Agent before calling
these methods. Model/vendor credentials are neither accepted nor required.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

SCHEMA = "love-house-agent-source/v1"
HOOK_SCHEMA = "love-house-agent-hook/v1"
MAX_EVENT_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUEUE_EVENTS = 5000
MAX_QUEUE_BYTES = 128 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_PLATFORM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_LOCK = threading.RLock()
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None


class SourceClientError(ValueError):
    def __init__(self, message, code="source_error"):
        super().__init__(message)
        self.code = code


def _text(value, field, maximum=40000, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise SourceClientError(field + "格式不正确", "invalid_input")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise SourceClientError(field + "无法保存为 UTF-8", "invalid_input") from None
    return value


def _identifier(value, field):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise SourceClientError(field + "格式不正确", "invalid_identity")
    return value


def _json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        encoded.encode("utf-8")
        return encoded
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise SourceClientError("活动须为可保存的 JSON 资料", "invalid_input") from None


def _safe_details(value, depth=0):
    """Drop execution credentials from optional adapter metadata, not role text."""
    if depth>20:raise SourceClientError('来源附加资料嵌套过深','invalid_input')
    private={'key','apikey','token','authorization','proxyauthorization','password','passwd','secret','secretkey','sessionkey','clientsecret',
             'accesstoken','refreshtoken','credentials','credential','headers','cookies','cookie','env','environment',
             'privatekey','accesskeyid','accesskeysecret'}
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if not isinstance(key,str):raise SourceClientError('附加资料字段名须为文字','invalid_input')
            if re.sub(r'[^a-z0-9]','',key.lower()) in private:continue
            result[key]=_safe_details(item,depth+1)
        return result
    if isinstance(value,list):return [_safe_details(item,depth+1) for item in value]
    return value


def validate_base_url(value):
    value = _text(value, "记忆服务地址", 2000)
    if any(ord(c) < 33 for c in value) or "\\" in value:
        raise SourceClientError("记忆服务地址不合法", "invalid_endpoint")
    try:
        p = urlsplit(value)
        if (p.scheme not in ("http", "https") or not p.hostname or p.username or p.password
                or p.query or p.fragment or p.port is not None and not 1 <= p.port <= 65535):
            raise ValueError()
        local = p.hostname.lower() == "localhost"
        if not local:
            try: local = ipaddress.ip_address(p.hostname).is_loopback
            except ValueError: pass
        if p.scheme == "http" and not local:
            raise ValueError()
        if any(part in (".", "..") for part in p.path.split("/")) or "%" in p.path:
            raise ValueError()
    except ValueError:
        raise SourceClientError("明文地址仅限本机；远程服务须使用明确的 HTTPS 地址", "invalid_endpoint") from None
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


def validate_platforms(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 32
            or any(not isinstance(v, str) or not (v == "*" or _PLATFORM.fullmatch(v)) for v in value)):
        raise SourceClientError("活动平台列表须为1至32个简短标识", "invalid_input")
    if "*" in value and value != ["*"]:
        raise SourceClientError("全部平台标识不能与其他平台混用", "invalid_input")
    return list(dict.fromkeys(value))


def validate_config(value):
    allowed = {"schema", "source_id", "connection_id", "library_id", "runtime_agent_id", "adapter", "platforms",
               "base_url", "token", "outbox_dir", "runtime_dir", "enabled", "revoked"}
    if not isinstance(value, dict) or set(value) - allowed or value.get("schema") != SCHEMA:
        raise SourceClientError("活动来源配置版本不支持", "invalid_config")
    result = dict(value)
    for field in ("source_id", "connection_id", "library_id"):
        result[field] = _identifier(result.get(field), field)
    result["runtime_agent_id"] = _text(result.get("runtime_agent_id"), "宿主 Agent 标识", 200)
    if any(ord(c) < 32 for c in result["runtime_agent_id"]):
        raise SourceClientError("宿主 Agent 标识包含控制字符", "invalid_identity")
    if result.get("adapter") not in ("sdk", "astrbot", "harness"):
        raise SourceClientError("活动来源适配器不支持", "invalid_config")
    result["platforms"] = validate_platforms(result.get("platforms"))
    result["base_url"] = validate_base_url(result.get("base_url"))
    for field in ("enabled", "revoked"):
        if type(result.get(field)) is not bool:
            raise SourceClientError("活动来源启停状态不正确", "invalid_config")
    token = result.get("token")
    if not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 33 for c in token):
        raise SourceClientError("活动来源凭据不正确", "invalid_config")
    if result["enabled"] and not result["revoked"] and not token:
        raise SourceClientError("活动来源凭据缺失", "invalid_config")
    for field in ("outbox_dir", "runtime_dir"):
        if field == "runtime_dir" and not result.get(field):
            result.pop(field, None); continue
        path = _text(result.get(field), field, 4096)
        if not Path(path).is_absolute():
            raise SourceClientError("来源私有目录须为本机绝对路径", "invalid_config")
        result[field] = str(Path(path).resolve())
        if field == "outbox_dir" and Path(result[field]).name != result["source_id"]:
            raise SourceClientError("待交目录必须单独归属于这个活动来源", "invalid_config")
    return result


def _write_private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        if hasattr(os, "fchmod"): os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_json(value)); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path); temporary = None
    finally:
        if temporary: Path(temporary).unlink(missing_ok=True)


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out: raise ValueError("duplicate")
        out[key] = value
    return out


def _read_json(path, limit):
    try:
        with Path(path).open("rb") as f: raw = f.read(limit + 1)
        if len(raw) > limit: raise ValueError()
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict): raise ValueError()
        return value
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise SourceClientError("来源配置或待交记录不可读，原文件未覆盖", "invalid_file") from None


@contextmanager
def _queue_lock(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _LOCK, (folder / ".delivery.lock").open("a+b") as lock:
        if hasattr(os, "fchmod"): os.fchmod(lock.fileno(), 0o600)
        if fcntl: fcntl.flock(lock, fcntl.LOCK_EX)
        elif msvcrt:
            lock.seek(0, 2)
            if lock.tell() == 0: lock.write(b"\0"); lock.flush()
            deadline = time.monotonic() + 5
            while True:
                try: lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1); break
                except OSError:
                    if time.monotonic() >= deadline: raise SourceClientError("来源队列正被使用", "queue_busy") from None
                    time.sleep(.02)
        try: yield
        finally:
            if fcntl: fcntl.flock(lock, fcntl.LOCK_UN)
            elif msvcrt: lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def send_json(request, *, timeout, max_bytes):
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise SourceClientError("记忆服务返回过大", "invalid_response")
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


class SourceClient:
    def __init__(self, config_path, *, transport=None, timeout=5):
        self.path = Path(config_path).expanduser().resolve()
        self.transport = transport or send_json
        self.timeout = max(.05, min(float(timeout), 30))

    def config(self):
        return validate_config(_read_json(self.path, 65536))

    def _active(self, cfg):
        if not cfg["enabled"] or cfg["revoked"]:
            raise SourceClientError("活动来源已暂停或撤销，新内容未入队", "source_paused")

    def _platform(self, cfg, value):
        if not isinstance(value, str) or not _PLATFORM.fullmatch(value):
            raise SourceClientError("活动平台标识不正确", "invalid_platform")
        if cfg["platforms"] != ["*"] and value not in cfg["platforms"]:
            raise SourceClientError("活动平台不属于已登记来源，内容未入队", "source_scope")
        return value

    def _base(self, cfg):
        if not cfg.get("runtime_dir") or urlsplit(cfg["base_url"]).scheme != "http":
            return cfg["base_url"]
        # Runtime hints are local private metadata, not a remote discovery scan.
        folder = Path(cfg["runtime_dir"])
        try:
            files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)[:20]
        except OSError:
            return cfg["base_url"]
        for path in files:
            try:
                info = _read_json(path, 65536)
                port = info.get("controller_port", info.get("port"))
                if info.get("service_version") == "0.4.0" and type(port) is int and 1 <= port <= 65535:
                    return "http://127.0.0.1:" + str(port)
            except SourceClientError:
                continue
        return cfg["base_url"]

    def _request(self, cfg, endpoint, payload):
        self._active(cfg)
        request = Request(self._base(cfg) + "/api/connections/" + cfg["connection_id"] + "/" + endpoint,
                          data=_json(payload).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["token"]}, method="POST")
        try:
            result = self.transport(request, timeout=self.timeout, max_bytes=MAX_RESPONSE_BYTES)
            if not isinstance(result, dict) or result.get("error"):
                raise SourceClientError("记忆服务未确认请求", "service_rejected")
            if result.get("library_id") != cfg["library_id"]:
                raise SourceClientError("服务返回的记忆归属不一致，未使用资料", "scope_mismatch")
            return result
        except SourceClientError:
            raise
        except HTTPError as e:
            raise SourceClientError("记忆来源请求未被接受，记录仍保留", "connection_rejected" if e.code in (401,403) else "service_rejected") from None
        except Exception:
            raise SourceClientError("记忆服务暂不可用，记录仍保留", "offline") from None

    @staticmethod
    def _identity(cfg):
        return {key: cfg[key] for key in ("source_id", "runtime_agent_id", "library_id")}

    def read_context(self, query, session_id, max_chars=8000):
        cfg = self.config(); self._active(cfg)
        query = _text(query, "query", 40000); session_id = _text(session_id, "session_id", 200)
        if type(max_chars) is not int or not 512 <= max_chars <= 32000:
            raise SourceClientError("记忆材料预算不正确", "invalid_input")
        return self._request(cfg, "context", {**self._identity(cfg), "query": query, "session_id": session_id, "max_chars": max_chars})

    def _event(self, cfg, session_id, event_id, platform, normalized, *, occurred_at, details):
        self._active(cfg); platform = self._platform(cfg, platform)
        session_id = _text(session_id, "session_id", 200); event_id = _text(event_id, "event_id", 200)
        stamp = self._event_time(cfg, session_id, event_id, platform, normalized, details, occurred_at)
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0:
            raise SourceClientError("发生时间须为有限时间戳", "invalid_input")
        # Details are raw evidence only, never a replacement for validated roles.
        if details is not None: _json(details)
        evidence = {**normalized.get("evidence", {}), "platform": platform, "source_id": cfg["source_id"],
                    "source_event_at": stamp, "source_runtime_agent_id": cfg["runtime_agent_id"]}
        normalized.update(status="complete", turn_id=event_id, origin="agent_source_adapter", evidence=evidence)
        return {**self._identity(cfg), "session_id": session_id, "event_id": event_id,
                "event_type": "source/" + normalized["type"], "platform": platform, "occurred_at": stamp,
                "record": {"schema": HOOK_SCHEMA, "source_adapter": cfg["adapter"], "raw_event": {"details": _safe_details(details)},
                           "normalized": normalized}}

    def _event_time(self, cfg, session_id, event_id, platform, normalized, details, occurred_at):
        """Keep retry timestamps stable without retaining another copy of prose."""
        key=hashlib.sha256(_json([cfg['source_id'],session_id,event_id]).encode()).hexdigest()
        digest=hashlib.sha256(_json([platform,normalized,_safe_details(details)]).encode()).hexdigest()
        proposed=time.time() if occurred_at is None else occurred_at
        if type(proposed) not in (int,float) or not math.isfinite(proposed) or proposed<0:
            raise SourceClientError('发生时间须为有限时间戳','invalid_input')
        folder=Path(cfg['outbox_dir'])
        with _queue_lock(folder):
            path=folder/'.event-identity.sqlite3'
            db=None
            try:
                db=sqlite3.connect(path,timeout=1)
                with db:
                    db.execute('CREATE TABLE IF NOT EXISTS event_identity(id TEXT PRIMARY KEY,semantic_hash TEXT NOT NULL,at REAL NOT NULL)')
                    db.execute('INSERT OR IGNORE INTO event_identity VALUES(?,?,?)',(key,digest,proposed))
                    row=db.execute('SELECT semantic_hash,at FROM event_identity WHERE id=?',(key,)).fetchone()
                    if row[0]!=digest or occurred_at is not None and row[1]!=occurred_at:
                        raise SourceClientError('同一事件标识已用于不同记录，未改写原文','event_conflict')
                path.chmod(0o600)
                return row[1]
            except sqlite3.Error:
                raise SourceClientError('来源事件标识暂不可保存，新记录未假装入队','queue_unavailable') from None
            finally:
                if db is not None:db.close()

    def record_dialogue(self, user, assistant, session_id, event_id, *, platform, occurred_at=None,
                        delivery_status="generated", details=None):
        if delivery_status not in ("generated", "platform_accepted", "delivered"):
            raise SourceClientError("对话结果状态不正确", "invalid_input")
        normalized = {"type": "turn", "user": _text(user, "user"), "assistant": _text(assistant, "assistant"),
                      "evidence": {"delivery_status": delivery_status}}
        cfg = self.config()
        return self.submit_event(self._event(cfg, session_id, event_id, platform, normalized, occurred_at=occurred_at, details=details))

    def record_observation(self, text, session_id, event_id, *, platform, outcome="observed", source_url="",
                           occurred_at=None, details=None):
        if outcome not in ("observed", "success", "failed"):
            raise SourceClientError("观察结果状态不正确", "invalid_input")
        if source_url:
            p = urlsplit(_text(source_url, "source_url", 4000))
            if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
                raise SourceClientError("来源链接不合法", "invalid_input")
            source_url = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        normalized = {"type": "tool", "text": _text(text, "text"), "outcome": outcome, "source_url": source_url}
        cfg = self.config()
        return self.submit_event(self._event(cfg, session_id, event_id, platform, normalized, occurred_at=occurred_at, details=details))

    def _validate_event(self, cfg, event):
        if not isinstance(event, dict): raise SourceClientError("活动须为对象", "invalid_input")
        for key, value in self._identity(cfg).items():
            if event.get(key) != value:
                raise SourceClientError("事件不属于已登记 Agent 来源，未入队", "source_scope")
        self._platform(cfg, event.get("platform")); _text(event.get("session_id"), "session_id", 200)
        _text(event.get("event_id"), "event_id", 200)
        record = event.get("record")
        normalized = record.get("normalized") if isinstance(record, dict) else None
        if not isinstance(normalized, dict) or normalized.get("type") not in ("turn", "tool") or normalized.get("status") != "complete":
            raise SourceClientError("活动尚无受支持的语义，未假装已形成记忆", "invalid_input")
        if len(_json(event).encode()) > MAX_EVENT_BYTES:
            raise SourceClientError("单条活动超过32MiB，请分段保留真实消息", "event_too_large")

    def submit_event(self, event):
        cfg = self.config(); self._active(cfg); self._validate_event(cfg, event)
        payload = _json(event)
        identity = _json([cfg["source_id"], event["session_id"], event["event_id"]])
        name = hashlib.sha256(identity.encode()).hexdigest() + ".json"
        folder = Path(cfg["outbox_dir"])
        with _queue_lock(folder):
            path = folder / name
            if path.exists():
                old = _read_json(path, MAX_EVENT_BYTES + 65536)
                if old != event:
                    raise SourceClientError("同一事件标识已用于不同记录，未覆盖待交原文", "event_conflict")
            else:
                pending = list(folder.glob("*.json"))
                total = sum(p.stat().st_size for p in pending)
                if len(pending) >= MAX_QUEUE_EVENTS or total + len(payload.encode()) > MAX_QUEUE_BYTES:
                    raise SourceClientError("来源待交队列已满，旧记录保留；请恢复服务后再交新记录", "queue_full")
                _write_private_json(path, event)
        drained = self.drain()
        outcome = drained.get("receipts", {}).get(name)
        if outcome:
            return {**outcome, "queued": False, "local_queue_committed": True,
                    "archive_committed": True, "saved": outcome.get("status") == "saved"}
        return {"accepted": False, "queued": True, "local_queue_committed": True,
                "archive_committed": False, "saved": False, "reason": drained.get("reason", "pending"),
                "source_id": cfg["source_id"], "library_id": cfg["library_id"]}

    def drain(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise SourceClientError("补交批次须为1至1000", "invalid_input")
        cfg = self.config()
        if not cfg["enabled"] or cfg["revoked"]:
            return {"status": "paused", "pending": self.status()["pending"], "receipts": {}}
        folder = Path(cfg["outbox_dir"]); receipts = {}; reason = None
        with _queue_lock(folder):
            for path in sorted(folder.glob("*.json"))[:limit]:
                try:
                    event = _read_json(path, MAX_EVENT_BYTES + 65536); self._validate_event(cfg, event)
                    result = self._request(cfg, "events", event)
                    if result.get("accepted") is not True or result.get("status") not in ("saved", "archived", "pending", "retry", "forgotten"):
                        raise SourceClientError("服务未确认原文持久保存", "unconfirmed")
                    receipts[path.name] = result
                    path.unlink()
                except SourceClientError as exc:
                    reason = exc.code; break
            pending = len(list(folder.glob("*.json")))
        return {"status": "queued" if pending else "ready", "pending": pending, "reason": reason, "receipts": receipts}

    def status(self):
        cfg = self.config(); folder = Path(cfg["outbox_dir"])
        return {key: cfg[key] for key in ("source_id", "library_id", "runtime_agent_id", "adapter", "platforms", "enabled", "revoked")} | {
            "status": "paused" if not cfg["enabled"] or cfg["revoked"] else "configured",
            "pending": len(list(folder.glob("*.json"))) if folder.exists() else 0,
            "full_activity_coverage_verified": False, "model_api_key_required": False}
