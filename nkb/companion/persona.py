"""人格原文、低风险风格学习与可回滚版本；没有模型调用。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re

from ..errors import ValidationError
from ..utils import now
from .memory import _text, get_profile

MAX_REVISIONS = 20
MAX_PROPOSALS = 20
_EMPTY = {"name": "", "persona": "", "user_name": ""}


class PersonaConflict(ValidationError):
    code = "persona_revision_conflict"


def _state(brain):
    state = deepcopy(brain.meta.get("companion_persona"))
    if state is None:
        profile = get_profile(brain)
        state = {"revision": 0, "enabled": bool(any(profile.values())), "learning_enabled": True,
                 "learned": {}, "proposals": [], "learning_ignored_ids": [], "user_disabled": False,
                 "revisions": [{"revision": 0, "profile": profile, "learned": {},
                                "enabled": bool(any(profile.values())), "learning_enabled": True,
                                "user_disabled": False,
                                "raw_text": profile["persona"], "source": {"origin": "existing_profile"},
                                "explicit": bool(any(profile.values())), "at": now()}]}
    if not isinstance(state, dict):
        raise ValidationError("人格版本格式不正确，未覆盖原资料")
    state.setdefault("user_disabled", False)
    return state


def _source(value):
    value = {"origin": value} if isinstance(value, str) else deepcopy(value)
    if not isinstance(value, dict) or not isinstance(value.get("origin"), str) or not value["origin"].strip():
        raise ValidationError("人格来源必须包含非空origin")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        raise ValidationError("人格来源必须是可保存的JSON资料") from None
    if len(encoded) > 4000:
        raise ValidationError("人格来源资料过长")
    return value


def _expected(state, revision):
    if revision is not None and (type(revision) is not int or revision != state["revision"]):
        raise PersonaConflict("人格已产生新版本，请刷新后重新确认")


def _commit(brain, state, profile, *, raw_text, source, explicit):
    state["revision"] += 1
    state["revisions"].append({"revision": state["revision"], "profile": deepcopy(profile),
                               "learned": deepcopy(state["learned"]), "enabled": state["enabled"],
                               "learning_enabled": state["learning_enabled"], "raw_text": raw_text,
                               "user_disabled": state["user_disabled"],
                               "source": deepcopy(source), "explicit": explicit, "at": now()})
    state["revisions"] = state["revisions"][-MAX_REVISIONS:]
    brain.meta["companion_profile"] = deepcopy(profile)
    brain.meta["companion_persona"] = deepcopy(state)
    return persona_state(brain)


def _active_turn_evidence(brain, ids):
    from .dedup import canonical_id
    independent={}
    for nid in ids:
        cid=canonical_id(brain,nid);node=brain.get(cid) if cid else None
        if (node and node.get("meta",{}).get("source")=="conversation_turn"
                and not node.get("meta",{}).get("memory_disabled")
                and not node.get("meta",{}).get("forgotten")):
            independent[cid]=node
    return list(independent.values())


def persona_state(brain):
    state = _state(brain)
    profile = get_profile(brain)
    descriptions = {"gentle": "语气温柔", "humorous": "适当幽默", "formal": "表达正式严谨",
                    "casual": "表达轻松自然", "concise": "回复简短", "detailed": "回复详细"}
    learned = [descriptions[item["value"]] for item in state["learned"].values()
               if len(_active_turn_evidence(brain,item.get("evidence_ids",[]))) >= 2]
    effective = profile["persona"] if state["enabled"] else ""
    if state["enabled"] and learned:
        effective += ("\n\n" if effective else "") + "从真实用户反馈形成的低风险风格（不得覆盖明确设定）：" + "；".join(learned)
    return {**state, "profile": profile, "manual": profile["persona"],
            "effective_persona": effective, "explicit": bool(profile["persona"])}


get_persona = persona_state


def save_explicit_profile(brain, profile):
    state = _state(brain)
    state["enabled"] = True
    state["user_disabled"] = False
    return _commit(brain, state, profile, raw_text=profile["persona"],
                   source={"origin": "manual_profile"}, explicit=True)


def import_persona(brain, text, source, enabled=True, expected_revision=None, **kwargs):
    text = _text(text, "persona", 4000)
    source = _source(source)
    if type(enabled) is not bool or ("explicit" in kwargs and kwargs["explicit"] is not True):
        raise ValidationError("人格导入需要明确用户请求与布尔启用状态")
    state = _state(brain)
    fingerprint = sha256(json.dumps([text, source, enabled], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    profile = get_profile(brain)
    # 重放防护属于ingest事件ID；明确导入的幂等只能与当前有效设定比较。
    # 开关/学习版本不重写manual来源，所以向后寻找当前原文最近的明确写入。
    current_manual_source = next((revision.get("source") for revision in reversed(state["revisions"])
                                  if revision.get("explicit")
                                  and revision.get("profile", {}).get("persona") == profile["persona"]
                                  and revision.get("raw_text") == profile["persona"]), None)
    if profile["persona"] == text and state["enabled"] == enabled and current_manual_source == source:
        return persona_state(brain)
    _expected(state, expected_revision)
    profile["persona"] = text
    state["enabled"] = enabled
    state["user_disabled"] = not enabled
    _commit(brain, state, profile, raw_text=text, source=source, explicit=True)
    brain.meta["companion_persona"]["revisions"][-1]["import_hash"] = fingerprint
    return persona_state(brain)


def set_persona_enabled(brain, enabled):
    if type(enabled) is not bool:
        raise ValidationError("enabled必须是布尔值")
    state = _state(brain)
    if state["enabled"] == enabled and state.get("user_disabled") == (not enabled):
        return persona_state(brain)
    state["enabled"] = enabled
    state["user_disabled"] = not enabled
    return _commit(brain, state, get_profile(brain), raw_text="", source={"origin": "persona_toggle"}, explicit=True)


def set_persona_learning(brain, enabled):
    if type(enabled) is not bool:
        raise ValidationError("learning_enabled必须是布尔值")
    state = _state(brain)
    if state["learning_enabled"] == enabled:
        return persona_state(brain)
    state["learning_enabled"] = enabled
    return _commit(brain, state, get_profile(brain), raw_text="", source={"origin": "learning_toggle"}, explicit=True)


def _evidence(brain, ids):
    if (not isinstance(ids, list) or len(ids) > 6 or any(not isinstance(i, str) or len(i) > 200 for i in ids)
            or not 2 <= len(set(ids)) <= 6):
        raise ValidationError("候选需要2~6条不同的真实完成对话证据")
    from .dedup import canonical_id
    ids=list(dict.fromkeys(canonical_id(brain,nid) for nid in ids))
    if len(ids)<2 or any(i is None for i in ids):
        raise ValidationError("候选需要至少2轮独立完成对话，重复来源不能算多条证据")
    quotes = []
    for nid in ids:
        node = brain.get(nid)
        if (node is None or node.get("meta", {}).get("memory_disabled") or node.get("meta", {}).get("source") != "conversation_turn"
                or not isinstance(node["meta"].get("assistant_reply"), str)):
            raise ValidationError("证据必须来自本库已经完成的真实对话")
        quotes.append({"id": nid, "user_excerpt": node["text"][:300],
                       "assistant_excerpt": node["meta"]["assistant_reply"][:150]})
    return quotes


def propose_persona(brain, text, evidence_ids, origin="hook"):
    text = _text(text, "proposal", 2000)
    quotes = _evidence(brain, evidence_ids)
    state = _state(brain)
    identifier = "persona_" + sha256(json.dumps([text, origin, state["revision"]], ensure_ascii=False).encode()).hexdigest()[:24]
    existing = next((p for p in state["proposals"] if p["id"] == identifier), None)
    if existing:
        return deepcopy(existing)
    if len(state["proposals"]) >= MAX_PROPOSALS:
        closed = next((p for p in state["proposals"] if p["status"] != "pending"), None)
        if closed is None:
            raise ValidationError("人格候选已满，请先审阅现有候选")
        state["proposals"].remove(closed)
    proposal = {"id": identifier, "text": text, "evidence_ids": [q["id"] for q in quotes],
                "evidence": quotes, "origin": _text(origin, "origin", 200), "status": "pending",
                "base_revision": state["revision"], "at": now(),
                "reason": "有多轮原文证据，但属于待审阅提议，未覆盖明确人格"}
    state["proposals"].append(proposal)
    brain.meta["companion_persona"] = state
    return deepcopy(proposal)


def accept_persona(brain, proposal_id, explicit=False, expected_revision=None):
    if explicit is not True:
        raise ValidationError("推测候选不能自动覆盖人格，需要明确用户批准")
    state = _state(brain)
    _expected(state, expected_revision)
    proposal = next((p for p in state["proposals"] if p["id"] == proposal_id), None)
    if proposal is None or proposal["status"] != "pending":
        raise ValidationError("待审阅人格候选不存在")
    if proposal["base_revision"] != state["revision"]:
        raise PersonaConflict("该候选基于旧人格版本，请重新生成后再确认")
    proposal["status"] = "accepted"
    profile = get_profile(brain)
    profile["persona"] = proposal["text"]
    state["enabled"] = True
    state["user_disabled"] = False
    return _commit(brain, state, profile, raw_text=proposal["text"],
                   source={"origin": "user_approved_proposal", "proposal_id": proposal_id,
                           "evidence_ids": proposal["evidence_ids"]}, explicit=True)


def reject_persona(brain, proposal_id, expected_revision=None):
    state = _state(brain)
    _expected(state, expected_revision)
    proposal = next((p for p in state["proposals"] if p["id"] == proposal_id), None)
    if proposal is None:
        raise ValidationError("人格候选不存在")
    if proposal["status"] == "accepted":
        raise ValidationError("已生效的候选不能改为拒绝，请使用人格回滚")
    proposal["status"] = "rejected"
    brain.meta["companion_persona"] = state
    return persona_state(brain)


def review_candidate(brain, proposal_id, action, expected_revision=None):
    if action == "accept":
        return accept_persona(brain, proposal_id, explicit=True, expected_revision=expected_revision)
    if action == "reject":
        return reject_persona(brain, proposal_id, expected_revision=expected_revision)
    raise ValidationError("action只能是accept或reject")


def rollback_persona(brain, revision, expected_revision=None):
    state = _state(brain)
    _expected(state, expected_revision)
    old = next((r for r in state["revisions"] if r["revision"] == revision), None)
    if old is None:
        raise ValidationError("该人格版本不在保留的最近20版中")
    for key in ("learned", "enabled", "learning_enabled"):
        state[key] = deepcopy(old[key])
    state["user_disabled"] = old.get("user_disabled", not old["enabled"])
    state["learning_ignored_ids"] = [n["id"] for n in brain.nodes.values()
                                      if n.get("meta", {}).get("source") == "conversation_turn"][-100:]
    return _commit(brain, state, old["profile"], raw_text=old["raw_text"],
                   source={"origin": "rollback", "target_revision": revision}, explicit=True)


_DIRECT = re.compile(r"^(?:我希望你|以后请你|以后请|请你以后|回答请|说话请)(.{1,250})[。！!]?$")
_EXCLUDE = re.compile(r"假设|假如|如果|引用|比如|例如|讨论|不要|不必|不需要|不希望|别|帮我写|文案|小说|故事|扮演|以下文本")
_STYLES = {"gentle": ("tone", ("温柔", "温和", "柔和")),
           "humorous": ("tone", ("幽默", "风趣")), "formal": ("tone", ("正式", "严谨")),
           "casual": ("tone", ("轻松", "自然一点", "随意")),
           "concise": ("length", ("简短", "简洁", "短一点")),
           "detailed": ("length", ("详细", "展开一点", "具体一点"))}


def learn_from_dialogue(brain):
    """只学习用户直接、重复提出的白名单语气维度；不学权限、事实或AI自述。"""
    state = _state(brain)
    if not state["learning_enabled"]:
        return {"changed": False, "reason": "learning_disabled", "revision": state["revision"]}
    ignored = set(state.get("learning_ignored_ids", []))
    from .dedup import is_duplicate
    # Export builds a complete visualization, including copied text/edges and
    # state for unrelated nodes.  Learning needs only the last 100 eligible raw
    # turns in insertion order.  Check live lifecycle state before using them,
    # preserving the same disabled/future/superseded/recovery rules as export.
    stamp, turns = now(), []
    for node in reversed(brain.nodes.values()):
        meta = node.get("meta", {})
        if (meta.get("source") != "conversation_turn" or node["id"] in ignored
                or not isinstance(meta.get("assistant_reply"), str)):
            continue
        if not brain._node_state(node, stamp)["recoverable"] or is_duplicate(node, brain):
            continue
        turns.append(node)
        if len(turns) == 100:
            break
    turns.reverse()
    matches = {}
    for node in turns:
        for line in node["text"].splitlines():
            line = line.strip()
            if not _DIRECT.fullmatch(line) or _EXCLUDE.search(line):
                continue
            values = [(value, dimension) for value, (dimension, words) in _STYLES.items()
                      if any(word in line for word in words)]
            for value, dimension in values:
                # 同一行给出相反风格时不猜测优先级。
                if sum(dimension == d for _, d in values) == 1:
                    matches.setdefault((dimension, value), []).append(node)
    order = {n["id"]: i for i, n in enumerate(turns)}
    winners = {}
    for (dimension, value), evidence in matches.items():
        evidence = list({n["id"]: n for n in evidence}.values())[-6:]
        if len(evidence) < 2:
            continue
        rank = order[evidence[-1]["id"]]
        if dimension not in winners or rank > winners[dimension][0]:
            winners[dimension] = (rank, value, evidence)
    changed, updates = False, []
    for dimension, (_, value, evidence) in winners.items():
        current = state["learned"].get(dimension)
        if current and current["value"] == value and len(_active_turn_evidence(brain,current.get("evidence_ids",[])))>=2:
            continue
        update = {"value": value, "evidence_ids": [n["id"] for n in evidence],
                  "evidence": [{"id": n["id"], "user_excerpt": n["text"][:300]} for n in evidence],
                  "origin": "repeated_direct_user_feedback", "risk": "low"}
        state["learned"][dimension] = update
        updates.append(update)
        changed = True
    if changed:
        if not state.get("user_disabled"):
            state["enabled"] = True
        result = _commit(brain, state, get_profile(brain), raw_text="", explicit=False,
                         source={"origin": "dialogue_style_learning", "updates": updates})
        return {"changed": True, "revision": result["revision"], "learned": result["learned"]}
    return {"changed": False, "reason": "insufficient_or_unchanged_evidence", "revision": state["revision"]}
