"""被动接收连接方事件。部分响应只进有界草稿，不进入记忆或人格证据。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from ..errors import ValidationError
from .memory import MAX_TEXT, _text, record_turn, turn_id
from .persona import import_persona, learn_from_dialogue, persona_state, propose_persona

MAX_PENDING = 32
_IMPORT = re.compile(r"^(?:请)?(?:导入人格|人格设定如下)\s*[:：]\s*(.*)$")


def connected_session_id(connection_id, session_id):
    connection_id = _text(connection_id, "connection_id", 200).strip()
    session_id = _text(session_id, "session_id", 200).strip()
    return "connected_" + sha256(json.dumps([connection_id, session_id], ensure_ascii=False).encode()).hexdigest()[:32]


def _json_data(value, maximum=12000):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise ValidationError("evidence必须是可保存的JSON资料") from None
    if len(encoded) > maximum:
        raise ValidationError("evidence过大，最多12000字")
    return deepcopy(value)


def _url(value):
    if value is None or value == "":
        return ""
    value = _text(value, "source_url", 4000)
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError("source_url必须是无认证信息的HTTP/HTTPS地址")
    return parsed._replace(query="", fragment="").geturl()


def ingest_event(brain, event):
    before = {key: deepcopy(getattr(brain, key)) for key in ("nodes", "edges", "meta", "_vec")}
    try:
        return _ingest_event(brain, event)
    except Exception:
        for key, value in before.items():
            setattr(brain, key, value)
        raise


def _ingest_event(brain, event):
    """event含connection_id/session_id/turn_id/type/status；不联网也不persist。

    type=turn: user/assistant原文；type=tool: text/origin/evidence/outcome；
    type=persona_import: text与explicit=True。status默认complete，可为partial。
    partial字段按最新完整缓冲覆盖而不是append，重放相同片段不会重复累计。
    """
    if brain.meta.get("demo"):
        raise ValidationError("示例库不能接收真实连接事件，请选择独立个人记忆库")
    if not isinstance(event, dict):
        raise ValidationError("event必须是对象")
    connection = _text(event.get("connection_id"), "connection_id", 200).strip()
    external_session = _text(event.get("session_id"), "session_id", 200).strip()
    request = _text(event.get("turn_id"), "turn_id", 200).strip()
    session = connected_session_id(connection, external_session)
    kind = event.get("type", "turn")
    status = event.get("status", "complete")
    if kind not in ("turn", "tool", "persona_import") or status not in ("partial", "complete"):
        raise ValidationError("事件type或status不支持")
    identifier = turn_id(session, request)
    identity = kind + ":" + identifier
    nid = identifier if kind == "turn" else kind + "_" + identifier[5:]
    tomb=brain.meta.get("memory_tombstones", {})
    receipt=(event.get("evidence") or {}).get("archive_receipt_id") if isinstance(event.get("evidence"),dict) else None
    if nid in tomb.get("node_ids",[]) or receipt in tomb.get("raw_ids",[]):
        return {"status":"forgotten","node_ids":[],"duplicate":True,"session_id":session}
    old = brain.get(nid)
    ingestion = deepcopy(brain.meta.get("companion_ingestion", {"pending": {}}))
    pending = ingestion.setdefault("pending", {})
    draft = {}
    if old is not None:
        metadata = old.get("meta", {})
        draft = {"origin": metadata.get("origin", "connected_chat"),
                 "source_url": metadata.get("source_url", "")}
        if kind == "turn":
            draft.update(user=old.get("text", ""), assistant=metadata.get("assistant_reply", ""))
        else:
            draft.update(text=old.get("text", ""), evidence=metadata.get("evidence"),
                         outcome=metadata.get("outcome", "observed"), explicit=kind == "persona_import",
                         enabled=metadata.get("persona_enabled", True))
    draft.update(deepcopy(pending.get(identity, {})))
    for field in ("user", "assistant", "text"):
        if field in event:
            draft[field] = _text(event[field], field, MAX_TEXT if field != "text" or kind != "persona_import" else 4000,
                                 empty=status == "partial")
    if "origin" in event:
        draft["origin"] = _text(event["origin"], "origin", 200)
    if "source_url" in event:
        draft["source_url"] = _url(event["source_url"])
    if "evidence" in event:
        draft["evidence"] = _json_data(event["evidence"])
    if "outcome" in event:
        if event["outcome"] not in ("observed", "success", "failed"):
            raise ValidationError("outcome只能是observed/success/failed")
        draft["outcome"] = event["outcome"]
    if "explicit" in event:
        if type(event["explicit"]) is not bool:
            raise ValidationError("explicit必须是布尔值")
        draft["explicit"] = event["explicit"]
    if "enabled" in event:
        if type(event["enabled"]) is not bool:
            raise ValidationError("enabled必须是布尔值")
        draft["enabled"] = event["enabled"]
    proof_session=_text(event['source_session_id'],'source_session_id',200) if event.get('source_session_id') is not None else external_session
    proof_event=_text(event['source_event_id'],'source_event_id',200) if event.get('source_event_id') is not None else request
    source = {"origin": draft.get("origin", "connected_chat"), "connection_id": connection,
              "session_id": external_session, "turn_id": request}
    if event.get("source_session_id") is not None:source["source_session_id"]=proof_session
    if event.get("source_event_id") is not None:source["source_event_id"]=proof_event
    if draft.get("source_url"):
        source["source_url"] = draft["source_url"]
    if status == "partial":
        if old is not None:
            from .dedup import canonical_id
            primary=canonical_id(brain,old) if kind=="turn" else nid
            return {"status": "complete", "node_ids": [primary],"record_node_ids":[nid],
                    "duplicate_of":primary if primary!=nid else None,
                    "deduplicated":old.get("meta",{}).get("dedup_status")=="confirmed",
                    "duplicate": True, "session_id": session}
        if identity not in pending and len(pending) >= MAX_PENDING:
            raise ValidationError("未完成事件已达32条上限，请完成或取消旧事件")
        duplicate = pending.get(identity) == draft
        if not duplicate:
            pending[identity] = draft
            brain.meta["companion_ingestion"] = ingestion
        return {"status": "partial", "node_ids": [], "duplicate": duplicate,
                "session_id": session, "reason": "草稿不进入完成对话、检索或人格学习"}
    # 完整校验后才写入；外层HTTP也应把事件与落盘作为同一事务。
    if kind == "turn":
        user = _text(draft.get("user"), "user", MAX_TEXT)
        assistant = _text(draft.get("assistant"), "assistant", MAX_TEXT)
        digest = sha256(json.dumps([user, assistant, source], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    elif kind == "tool":
        text = _text(draft.get("text"), "text", MAX_TEXT)
        digest = sha256(json.dumps([text, source, draft.get("outcome", "observed"), draft.get("evidence")],
                                  ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    else:
        text = _text(draft.get("text"), "text", 4000)
        if draft.get("explicit") is not True:
            raise ValidationError("人格原文导入需要明确用户请求explicit=true")
        digest = sha256(json.dumps([text, source, draft.get("enabled", True)], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if old is not None:
        if old.get("meta", {}).get("ingest_hash") != digest:
            raise ValidationError("同一连接/会话/turn_id已完成不同内容，未覆盖原记录")
        from .dedup import canonical_id
        primary=canonical_id(brain,old) if kind=="turn" else nid
        return {"status": "complete", "node_ids": [primary], "record_node_ids":[nid],
                "duplicate_of":primary if primary!=nid else None,"deduplicated":old.get("meta",{}).get("dedup_status")=="confirmed",
                "duplicate": True, "session_id": session,"persona_revision": old["meta"].get("persona_revision")}
    if kind == "turn":
        record_turn(brain, user, assistant, session, request, origin=source["origin"],
                    external_session_id=proof_session,source_event_id=proof_event,connection_id=connection)
        node = brain.nodes[nid]
        node["meta"].update(connection_id=connection, external_session_id=proof_session, external_transport_session_id=external_session,
                            external_turn_id=request, origin=source["origin"], ingest_hash=digest)
        if source.get("source_url"):
            node["meta"]["source_url"] = source["source_url"]
        if "evidence" in draft:
            node["meta"]["evidence"] = draft["evidence"]
        from .dedup import annotate_turn_recording,canonical_id
        dedup=annotate_turn_recording(brain,nid)
        canonical=canonical_id(brain,nid)
        lines = user.strip().splitlines()
        match = _IMPORT.fullmatch(lines[0]) if lines else None
        if match and canonical==nid:
            raw = "\n".join([match.group(1), *lines[1:]]).strip()
            if raw:
                state = import_persona(brain, raw, {**source, "evidence_node_id": nid})
                node["meta"]["persona_revision"] = state["revision"]
                node["meta"]["persona_action"] = "explicit_import"
        elif not match and ("导入人格" in user or "设定如下" in user):
            node["meta"]["persona_review_note"] = "标记不在明确首行命令中，可能属于引用或讨论，未导入人格"
        learned = learn_from_dialogue(brain) if canonical==nid else {"changed":False}
        if learned["changed"]:
            node["meta"]["persona_revision"] = learned["revision"]
            node["meta"]["persona_action"] = "low_risk_style_learning"
        proposals = event.get("proposals", [])
        if not isinstance(proposals, list) or len(proposals) > 5:
            raise ValidationError("proposals最多5条")
        for proposal in (proposals if canonical==nid else []):
            if not isinstance(proposal, dict):
                raise ValidationError("proposal必须是对象")
            propose_persona(brain, proposal.get("text"), proposal.get("evidence_ids"), origin="connected_hook")
    else:
        brain.add(("工具观察 · " if kind == "tool" else "人格导入来源 · ") + text.strip().splitlines()[0][:60],
                  text, kind="episode", id=nid, session_id=session, impact=0, salience=0.55,
                  meta={"source": "tool_observation" if kind == "tool" else "persona_import_source",
                        **source, "origin": source["origin"], "confirmed": False, "important": False,
                        "outcome": draft.get("outcome", "observed"), "evidence": draft.get("evidence"),
                        "persona_enabled": draft.get("enabled", True),
                        "external_session_id": external_session, "external_turn_id": request,
                        "ingest_hash": digest, "speaker": "tool" if kind == "tool" else "user"})
        if kind == "persona_import":
            state = import_persona(brain, text, {**source, "evidence_node_id": nid}, enabled=draft.get("enabled", True))
            brain.nodes[nid]["meta"]["persona_revision"] = state["revision"]
    pending.pop(identity, None)
    brain.meta["companion_ingestion"] = ingestion
    node = brain.nodes[nid]
    from .dedup import canonical_id
    canonical=canonical_id(brain,nid) if kind=="turn" else nid
    return {"status": "complete", "node_ids": [canonical], "record_node_ids":[nid],
            "deduplicated":bool(kind=="turn" and dedup.get("deduplicated")),
            "duplicate_of":canonical if canonical!=nid else None,
            "duplicate": False, "session_id": session,
            "persona_revision": node["meta"].get("persona_revision"),
            "persona_action": node["meta"].get("persona_action"),
            "review_note": node["meta"].get("persona_review_note")}
