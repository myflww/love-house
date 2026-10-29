"""Deliberate historical-chat import, without model calls or filesystem access.

Parsing/preview is pure. A whole validated batch is staged with one anchor sync;
the caller persists once in its graph transaction. Imported statements retain
their original roles and source times and never become user-confirmed facts.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re

from ..core.brain import Brain
from ..errors import ValidationError

MAX_BYTES = 4 * 1024 * 1024
MAX_MESSAGES = 2000
MAX_MESSAGE_CHARS = 40000
SCHEMA = "love-house-dialogue-import/v1"
_ROLES = {"user": "user", "human": "user", "用户": "user", "我": "user",
          "assistant": "assistant", "ai": "assistant", "bot": "assistant",
          "model": "assistant", "助手": "assistant", "模型": "assistant",
          "system": "system", "developer": "system", "系统": "system",
          "tool": "tool", "工具": "tool"}
_HEADER = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\[(?P<before>[^\]\n]{4,80})\]\s*)?"
                     r"(?P<role>用户|助手|系统|工具|模型|user|assistant|human|system|tool|AI|model|bot)"
                     r"\s*(?:\[(?P<after>[^\]\n]{4,80})\])?\s*[:：]\s?(?P<body>.*)$", re.I)


def _json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        encoded.encode("utf-8")
        return encoded
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("导出资料包含无法保存的文字或 JSON 结构") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous duplicate field")
        result[key] = value
    return result


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _time(value):
    """Never silently invent the timezone of an old chat export."""
    if value is None or value == "":
        return None, "missing"
    if type(value) in (int, float):
        stamp = value / 1000 if value > 100000000000 else value
        if math.isfinite(stamp) and 0 <= stamp <= 253402300799:
            return float(stamp), "known"
        return None, "invalid"
    if not isinstance(value, str) or len(value) > 100:
        return None, "invalid"
    try:
        date = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if date.tzinfo is None:
            return None, "timezone_missing"
        stamp = date.timestamp()
        return (stamp, "known") if 0 <= stamp <= 253402300799 else (None, "invalid")
    except (ValueError, OverflowError, OSError):
        return None, "invalid"


def _content(raw):
    """Keep unsupported blocks as data, even when only text can be indexed."""
    if isinstance(raw, str):
        return raw, False
    if isinstance(raw, dict) and isinstance(raw.get("parts"), list):
        parts = raw["parts"]
    elif isinstance(raw, list):
        parts = raw
    elif isinstance(raw, dict) and isinstance(raw.get("text"), str):
        return raw["text"], False
    else:
        raise ValidationError("消息 content 必须是文字或受支持的内容分块")
    text, nontext = [], False
    for part in parts:
        if isinstance(part, str):
            text.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str):
            text.append(part["text"])
        else:
            nontext = True
    return "\n".join(text), nontext


def _message(raw, index):
    if not isinstance(raw, dict):
        raise ValidationError(f"第 {index + 1} 条消息不是对象")
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    role_value = raw.get("role", author.get("role", raw.get("from", "")))
    if not isinstance(role_value, str) or role_value.lower() not in _ROLES:
        raise ValidationError(f"第 {index + 1} 条消息的角色无法识别；不会猜测谁说了这句话")
    original = raw.get("content", raw.get("text", raw.get("value")))
    text, nontext = _content(original)
    if len(text) > MAX_MESSAGE_CHARS or len(_json(original)) > MAX_MESSAGE_CHARS * 2:
        raise ValidationError(f"单条消息最多 {MAX_MESSAGE_CHARS} 字；请拆分长记录后导入")
    timestamp = next((raw[k] for k in ("timestamp", "create_time", "created_at", "time") if k in raw), None)
    if timestamp is not None and not isinstance(timestamp, (str, int, float)):
        raise ValidationError(f"第 {index + 1} 条消息的时间须为数字或日期文字")
    source_time, status = _time(timestamp)
    identifier = raw.get("id", raw.get("message_id"))
    if identifier is not None and (not isinstance(identifier, str) or len(identifier) > 500):
        raise ValidationError("消息 id 必须是不超过 500 字的字符串")
    result = {"role": _ROLES[role_value.lower()], "source_role": role_value, "text": text, "source_timestamp": timestamp,
              "source_event_at": source_time, "time_status": status, "position": index}
    if identifier:
        result["source_message_id"] = identifier
    if not isinstance(original, str):
        result["original_content"] = deepcopy(original)
    if nontext:
        result["contains_nontext"] = True
    return result


def _mapping_messages(session, warnings):
    mapping = session["mapping"]
    if not isinstance(mapping, dict) or len(mapping) > MAX_MESSAGES * 3:
        raise ValidationError("ChatGPT mapping 格式错误或消息过多")
    current = session.get("current_node")
    if not current:
        leaves = [key for key, node in mapping.items() if isinstance(node, dict) and not node.get("children")]
        if len(leaves) != 1:
            raise ValidationError("该导出有多条分支但没有 current_node，无法确定真实对话，请先选择要导出的分支")
        current = leaves[0]
    if not isinstance(current, str):
        raise ValidationError("ChatGPT current_node 必须是分支节点标识")
    chain, seen = [], set()
    while current is not None:
        if current in seen or current not in mapping or not isinstance(mapping[current], dict):
            raise ValidationError("ChatGPT 分支存在循环或缺失节点，未导入不完整链")
        seen.add(current)
        node = mapping[current]
        if node.get("message") is not None:
            chain.append(node["message"])
        current = node.get("parent")
    other = sum(isinstance(node, dict) and node.get("message") is not None for key, node in mapping.items() if key not in seen)
    if other:
        warnings.append({"code": "unchosen_branches", "count": other,
                         "message": f"当前分支之外的 {other} 条消息未选择；如需保留，请分别导出其他分支。"})
    return list(reversed(chain))


def _text_messages(content):
    result, role, timestamp, lines = [], None, None, []
    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _HEADER.match(line)
        if match:
            if role is not None:
                result.append({"role": role, "content": "\n".join(lines), "timestamp": timestamp})
            elif any(part.strip() for part in lines):
                raise ValidationError("首条角色标记前有无法归属的文字；请移除说明文字或改用带 role 的 JSON")
            role, timestamp, lines = match["role"], match["before"] or match["after"], [match["body"]]
        else:
            lines.append(line)
    if role is not None:
        result.append({"role": role, "content": "\n".join(lines), "timestamp": timestamp})
    if not result:
        raise ValidationError("未找到明确的角色标记。请使用“用户：… / 助手：…”格式，或导入带 role/content 的 JSON")
    return result


def _parse(content, name, format):
    if not isinstance(content, str) or not content.strip():
        raise ValidationError("请选择聊天导出文件，或粘贴带角色的聊天记录")
    try:
        size = len(content.encode("utf-8"))
    except UnicodeError:
        raise ValidationError("聊天文件包含无法保存的字符") from None
    if size > MAX_BYTES:
        raise ValidationError("单批聊天记录最多 4 MiB，请分批导出")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValidationError("记录名称须为 1~200 字")
    _json(name)
    if format not in ("auto", "json", "text"):
        raise ValidationError("format 只能是 auto、json 或 text")
    stripped = content.lstrip("\ufeff \t\r\n")
    warnings = []
    explicit_text_header = bool(_HEADER.match(stripped.split("\n", 1)[0]))
    if format == "json" or (format == "auto" and stripped.startswith(("[", "{")) and not explicit_text_header):
        try:
            value = json.loads(stripped, object_pairs_hook=_unique_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        except (ValueError, RecursionError):
            raise ValidationError("JSON 无法解析，请检查是否完整导出；没有写入任何记录") from None
        if isinstance(value, dict) and "sessions" in value:
            sessions = value["sessions"]
        elif isinstance(value, dict) and "conversations" in value:
            sessions = value["conversations"]
        elif isinstance(value, dict):
            sessions = [value]
        elif isinstance(value, list) and value and all(isinstance(x, dict) and ("role" in x or "from" in x) for x in value):
            sessions = [{"messages": value}]
        else:
            sessions = value
    else:
        sessions = [{"messages": _text_messages(content)}]
        warnings.append({"code": "text_role_markers", "message": "文字格式按独立行的角色标记分段；若正文中也有“用户：/助手：”示例，请改用 JSON 以免误分段。"})
    if not isinstance(sessions, list) or not sessions or len(sessions) > 100:
        raise ValidationError("需要 messages 数组或最多 100 个会话的导出列表")
    normalized, total = [], 0
    for si, session in enumerate(sessions):
        if not isinstance(session, dict):
            raise ValidationError("会话须为包含 messages 的对象")
        messages = _mapping_messages(session, warnings) if "mapping" in session else session.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValidationError("每个会话都需要非空 messages 数组")
        total += len(messages)
        if total > MAX_MESSAGES:
            raise ValidationError(f"单批最多 {MAX_MESSAGES} 条角色消息，请分批导入")
        parsed = [_message(m, i) for i, m in enumerate(messages)]
        source_id = session.get("id", session.get("conversation_id", session.get("session_id")))
        if source_id is not None and (not isinstance(source_id, str) or len(source_id) > 500):
            raise ValidationError("会话 id 必须是不超过 500 字的字符串")
        title = session.get("title", session.get("name", name))
        if not isinstance(title, str):
            raise ValidationError("会话名称必须是字符串")
        _json(title)
        identity = {"source_id": source_id} if source_id else {"messages": parsed}
        key = _hash(identity)
        stamps = [m["source_event_at"] for m in parsed if m["source_event_at"] is not None]
        if any(b < a for a, b in zip(stamps, stamps[1:])):
            warnings.append({"code": "out_of_order", "session": si,
                             "message": "消息时间存在倒序；保留文件原顺序，不擅自重排或补写。"})
        counts = Counter(m["time_status"] for m in parsed)
        for code in ("missing", "timezone_missing", "invalid"):
            if counts[code]:
                warnings.append({"code": "time_" + code, "session": si, "count": counts[code],
                                 "message": {"missing": "部分消息没有历史时间，将保留为空，不用导入时间冒充。",
                                             "timezone_missing": "部分日期没有时区，保留原日期文字，不猜测时区。",
                                             "invalid": "部分日期无法识别，保留原日期文字，不猜测发生时间。"}[code]})
        if any(m.get("contains_nontext") for m in parsed):
            warnings.append({"code": "nontext", "session": si,
                             "message": "含图片等非文字分块；原始结构作为资料保留，不下载附件，不声称已理解图片。"})
        if any(not m["text"].strip() and not m.get("contains_nontext") for m in parsed):
            warnings.append({"code": "empty_message", "session": si,
                             "message": "包含空消息，保留其角色与时间，不编造正文。"})
        normalized.append({"title": title[:200], "source_id": source_id, "key": key,
                           "session_id": "imported_" + key[:40], "messages": parsed})
    return normalized, warnings


def _units(sessions):
    units = []
    for session in sessions:
        messages, i = session["messages"], 0
        while i < len(messages):
            selected = [messages[i]]
            paired = (messages[i]["role"] == "user" and i + 1 < len(messages)
                      and messages[i + 1]["role"] == "assistant"
                      and messages[i]["text"].strip() and messages[i + 1]["text"].strip())
            if paired:
                selected.append(messages[i + 1])
            identity = [session["key"], selected]
            units.append({"id": "chatimp_" + _hash(identity)[:40], "session": session,
                          "messages": selected, "paired": bool(paired)})
            i += len(selected)
    return units


def _prepare(brain, content, name, format):
    if brain.meta.get("demo"):
        raise ValidationError("示例库不能导入个人聊天，请选择独立记忆库")
    sessions, warnings = _parse(content, name, format)
    units = _units(sessions)
    tombstones = set(brain.meta.get("memory_tombstones", {}).get("node_ids", []))
    known = set(brain.nodes)
    for unit in units:
        unit["status"] = "forgotten" if unit["id"] in tombstones else "duplicate" if unit["id"] in known else "new"
        known.add(unit["id"])
    added = sum(u["status"] == "new" for u in units)
    if added > max(0, brain.config.max_nodes - len(brain.nodes)):
        raise ValidationError(f"本批需要 {added} 个空位；容量不足，未驱逐旧记忆，请分批或调整容量")
    unpaired = sum(len(u["messages"]) for u in units if not u["paired"] and u["messages"][0]["role"] in ("user", "assistant"))
    if unpaired:
        warnings.append({"code": "unpaired", "count": unpaired,
                         "message": f"有 {unpaired} 条用户/助手消息缺少相邻配对，将逐条保留原文，不编造缺失回复。"})
    fingerprint = _hash([[s["key"], s["messages"]] for s in sessions])
    return sessions, units, warnings, fingerprint


def plan_dialogues(brain, *, content, name="聊天记录", format="auto"):
    sessions, units, warnings, fingerprint = _prepare(brain, content, name, format)
    return {"schema": SCHEMA, "read_only": True, "fingerprint": fingerprint,
            "name": name, "message_count": sum(len(s["messages"]) for s in sessions),
            "turn_count": sum(u["paired"] for u in units), "record_count": len(units),
            "added": sum(u["status"] == "new" for u in units),
            "skipped": sum(u["status"] != "new" for u in units),
            "sessions": [{"title": s["title"], "source_id": s["source_id"], "session_id": s["session_id"],
                          "message_count": len(s["messages"]),
                          "first_timestamp": s["messages"][0]["source_timestamp"],
                          "last_timestamp": s["messages"][-1]["source_timestamp"]} for s in sessions],
            "items": [{"id": u["id"], "status": u["status"], "roles": [m["role"] for m in u["messages"]],
                       "excerpt": u["messages"][0]["text"][:120], "timestamp": u["messages"][0]["source_timestamp"]} for u in units[:30]],
            "preview_items_omitted": max(0, len(units) - 30), "warnings": warnings,
            "provenance": "imported_record", "confirmed": False, "model_calls": False,
            "limits": {"bytes": MAX_BYTES, "messages": MAX_MESSAGES}}


class _StagingBrain(Brain):
    def _sync_anchors(self, *, create_edges=True):
        # New records have no inferred emotion. The real graph syncs once after
        # all validated additions, never once per historical message.
        pass


def import_dialogues(brain, *, content, name="聊天记录", format="auto", expected_fingerprint=None, confirm=False):
    if confirm is not True:
        raise ValidationError("先预览聊天记录，再明确确认导入")
    sessions, units, warnings, fingerprint = _prepare(brain, content, name, format)
    if not isinstance(expected_fingerprint, str) or expected_fingerprint != fingerprint:
        raise ValidationError("导入内容与预览不一致，请重新预览后确认")
    stage = _StagingBrain.new(encode=brain.encoder, config=brain.config)
    batch = fingerprint[:40]
    for unit in units:
        if unit["status"] != "new":
            continue
        session, messages = unit["session"], unit["messages"]
        first = messages[0]
        stamp = next((m["source_event_at"] for m in messages if m["source_event_at"] is not None), None)
        text = first["text"] or ("[非文字内容；原始结构保存在来源资料中]" if first.get("contains_nontext")
                                 else "[空消息；保留原始角色与时间]")
        metadata = {"source": "conversation_turn" if unit["paired"] else "history_import",
                    "speaker": first["role"], "origin": "manual_import", "confirmed": False,
                    "important": False, "provenance": "imported_record", "import_batch": batch,
                    "import_name": name, "import_session_title": session["title"],
                    "external_session_id": session["source_id"], "import_messages": deepcopy(messages),
                    "source_time_unknown": stamp is None, "source_event_at": stamp}
        if unit["paired"]:
            metadata.update(assistant_reply=messages[1]["text"],
                            roles={"text": "user", "assistant_reply": "assistant"},
                            turn_hash=hashlib.sha256(json.dumps([session["session_id"], text, messages[1]["text"]], ensure_ascii=False).encode()).hexdigest())
        stage.add("导入对话 · " + (first["text"].strip().splitlines() or [first["role"]])[0][:65],
                  text, kind="episode", id=unit["id"], tags=["历史对话导入"],
                  session_id=session["session_id"], event_at=stamp, salience=.55, impact=0, meta=metadata)
    if not stage.nodes:
        return {"schema": SCHEMA, "saved": True, "added": 0, "skipped": len(units), "ids": [],
                "fingerprint": fingerprint, "warnings": warnings, "provenance": "imported_record"}
    # The anchor algorithm only changes anchor_info on old nodes and edge
    # dictionaries; journal these fields, not every old message/body/vector.
    old_infos = {nid: deepcopy(n["anchor_info"]) for nid, n in brain.nodes.items() if "anchor_info" in n}
    old_edges = {key: dict(edge) for key, edge in brain.edges.items()}
    old_ids = set(brain.nodes)
    ids = list(stage.nodes)
    try:
        brain.nodes.update(stage.nodes)
        brain._vec.update(stage._vec)
        brain._sync_anchors()
    except Exception:
        for nid in ids:
            brain.nodes.pop(nid, None)
            brain._vec.pop(nid, None)
        for nid in old_ids:
            if nid in old_infos:
                brain.nodes[nid]["anchor_info"] = old_infos[nid]
            else:
                brain.nodes[nid].pop("anchor_info", None)
        brain.edges.clear()
        brain.edges.update(old_edges)
        raise
    return {"schema": SCHEMA, "saved": True, "added": len(ids), "skipped": len(units) - len(ids),
            "ids": ids, "fingerprint": fingerprint, "warnings": warnings,
            "message_count": sum(len(s["messages"]) for s in sessions), "provenance": "imported_record"}
