"""本机 HTTP 服务：可视化与 JSON API。

同一个知识库的读取、修改和保存共享操作锁。未来时间只通过
``POST /api/preview {days}`` 预览；``/api/forget`` 只维护真实当前时间。
"""
from __future__ import annotations

import copy
import ipaddress
import json
import math
import os
import hashlib
from pathlib import Path
import urllib.request
import urllib.error
import threading
from http.server import BaseHTTPRequestHandler
from ..service.httpd import LoopbackHTTPServer as ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .. import render
from ..core.brain import Brain
from ..core.transaction import rollback_guard
from ..errors import NotFound, ValidationError
from ..viz import builder as viz
from ..ingest.notes import import_notes, plan_notes
from ..companion import (build_context, get_profile, save_profile, remember, record_turn,
                         turn_id, DeepSeekClient, CompanionError)

MAX_BODY_BYTES = 1024 * 1024
MAX_PREVIEW_DAYS = 36500


class RequestError(ValueError):
    """可以安全返回给调用者的请求错误。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _text(data, key, default=None, *, required=False, limit=100000):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise RequestError(f"{key} 必须是长度不超过 {limit} 的字符串")
    if required and not value.strip():
        raise RequestError(f"{key} 不能为空")
    return value.strip() if required else value


def _number(data, key, default, low, high, *, integer=False):
    value = data.get(key, default)
    numeric = type(value) is int if integer else type(value) in (int, float)
    if not numeric or not math.isfinite(value) or not low <= value <= high:
        unit = "整数" if integer else "有限数值"
        raise RequestError(f"{key} 必须是 {low}~{high} 的{unit}")
    return value


def _strings(data, key, default=None, *, limit=100, item_limit=200, required=False):
    value = data.get(key, default if default is not None else [])
    if (not isinstance(value, list) or len(value) > limit
            or any(not isinstance(item, str) or not item.strip()
                   or len(item) > item_limit for item in value)):
        raise RequestError(f"{key} 必须是最多 {limit} 项的非空字符串数组")
    if required and not value:
        raise RequestError(f"{key} 不能为空")
    return value


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _response_snapshot(value):
    """Detach and validate the response before the corresponding save commits.

    JSON serialization and UTF-8 encoding can fail even after deepcopy succeeds
    (sets, NaN, unsupported objects or lone surrogates).  A socket failure after
    a valid committed response remains an acknowledgement/retry issue; this
    check deliberately does not include network output in the transaction.
    """
    result = copy.deepcopy(value)
    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        raise ValidationError("返回资料无法编码为完整 JSON，本次改动未保存") from None
    return result


def make_handler(brain: Brain):
    # Lock the whole operation, including a stable result snapshot and persistence.
    # A save-only lock still lets two operations mutate one another's working state.
    operation_lock = threading.RLock()
    chat_lock = threading.Lock()
    replies = {}  # bounded, per-process retry cache; never contains an API key

    class Handler(BaseHTTPRequestHandler):
        server_version = "neural-kb"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, fmt, *args):
            pass

        def _respond(self, body, code, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; "
                             "script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._respond(body, code, "application/json; charset=utf-8")

        def _html(self, content):
            self._respond(content.encode("utf-8"), 200, "text/html; charset=utf-8")

        def _check_request(self):
            """Reject DNS rebinding and browser cross-origin access, including writes."""
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise RequestError("Host 请求头不合法", 403)
            raw_host = hosts[0]
            try:
                authority = urlsplit("//" + raw_host)
                hostname = authority.hostname
                port = authority.port or 80
                if (not hostname or authority.username is not None
                        or authority.password is not None or authority.path
                        or authority.query or authority.fragment):
                    raise ValueError("invalid host")
            except ValueError:
                raise RequestError("Host 请求头不合法", 403) from None

            bound = self.server.server_address[0].lower()
            local_address = self.connection.getsockname()[0].lower()
            allowed = {bound, local_address}
            if bound in ("0.0.0.0", "::"):
                allowed.discard(bound)
            try:
                loopback = ipaddress.ip_address(local_address).is_loopback
            except ValueError:
                loopback = local_address == "localhost"
            if loopback:
                allowed.update(("localhost", "127.0.0.1", "::1"))
            if hostname.lower() not in allowed or port != self.server.server_port:
                raise RequestError("不受信任的 Host", 403)

            if not self.path.startswith("/") or self.path.startswith("//"):
                raise RequestError("请求地址不合法")
            parsed = urlsplit(self.path)
            if parsed.fragment:
                raise RequestError("请求地址不合法")
            # Opening our empty HTML shell in a top-level window is navigation,
            # not cross-origin access to a user's knowledge. Keep every API and
            # iframe/embedded request behind the existing same-origin policy.
            navigation = (self.command == "GET" and parsed.path in ("/", "/index.html")
                          and self.headers.get("Sec-Fetch-Mode") == "navigate"
                          and self.headers.get("Sec-Fetch-Dest") == "document")

            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1:
                raise RequestError("不允许跨来源访问", 403)
            if origins:
                try:
                    origin = urlsplit(origins[0])
                    same = (origin.scheme == "http" and origin.hostname == hostname
                            and (origin.port or 80) == port
                            and origin.username is None and origin.password is None
                            and not origin.path and not origin.query and not origin.fragment)
                except ValueError:
                    same = False
                if not same:
                    raise RequestError("不允许跨来源访问", 403)
            if (not navigation and
                    self.headers.get("Sec-Fetch-Site", "").lower() in ("cross-site", "same-site")):
                raise RequestError("不允许跨来源访问", 403)
            return parsed

        def _body(self,limit=MAX_BODY_BYTES):
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) != 1 or not lengths[0].isascii()
                    or not lengths[0].isdigit() or self.headers.get("Transfer-Encoding")):
                raise RequestError("需要唯一合法的 Content-Length")
            size = int(lengths[0])
            if size > limit:
                raise RequestError(f"请求体超过 {limit//(1024*1024)} MiB", 413)
            if self.headers.get_content_type() != "application/json":
                raise RequestError("Content-Type 必须是 application/json")
            if size == 0:
                raise RequestError("请求体必须是 JSON 对象")
            try:
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("incomplete body")
                data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                                  parse_float=_finite_float,
                                  object_pairs_hook=_unique_object)
                # Reject lone surrogate escapes as well as invalid input bytes;
                # otherwise a later UTF-8 save can fail after changing the graph.
                json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (UnicodeError, ValueError, RecursionError, TimeoutError):
                raise RequestError("请求体必须是合法 JSON 对象") from None
            if not isinstance(data, dict):
                raise RequestError("请求体必须是 JSON 对象")
            return data

        def _presentation_graph(self,graph):
            from ..companion.dedup import canonical_id,is_duplicate
            present={n['id'] for n in graph['nodes']}
            for node in graph['nodes']:
                canonical=canonical_id(brain,node['id'])
                node['presentation_duplicate_of']=canonical if (canonical in present or canonical in brain.meta.get('memory_tombstones',{}).get('node_ids',[])) and is_duplicate(brain.get(node['id']),brain) else None
            aliases={n['id']:n['presentation_duplicate_of'] for n in graph['nodes'] if n.get('presentation_duplicate_of')}
            combined={}
            for edge in graph['edges']:
                source=aliases.get(edge['source'],edge['source']);target=aliases.get(edge['target'],edge['target'])
                if source==target or source not in present or target not in present:continue
                key=tuple(sorted((source,target)))
                if key not in combined:combined[key]={**edge,'source':source,'target':target}
                else:
                    # Duplicate capture edges are one relation, not stronger evidence.
                    combined[key]['w']=max(combined[key].get('w',0),edge.get('w',0))
                    combined[key]['effective_w']=max(combined[key].get('effective_w',0),edge.get('effective_w',0))
                    combined[key]['active']=combined[key].get('active',False) or edge.get('active',False)
            graph['edges']=list(combined.values())
            return graph

        def _route_get(self, path, query):
            if path == "/api/persona":
                from ..companion import persona_state
                state=persona_state(brain)
                return {**state,"text":state.get("effective_persona",""),"candidates":state.get("proposals",[])}
            if path == "/api/ai/status":
                return {"configured": bool(os.environ.get("DEEPSEEK_API_KEY")),
                        "model": "deepseek-flash", "profile": get_profile(brain),
                        "is_demo": bool(brain.meta.get("demo")),
                        "storage": "local", "automatic_memory": "user_episode",
                        "api_key_saved": False}
            if path == "/api/ai/harness":
                app = next((p for p in (Path.home() / "Applications/爱之屋.app/Contents/Resources", Path.home() / "Applications/知识星图.app/Contents/Resources") if p.is_dir()),Path.home() / "Applications/爱之屋.app/Contents/Resources")
                python = app / "python/bin/python3.12"
                bridge = app / "backend/harness_bridge.py"
                overlay = ("- insert:\n    - id: memory-neural-kb\n"
                           "      name: '@deepseek-ai/dsh-mcp-client'\n"
                           "      config:\n        serverName: neural-memory\n"
                           "        transport: stdio\n"
                           f"        command: {json.dumps(str(python),ensure_ascii=False)}\n"
                           f"        args: [{json.dumps(str(bridge),ensure_ascii=False)}]\n"
                           "        env:\n"
                           f"          PYTHONHOME: {json.dumps(str(app/'python'),ensure_ascii=False)}\n")
                return {"overlay": overlay, "status": "ready" if bridge.exists() else "app_required",
                        "instructions": "打开爱之屋；把配置作为 Harness patch 加载。先调用 memory_context，完成任务后调用 memory_event 或 memory_record_turn。",
                        "command": 'dsh web --patch /绝对路径/neural-memory.cordis.yml',
                        "library": "personal", "context_url": "/api/ai/harness/context",
                        "requires_api_key_for_memory_tools": False}
            if path == "/api/graph":
                return self._presentation_graph(brain.export())
            if path == "/api/stats":
                return brain.stats()
            if path == "/api/health":
                return {"ok": True, "name": brain.name}
            if path == "/api/node":
                try:
                    params = parse_qs(query, strict_parsing=True)
                except ValueError:
                    raise RequestError("需要唯一的节点 id") from None
                ids = params.get("id", [])
                if len(ids) != 1 or not ids[0] or set(params) != {"id"}:
                    raise RequestError("需要唯一的节点 id")
                for node in brain.export()["nodes"]:
                    if node["id"] == ids[0]:
                        return node
                raise RequestError("节点不存在", 404)
            raise RequestError("接口不存在", 404)

        def do_GET(self):
            try:
                parsed = self._check_request()
                if parsed.path in ("/", "/index.html"):
                    return self._html(viz.html_for_serve())
                with operation_lock:
                    result = copy.deepcopy(self._route_get(parsed.path, parsed.query))
                return self._json(result)
            except RequestError as exc:
                return self._json({"error": str(exc)}, exc.status)
            except Exception:
                return self._json({"error": "服务暂时无法完成请求"}, 500)

        def _route_post(self, path, data):
            if path == "/api/ingest":
                from ..companion import ingest_event
                return ingest_event(brain,data)
            if path == "/api/persona/import":
                from ..companion import import_persona
                return import_persona(brain,data.get("text"),data.get("source","ui"),
                    enabled=data.get("enabled",True),expected_revision=data.get("expected_revision"))
            if path == "/api/persona/enabled":
                from ..companion import set_persona_enabled,set_persona_learning,persona_state
                if "enabled" in data:set_persona_enabled(brain,data["enabled"])
                if "learning_enabled" in data:set_persona_learning(brain,data["learning_enabled"])
                return persona_state(brain)
            if path.startswith("/api/persona/candidates/") and path.endswith("/review"):
                from ..companion import review_candidate
                return review_candidate(brain,path.split("/")[4],data.get("action"),data.get("expected_revision"))
            if path == "/api/persona/rollback":
                from ..companion import rollback_persona
                return rollback_persona(brain,data.get("revision"),data.get("expected_revision"))
            if path == "/api/ai/context":
                query = _text(data, "query", required=True, limit=40000)
                return build_context(brain, query, session_id=data.get("session_id"))
            if path in ("/api/ai/profile", "/api/ai/remember", "/api/ai/record", "/api/ai/event"):
                if brain.meta.get("demo"):
                    raise RequestError("请先切换到“我的知识库”，再保存陪伴记忆")
                if path == "/api/ai/profile":
                    return {"profile": save_profile(brain, **{k: data.get(k, "") for k in ("name", "persona", "user_name")}), "saved": True}
                if path == "/api/ai/remember":
                    harness = data.get("origin") == "harness"
                    important = data.get("important", False if harness else True)
                    text = _text(data, "text", required=True, limit=40000)
                    kind = data.get("kind", "fact" if harness else "preference")
                    if harness:
                        if kind not in ("preference", "fact", "episode") or type(important) is not bool:
                            raise RequestError("记忆类型或重要性不合法")
                        nid = brain.add(text.splitlines()[0][:80], text, kind=kind,
                                        salience=.8 if important else .6,
                                        impact=data.get("impact", 0), session_id=data.get("session_id"),
                                        tags=["Harness记录"], meta={"source":"harness_recorded",
                                            "confirmed":False, "speaker":"agent", "important":important})
                        brain.auto_link(nid, top=2)
                    else:
                        nid = remember(brain, text, kind=kind, important=important,
                                       session_id=data.get("session_id"), impact=data.get("impact", 0))
                    return {"id": nid, "saved": True}
                if path == "/api/ai/record":
                    nid = record_turn(brain, data.get("user"), data.get("assistant"),
                                      data.get("session_id"), data.get("request_id"),
                                      origin="manual_harness" if data.get("origin")=="harness" else "manual_record",
                                      external_session_id=data.get("source_session_id"),
                                      source_event_id=data.get("source_event_id"),connection_id=data.get("connection_id"))
                    if data.get("origin") == "harness":
                        brain.nodes[nid]["meta"]["recorded_by"] = "harness"
                    from ..companion.dedup import canonical_id
                    canonical=canonical_id(brain,nid)
                    return {"id": canonical, "record_id":nid, "duplicate_of":canonical if canonical!=nid else None, "saved": True}
                # A tool observation is a sourced report, not a user-confirmed fact.
                text = _text(data, "text", required=True, limit=40000)
                session = _text(data, "session_id", required=True, limit=200)
                request = _text(data, "request_id", required=True, limit=200)
                outcome = data.get("outcome", "observed")
                if outcome not in ("observed", "success", "failed"):
                    raise RequestError("outcome 只能是 observed/success/failed")
                url = urlsplit(_text(data, "source_url", "", limit=4000))
                if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
                    raise RequestError("source_url 需要无认证信息的 HTTP/HTTPS 来源")
                safe_url = url._replace(query="", fragment="").geturl()
                nid = "event_" + turn_id(session, request)[5:]
                digest = hashlib.sha256(json.dumps([text,safe_url,outcome],ensure_ascii=False).encode()).hexdigest()
                old = brain.get(nid)
                if old:
                    if old.get("meta", {}).get("event_hash") != digest:
                        raise RequestError("同一 request_id 已记录不同事件")
                else:
                    brain.add("网页事件 · " + text[:60], text, kind="episode", id=nid, session_id=session,
                              meta={"source": "tool_observation", "source_url": safe_url,
                                    "outcome": outcome, "event_hash": digest,
                                    "confirmed": False, "speaker": "tool", "important": False})
                return {"id": nid, "saved": True, "source_url": safe_url}

            if path in ("/api/import/preview", "/api/import"):
                args = {"files": data.get("files"),
                        "mode": data.get("mode", "heading"),
                        "kind": data.get("kind", "doc")}
                return (plan_notes if path.endswith("/preview") else import_notes)(brain, **args)

            if path == "/api/update":
                nid = _text(data, "id", required=True, limit=200)
                if nid not in brain.nodes:
                    raise RequestError("节点不存在", 404)
                allowed = {"id", "label", "text", "kind", "tags", "salience", "impact",
                           "meta", "event_at", "session_id"}
                if set(data) - allowed:
                    raise RequestError("包含不可编辑的字段")
                fields = {}
                for key, limit in (("label", 500), ("text", 100000), ("kind", 64)):
                    if key in data:
                        fields[key] = _text(data, key, required=key != "text", limit=limit)
                if "tags" in data:
                    fields["tags"] = _strings(data, "tags")
                if "salience" in data:
                    fields["salience"] = _number(data, "salience", 0, 0, 1)
                if "impact" in data:
                    fields["impact"] = _number(data, "impact", 0, -1, 1)
                if "event_at" in data:
                    fields["event_at"] = _number(data, "event_at", 0, 0, 253402300799)
                if "session_id" in data:
                    fields["session_id"] = (None if data["session_id"] is None else
                                             _text(data, "session_id", required=True, limit=200))
                if "meta" in data:
                    meta = data["meta"]
                    if not isinstance(meta, dict):
                        raise RequestError("meta 必须是 JSON 对象")
                    if "session_id" in meta and meta["session_id"] is not None:
                        _text(meta, "session_id", required=True, limit=200)
                    if "event_at" in meta:
                        _number(meta, "event_at", 0, 0, 253402300799)
                    fields["meta"] = meta
                if not fields:
                    raise RequestError("没有待保存的修改")
                brain.update(nid, **fields)
                node = next(n for n in brain.export()["nodes"] if n["id"] == nid)
                return {"id": nid, "node": node}

            if path == "/api/recall":
                query = _text(data, "query", required=True, limit=10000)
                k = _number(data, "k", brain.config.k, 1, 100, integer=True)
                steps = _number(data, "steps", brain.config.steps, 0, 20, integer=True)
                damping = _number(data, "damping", brain.config.damping, 0, 1)
                learn = data.get("learn", False)
                if type(learn) is not bool:
                    raise RequestError("learn 必须是布尔值")
                output_format = data.get("format", "json")
                if output_format not in ("json", "md"):
                    raise RequestError("format 只能是 json 或 md")
                result = brain.recall(query, k=k, steps=steps, damping=damping)
                if learn:
                    result["reinforced"] = brain.reinforce([h["id"] for h in result["hits"][:4]])
                if output_format == "md":
                    result["markdown"] = render.to_markdown(result)
                return result

            if path == "/api/add":
                fields = {
                    "label": _text(data, "label", required=True, limit=500),
                    "text": _text(data, "text", ""),
                    "kind": _text(data, "kind", "concept", required=True, limit=64),
                    "tags": _strings(data, "tags"),
                    "salience": _number(data, "salience", 0.6, 0, 1),
                    "impact": _number(data, "impact", 0.0, -1, 1),
                }
                meta = data.get("meta", {})
                if not isinstance(meta, dict):
                    raise RequestError("meta 必须是 JSON 对象")
                fields["meta"] = meta
                if "event_at" in data:
                    fields["event_at"] = _number(data, "event_at", 0, 0, 253402300799)
                if "session_id" in data:
                    fields["session_id"] = _text(data, "session_id", required=True, limit=200)
                # Validate legacy metadata aliases before the engine interprets them.
                if "event_at" in meta:
                    _number(meta, "event_at", 0, 0, 253402300799)
                if "session_id" in meta:
                    _text(meta, "session_id", required=True, limit=200)
                nid = brain.add(**fields)
                links = brain.auto_link(nid, top=2)
                return {"id": nid, "linked_to": links}

            if path == "/api/link":
                a = _text(data, "a", required=True, limit=200)
                b = _text(data, "b", required=True, limit=200)
                weight = _number(data, "w", 0.4, 0, 1)
                if a not in brain.nodes or b not in brain.nodes:
                    raise RequestError("节点不存在", 404)
                weight = brain.link(a, b, weight)
                return {"a": a, "b": b, "w": weight}

            if path == "/api/reinforce":
                ids = _strings(data, "ids", limit=500, required=True)
                if any(nid not in brain.nodes for nid in ids):
                    raise RequestError("节点不存在", 404)
                result = brain.reinforce(ids)
                return result

            if path == "/api/preview":
                days = _number(data, "days", 0, 0, MAX_PREVIEW_DAYS)
                return self._presentation_graph(brain.preview(days=days))

            if path == "/api/forget":
                # Previous versions destructively simulated a future date here.
                if (set(data) - {"days"} or type(data.get("days", 0)) not in (int, float)
                        or data.get("days", 0) != 0):
                    raise RequestError("forget 仅维护当前时间；未来模拟请使用 /api/preview")
                result = brain.forget()
                return result
            raise RequestError("接口不存在", 404)

        def _ai_chat(self, data):
            message = _text(data, "message", required=True, limit=40000)
            session = _text(data, "session_id", required=True, limit=200)
            request = _text(data, "request_id", required=True, limit=200)
            model = _text(data, "model", "deepseek-flash", required=True, limit=200)
            nid = turn_id(session, request)
            # Serialize model turns without holding the graph lock during network I/O.
            with chat_lock:
                with operation_lock:
                    if brain.meta.get("demo"):
                        raise RequestError("请切换到“我的知识库”，再连接 DeepSeek 聊天")
                    old = brain.get(nid)
                    if old is not None:
                        if old["text"] != message or old.get("meta", {}).get("source") != "conversation_turn":
                            raise RequestError("该请求编号已用于不同内容")
                        if old.get("meta", {}).get("model", model) != model:
                            raise RequestError("该请求编号已用于另一模型，请新建请求")
                        return {"id": nid, "reply": old["meta"]["assistant_reply"], "saved": True,
                                "memory_ids": [], "context": {}, "replayed": True}
                    cached = replies.get(nid)
                    if cached and cached["message"] != message:
                        raise RequestError("该请求编号已用于不同内容")
                    if cached and cached["model"] != model:
                        raise RequestError("该请求编号已用于另一模型，请用原模型补存或新建请求")
                    context = cached["context"] if cached else build_context(brain, message, session_id=session)
                reply = cached["reply"] if cached else DeepSeekClient().reply(
                    api_key=data.get("api_key"), model=model, messages=context["messages"])
                replies[nid] = {"message": message, "reply": reply, "context": context, "model": model}
                while len(replies) > 16:
                    replies.pop(next(iter(replies)))
                with operation_lock:
                    try:
                        with rollback_guard(brain) as guard:
                            record_turn(brain, message, reply, session, request)
                            brain.nodes[nid]["meta"].update(provider="deepseek", model=model,
                                                           context_memory_ids=list(context["memory_ids"]))
                            response = _response_snapshot({"id": nid, "reply": reply, "saved": True,
                                "memory_ids": context["memory_ids"], "context": context})
                            guard.persist()
                    except ValidationError:
                        raise
                    except Exception:
                        return {"reply": reply, "saved": False, "memory_ids": context["memory_ids"],
                                "context": context, "warning": "回复已收到，但本地保存失败。重试相同请求可补存，不会再次调用模型。"}
                return response

        def _harness_context(self, data):
            query = _text(data, "query", required=True, limit=40000)
            session = data.get("session_id")
            port = getattr(self.server, "personal_port", self.server.server_port)
            if port == self.server.server_port:
                with operation_lock:
                    if brain.meta.get("demo"):
                        raise RequestError("请在新版桌面应用中检查个人记忆服务")
                    return {**build_context(brain, query, session_id=session), "library": "personal"}
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ai/context",
                                         data=json.dumps({"query":query,"session_id":session}).encode(),
                                         headers={"Content-Type":"application/json"}, method="POST")
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=10) as response:
                    result = json.load(response)
            except Exception:
                raise RequestError("个人记忆服务暂不可用，请重新启动爱之屋", 503) from None
            return {**result, "library": "personal"}

        def do_POST(self):
            try:
                parsed = self._check_request()
                routes = {"/api/recall", "/api/add", "/api/link", "/api/reinforce",
                          "/api/preview", "/api/forget", "/api/update",
                          "/api/import", "/api/import/preview", "/api/ai/context",
                          "/api/ai/profile", "/api/ai/remember", "/api/ai/record", "/api/ai/event", "/api/ai/chat",
                          "/api/ai/harness/context", "/api/ingest", "/api/persona/import",
                          "/api/persona/enabled", "/api/persona/rollback"}
                if parsed.path not in routes and not (parsed.path.startswith('/api/persona/candidates/') and parsed.path.endswith('/review')):
                    raise RequestError("接口不存在", 404)
                data = self._body()
                if parsed.path == "/api/ai/chat":
                    return self._json(self._ai_chat(data))
                if parsed.path == "/api/ai/harness/context":
                    return self._json(self._harness_context(data))
                with operation_lock:
                    mutates = (parsed.path not in ("/api/preview", "/api/import/preview", "/api/ai/context")
                               and (parsed.path != "/api/recall" or data.get("learn") is True))
                    # Atomic file replacement protects the old disk state. Keep
                    # the in-memory graph equally consistent if an operation or
                    # persistence fails, so a failed write cannot appear later.
                    if mutates:
                        with rollback_guard(brain) as guard:
                            result = _response_snapshot(self._route_post(parsed.path, data))
                            guard.persist()
                    else:
                        result = copy.deepcopy(self._route_post(parsed.path, data))
                return self._json(result)
            except RequestError as exc:
                return self._json({"error": str(exc)}, exc.status)
            except CompanionError as exc:
                return self._json({"error": str(exc), "code": exc.code}, 400 if exc.code in ("missing_key", "invalid_key") else 502)
            except NotFound:
                return self._json({"error": "节点不存在"}, 404)
            except ValidationError as exc:
                return self._json({"error": str(exc)}, 400)
            except (ValueError, TypeError, KeyError, OverflowError):
                return self._json({"error": "请求字段不合法"}, 400)
            except Exception:
                return self._json({"error": "服务暂时无法完成请求"}, 500)

        def do_OPTIONS(self):
            try:
                parsed = self._check_request()
                if parsed.path not in ("/", "/index.html", "/api/graph", "/api/stats",
                                       "/api/health", "/api/node", "/api/recall",
                                       "/api/add", "/api/link", "/api/reinforce",
                                       "/api/preview", "/api/forget", "/api/update",
                                       "/api/import", "/api/import/preview", "/api/ai/status", "/api/ai/harness",
                                       "/api/ai/context", "/api/ai/profile", "/api/ai/remember", "/api/ai/record", "/api/ai/event", "/api/ai/chat",
                                       "/api/ai/harness/context"):
                    raise RequestError("接口不存在", 404)
                return self._respond(b"", 204, "application/json")
            except RequestError as exc:
                return self._json({"error": str(exc)}, exc.status)

    # Internal controller callbacks use exactly the same lock as all HTTP writes.
    # They are Python callables only, never exposed as arbitrary HTTP operations.
    def snapshot():
        with operation_lock:
            return copy.deepcopy(brain.to_dict())
    def transaction(callback):
        with operation_lock:
            with rollback_guard(brain) as guard:
                result = _response_snapshot(callback(brain))
                guard.persist()
                return result
    Handler.memory_snapshot = staticmethod(snapshot)
    Handler.memory_transaction = staticmethod(transaction)
    return Handler


def serve(brain: Brain, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(brain))
    print(f"neural-kb 已启动： http://{host}:{httpd.server_port}")
    print(f"  知识库 {brain.name} · {len(brain.nodes)} 节点 / {len(brain.edges)} 边")
    print("  Ctrl-C 停止")
    return httpd
