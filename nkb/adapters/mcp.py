"""MCP server（stdio，JSON-RPC 2.0，零依赖）。

给 Claude Desktop / Cursor / WorkBuddy 这类支持 MCP 的客户端用。
启动后客户端会自动拿到 5 个工具，模型就能自己往知识库里查和写。

关键约束：**stdout 只能吐协议消息**。任何调试输出都必须走 stderr，
否则客户端解析失败，表现为"连上了但工具列表是空的"。
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy

from .. import render
from ..core.brain import Brain
from .._version import __version__

PROTOCOL = "2024-11-05"
SERVER = {"name": "neural-kb", "version": __version__}

TOOLS = [
    {
        "name": "kb_recall",
        "description": ("从神经知识库里做激活扩散检索。返回按激活强度排序的节点、"
                        "分数、跳数和传播路径。事实性问题先查再答；查不到就说没有。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索语句，自然语言即可"},
                "k": {"type": "integer", "description": "返回条数，默认 8", "default": 8},
                "steps": {"type": "integer", "description": "扩散跳数，默认 3", "default": 3},
                "raw": {"type": "boolean", "description": "true 时返回结构化 JSON", "default": False},
                "learn": {"type": "boolean", "description": "明确为 true 才强化并保存；默认只读", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_add",
        "description": "往知识库里加一条知识。会自动按字面重合连到最近的既有节点。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "短标题，将来检索命中的就是它"},
                "text": {"type": "string", "description": "正文，一到三段"},
                "kind": {"type": "string", "default": "concept",
                         "description": "concept/fact/episode/preference/doc/question/answer"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "salience": {"type": "number", "default": 0.6,
                             "description": "初始显著性 0~1，越重要给越高"},
                "impact": {"type": "number", "minimum": -1, "maximum": 1, "default": 0},
                "session_id": {"type": "string", "description": "同一会话标识，用于情绪锚点的有限前后文"},
                "event_at": {"type": "number", "description": "真实事件时间，Unix 秒，缺省为当前时间"},
                "important": {"type": "boolean", "default": False},
            },
            "required": ["label"],
        },
    },
    {
        "name": "kb_link",
        "description": "把两个已有节点连起来并加强这条边。两个 id 或两个精确 label 都行。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string"}, "b": {"type": "string"},
                "w": {"type": "number", "default": 0.4},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "kb_get",
        "description": "按 id 或精确 label 取一个节点的全文和邻居。",
        "inputSchema": {
            "type": "object",
            "properties": {"id_or_label": {"type": "string"}},
            "required": ["id_or_label"],
        },
    },
    {
        "name": "kb_stats",
        "description": "知识库规模、连接强度、各类型节点数量。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_preview",
        "description": "只读预测若干天后的记忆状态；不会删除、强化或保存记忆。",
        "inputSchema": {"type": "object", "properties": {
            "days": {"type": "number", "minimum": 0, "default": 30}
        }},
    },
]


def _resolve(brain: Brain, key: str) -> str:
    if key in brain.nodes:
        return key
    for nid, n in brain.nodes.items():
        if n["label"] == key:
            return nid
    low = key.lower()
    cands = [nid for nid, n in brain.nodes.items() if low in n["label"].lower()]
    if len(cands) == 1:
        return cands[0]
    raise KeyError(f"找不到节点: {key}" + (f"（相似 {len(cands)} 个，请给更精确的 label）"
                                          if cands else ""))


def call_tool(brain: Brain, name: str, args: dict) -> dict:
    """工具分发。返回 MCP 的 result 结构。可被测试直接调用。"""
    before = None
    try:
        if not isinstance(args, dict):
            raise ValueError("arguments 必须是对象")
        mutates = name in ("kb_add", "kb_link") or (name == "kb_recall" and args.get("learn") is True)
        if mutates:
            before = {key: deepcopy(getattr(brain, key)) for key in ("nodes", "edges", "meta", "_vec")}
        result = _dispatch_tool(brain, name, args)
        if result.get("isError"):
            if before is not None:
                for key, value in before.items():
                    setattr(brain, key, value)
            return result
        # 完成返回内容的编码/渲染后才保存，失败的工具不能留下半次写入。
        if mutates:
            brain.persist()
        return result
    except Exception as exc:
        if before is not None:
            for key, value in before.items():
                setattr(brain, key, value)
        return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True}


def _dispatch_tool(brain: Brain, name: str, args: dict) -> dict:
    try:
        if name == "kb_recall":
            r = brain.recall(args["query"], k=int(args.get("k", brain.config.k)),
                             steps=int(args.get("steps", brain.config.steps)))
            learn = args.get("learn", False)
            if not isinstance(learn, bool):
                raise ValueError("learn 必须是布尔值")
            if learn:
                r["reinforced"] = brain.reinforce([h["id"] for h in r["hits"][:4]])
            if args.get("raw"):
                text = json.dumps(r, ensure_ascii=False, indent=1)
            else:
                text = render.to_markdown(r)
            return {"content": [{"type": "text", "text": text}]}

        if name == "kb_add":
            nid = brain.add(
                label=args["label"], text=args.get("text", ""),
                kind=args.get("kind", "concept"),
                tags=args.get("tags") or [],
                salience=float(args.get("salience", 0.6)),
                impact=float(args.get("impact", 0)),
                session_id=args.get("session_id"), event_at=args.get("event_at"),
                meta={"important": args.get("important", False)},
            )
            links = brain.auto_link(nid, top=2)
            return {"content": [{"type": "text", "text": json.dumps(
                {"id": nid, "linked_to": [{"id": i, "w": w} for i, w in links]},
                ensure_ascii=False)}]}

        if name == "kb_link":
            a = _resolve(brain, args["a"])
            b = _resolve(brain, args["b"])
            w = brain.link(a, b, float(args.get("w", 0.4)))
            return {"content": [{"type": "text", "text": json.dumps(
                {"a": a, "b": b, "w": w}, ensure_ascii=False)}]}

        if name == "kb_get":
            nid = _resolve(brain, args["id_or_label"])
            n = brain.nodes[nid]
            nb = [{"id": i, "label": brain.nodes[i]["label"], "w": w}
                  for i, w in brain.neighbors(nid)][:12]
            return {"content": [{"type": "text", "text": json.dumps(
                {"id": nid, "label": n["label"], "kind": n["kind"], "text": n["text"],
                 "tags": n["tags"], "salience": n["salience"], "recalls": n["recalls"],
                 "neighbors": nb}, ensure_ascii=False, indent=1)}]}

        if name == "kb_stats":
            return {"content": [{"type": "text", "text": json.dumps(
                brain.stats(), ensure_ascii=False, indent=1)}]}

        if name == "kb_preview":
            return {"content": [{"type": "text", "text": json.dumps(
                brain.preview(days=args.get("days", 30)), ensure_ascii=False)}]}

        return {"content": [{"type": "text", "text": f"未知工具: {name}"}], "isError": True}
    except Exception as exc:  # 工具内部错误要回给模型，不是崩掉进程
        return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True}


def handle(brain: Brain, msg: dict) -> dict | None:
    """单条消息处理。返回 None 表示这是通知、不需要回。"""
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Invalid Request"}}
    method = msg.get("method")
    mid = msg.get("id")
    if not isinstance(msg.get("params", {}), dict):
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32602, "message": "params must be an object"}}
    if mid is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return _ok(mid, {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER,
        })
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        p = msg.get("params", {})
        if not isinstance(p.get("arguments", {}), dict):
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": "arguments must be an object"}}
        return _ok(mid, call_tool(brain, p.get("name"), p.get("arguments") or {}))
    if method == "ping":
        return _ok(mid, {})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"unsupported method: {method}"}}


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(brain: Brain, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[nkb-mcp] 坏消息: {exc}", file=sys.stderr)
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                     "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            stdout.flush()
            continue
        resp = handle(brain, msg)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
