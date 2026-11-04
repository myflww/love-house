"""人格原文、低风险风格学习与可回滚版本；没有模型调用。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import re
import unicodedata

from ..errors import ValidationError
from ..utils import now
from .memory import _text, get_profile

MAX_REVISIONS = 20
MAX_PROPOSALS = 20
TRAIT_DIMENSIONS = {"communication": "表达习惯", "temperament": "性格倾向", "interests": "兴趣",
                    "values": "价值倾向", "identity": "自我描述", "interaction": "相处方式"}
_EMPTY = {"name": "", "persona": "", "user_name": ""}


class PersonaConflict(ValidationError):
    code = "persona_revision_conflict"


def _state(brain):
    preferences = brain.meta.get("companion_persona_preferences", {})
    if not isinstance(preferences, dict):raise ValidationError("人格开关资料格式不正确")
    for key in ("enabled", "learning_enabled", "user_disabled"):
        if key in preferences and type(preferences[key]) is not bool:raise ValidationError("人格开关必须为布尔值")
    for key, pattern in (("blocked_trait_ids", r"persona_trait_[a-f0-9]{24}"), ("blocked_trait_evidence", r"[a-f0-9]{64}")):
        values = preferences.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or re.fullmatch(pattern, v) is None for v in values):
            raise ValidationError("人格移除标记格式不正确")
    state = deepcopy(brain.meta.get("companion_persona"))
    if state is None:
        profile = get_profile(brain)
        enabled = preferences.get("enabled", True) is not False and preferences.get("user_disabled") is not True
        learning = preferences.get("learning_enabled", True) is not False
        user_disabled = not enabled
        state = {"schema_version":2, "revision": 0, "enabled": enabled, "learning_enabled": learning,
                 "learned": {}, "proposals": [], "learning_ignored_ids": [], "user_disabled": False,
                 "revisions": [{"revision": 0, "profile": profile, "learned": {},
                                "enabled": enabled, "learning_enabled": learning,
                                "user_disabled": user_disabled,
                                "raw_text": profile["persona"], "source": {"origin": "existing_profile"},
                                "explicit": bool(any(profile.values())), "at": now()}]}
        state["user_disabled"] = user_disabled
        state["blocked_trait_ids"] = [s for s in preferences.get("blocked_trait_ids", [])
                                      if isinstance(s, str) and re.fullmatch(r"persona_trait_[a-f0-9]{24}", s)]
        state["blocked_trait_evidence"] = [s for s in preferences.get("blocked_trait_evidence", [])
                                           if isinstance(s, str) and re.fullmatch(r"[a-f0-9]{64}", s)]
    if not isinstance(state, dict):
        raise ValidationError("人格版本格式不正确，未覆盖原资料")
    if preferences.get("enabled") is False or preferences.get("user_disabled") is True:
        state["enabled"] = False;state["user_disabled"] = True
    if preferences.get("learning_enabled") is False:state["learning_enabled"] = False
    state.setdefault("user_disabled", False)
    state.setdefault("learning_enabled", True)
    state.setdefault("formed_traits", [])
    state.setdefault("blocked_trait_ids", [])
    state.setdefault("blocked_trait_evidence", [])
    state.setdefault("learning_ignored_ids", [])
    if type(state.get("revision")) is not int or state["revision"] < 0:
        raise ValidationError("人格版本必须为非负整数")
    if "schema_version" in state and (type(state["schema_version"]) is not int or state["schema_version"] not in (1,2)):
        raise ValidationError("人格资料版本暂不支持")
    if any(type(state.get(k)) is not bool for k in ("enabled", "learning_enabled", "user_disabled")):
        raise ValidationError("人格开关必须为布尔值")
    if not isinstance(state.get("learned"), dict) or any(not isinstance(state.get(k), list) for k in ("proposals", "revisions", "formed_traits", "blocked_trait_ids", "blocked_trait_evidence", "learning_ignored_ids")):
        raise ValidationError("人格历史与形成资料格式不正确")
    if any(not isinstance(p,dict) or not isinstance(p.get("id"),str) or not isinstance(p.get("text"),str)
           or p.get("status") not in ("pending","accepted","rejected") for p in state["proposals"]):
        raise ValidationError("人格候选格式不正确")
    for revision in state["revisions"]:
        if (not isinstance(revision,dict) or type(revision.get("revision")) is not int
                or not isinstance(revision.get("profile"),dict)
                or type(revision.get("enabled")) is not bool or type(revision.get("learning_enabled")) is not bool
                or any(not isinstance(revision["profile"].get(k,""),str) or len(revision["profile"].get(k,""))>limit
                       for k,limit in (("name",80),("persona",4000),("user_name",80)))):
            raise ValidationError("人格历史版本格式不正确")
    for key, pattern in (("blocked_trait_ids", r"persona_trait_[a-f0-9]{24}"), ("blocked_trait_evidence", r"[a-f0-9]{64}")):
        if any(not isinstance(v, str) or re.fullmatch(pattern, v) is None for v in state[key]):
            raise ValidationError("人格移除标记格式不正确")
        state[key] = sorted(set(state[key]) | set(preferences.get(key, [])))
    # Unknown nested learned entries are not current preferences. In particular
    # do not let imported text/instructions masquerade as the legacy enum.
    state["learned"] = {key:{field:deepcopy(item[field]) for field in ("value", "evidence_ids", "evidence", "origin", "risk") if field in item}
        for key,item in state["learned"].items()
        if isinstance(key,str) and isinstance(item,dict) and isinstance(item.get("value"),str)
        and item["value"] in ("gentle","humorous","formal","casual","concise","detailed")
        and isinstance(item.get("evidence_ids"),list) and all(isinstance(nid,str) for nid in item["evidence_ids"])}
    if state["user_disabled"]:state["enabled"] = False
    # Older empty libraries used disabled as an implicit default. Explicit off
    # choices, including rollback/import, remain off after this migration.
    if state.get("enabled") is False and not state["user_disabled"]:
        explicit_off = any(r.get("explicit") is True and r.get("enabled") is False
                           and (r.get("source", {}).get("origin") if isinstance(r.get("source"), dict) else None) != "existing_profile"
                           for r in state.get("revisions", []) if isinstance(r, dict))
        if state.get("schema_version",1) < 2 and not explicit_off and not any(get_profile(brain).values()):
            state["enabled"] = True
        else:
            state["user_disabled"] = True
    state["schema_version"] = 2
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
                               "formed_traits": deepcopy(state.get("formed_traits", [])),
                               "blocked_trait_ids": deepcopy(state.get("blocked_trait_ids", [])),
                               "blocked_trait_evidence": deepcopy(state.get("blocked_trait_evidence", [])),
                               "source": deepcopy(source), "explicit": explicit, "at": now()})
    state["revisions"] = state["revisions"][-MAX_REVISIONS:]
    brain.meta["companion_profile"] = deepcopy(profile)
    brain.meta["companion_persona"] = deepcopy(state)
    # Keep only switches outside history so forgetting quoted evidence cannot
    # accidentally turn an explicitly disabled feature back on.
    brain.meta["companion_persona_preferences"] = {
        "enabled": state["enabled"], "learning_enabled": state["learning_enabled"],
        "user_disabled": state["user_disabled"],
        "blocked_trait_ids": deepcopy(state.get("blocked_trait_ids", [])),
        "blocked_trait_evidence": deepcopy(state.get("blocked_trait_evidence", []))}
    return persona_state(brain)


def _active_turn_evidence(brain, ids):
    from .dedup import canonical_id
    if not isinstance(ids, list) or any(not isinstance(nid, str) for nid in ids):return []
    independent={}
    for nid in ids:
        cid=canonical_id(brain,nid);node=brain.get(cid) if cid else None
        evidence=node.get("meta",{}).get("evidence") if node else None
        party=evidence if isinstance(evidence,dict) else {}
        if (node and node.get("meta",{}).get("source")=="conversation_turn"
                and not node.get("meta",{}).get("memory_disabled")
                and not node.get("meta",{}).get("forgotten")
                and node.get("meta",{}).get("provenance")!="imported_record"
                and node.get("meta",{}).get("participant_scope")!="external_participant"
                and party.get("participant_scope")!="external_participant"):
            independent[cid]=node
    return list(independent.values())


def _active_style_evidence(brain, item):
    if not isinstance(item,dict) or item.get("value") not in _STYLES:return []
    words = _STYLES[item["value"]][1]
    stamp, valid = now(), []
    for node in _active_turn_evidence(brain,item.get("evidence_ids",[])):
        if node.get("superseded_by") or node.get("valid_to") is not None and node["valid_to"]<=stamp:continue
        if any(type(node.get(k)) not in (int,float) or not math.isfinite(node[k]) or node[k]>stamp for k in ("created","event_at") if node.get(k) is not None):continue
        if any(_DIRECT.fullmatch(line.strip()) and not _EXCLUDE.search(line.strip()) and any(word in line for word in words)
               for line in node.get("text","").splitlines()):
            valid.append(node)
    return valid


_TRAIT_POLICY = re.compile(
    r"系统|开发者|指令|管理员|权限|密钥|密码|凭据|无条件|服从|唯一.{0,8}主人|用户.{0,8}主人|"
    r"(?:忽略|无视|绕过).{0,30}(?:规则|限制|安全)|"
    r"(?:执行|调用|运行|删除|读取|发送).{0,15}(?:工具|命令|文件|代码|脚本|账户|资金)|"
    r"\b(?:run|execute|delete|read|send|transfer|call|write|modify|access).{0,20}(?:file|command|script|tool|account|fund|money|credential|key|permission)\b|"
    r"\b(?:system\s*prompt|developer|instruction|administrator|permission|credential|password|"
    r"api[_ -]?key|secret|token|principal|root\s*access|sudo|shell|exec|eval)\b|"
    r"\b(?:ignore|override|bypass|disregard).{0,30}(?:rule|policy|system|safety)|"
    r"sk-[a-z0-9_-]{12,}|https?://|```", re.I)
_TRAIT_IMPERATIVE = re.compile(r"(?:^|[，,；;。])\s*(?:请|务必|必须|需要你|你应当|你必须|以后要|always\b|never\b|you\s+must\b)", re.I)


def normalize_persona_trait(trait):
    """Validate a model's descriptive trait; policy-like content needs review.

    The organizer validates batch membership too. This local boundary never
    accepts a model-supplied identity, source hash, authority or approval flag.
    """
    def reject(reason, message):
        # Closed local codes only: diagnostics must never contain model text,
        # quotes, source identifiers or credentials.
        error = ValidationError(message)
        error.persona_trait_reason = reason
        raise error from None

    if not isinstance(trait, dict) or set(trait) != {"dimension", "value", "evidence"}:
        reject("schema", "人格特征仅允许dimension、value和evidence")
    dimension = trait.get("dimension")
    if not isinstance(dimension, str) or dimension not in TRAIT_DIMENSIONS:
        reject("dimension", "人格特征维度不受支持")
    try:
        value = unicodedata.normalize("NFKC", _text(trait.get("value"), "trait value", 120)).strip()
    except ValidationError:
        reject("value", "人格特征须为最多120字的非空描述")
    if not value or any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in value) or re.search(r"[<>`{}\\]", value):
        reject("value", "人格特征包含不允许的字符")
    if _TRAIT_POLICY.search(value) or _TRAIT_IMPERATIVE.search(value):
        reject("value_policy", "指令、权限或安全相关内容不能自动成为人格特征，请人工审阅")
    evidence = trait.get("evidence")
    if not isinstance(evidence, list) or not 2 <= len(evidence) <= 6:
        reject("evidence_count", "人格形成需要2~6条独立助手原话证据")
    refs = []
    for ref in evidence:
        if not isinstance(ref, dict) or set(ref) != {"id", "role", "quote"}:
            reject("evidence_schema", "人格依据仅允许id、role和quote")
        if ref.get("role") != "assistant":
            reject("evidence_role", "人格特征只能引用本Agent的助手原话，不能使用用户或工具角色")
        try:
            identifier = _text(ref.get("id"), "evidence id", 200).strip()
        except ValidationError:
            reject("evidence_id", "人格依据须包含有效来源标识")
        try:
            quote = _text(ref.get("quote"), "evidence quote", 500).strip()
        except ValidationError:
            reject("evidence_quote", "人格依据须为最多500字的非空原话")
        refs.append({"id": identifier, "role": "assistant", "quote": quote})
    if len({ref["id"] for ref in refs}) < 2:
        reject("evidence_duplicate", "同一段对话不能重复充当多条人格依据")
    return {"dimension": dimension, "value": value, "evidence": refs}


def _trait_version(node):
    meta = node.get("meta", {})
    material = [node.get("id"), meta.get("source"), node.get("text"), meta.get("assistant_reply"),
                node.get("session_id"), node.get("created"), node.get("event_at"),
                meta.get("speaker"), meta.get("import_messages"),
                (meta.get("evidence") or {}).get("archive_receipt_id") if isinstance(meta.get("evidence"), dict) else None]
    return sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _trait_evidence(brain, refs, *, library_id=None, versions=None):
    from .dedup import canonical_id
    stamp = now()
    tomb = brain.meta.get("memory_tombstones", {})
    blocked_ids = set(tomb.get("node_ids", []))
    blocked_texts = set(tomb.get("text_hashes", []))
    namespace = library_id or brain.meta.get("library_id")
    resolved, hashes = [], {}
    for ref in refs:
        nid = canonical_id(brain, ref["id"])
        node = brain.get(nid) if nid else None
        if not node or nid in blocked_ids or ref["id"] in blocked_ids:
            raise ValidationError("人格依据已经不存在或已被忘记")
        meta = node.get("meta", {})
        receipt = (meta.get("evidence") or {}).get("archive_receipt_id") if isinstance(meta.get("evidence"), dict) else None
        if receipt in tomb.get("raw_ids", []):
            raise ValidationError("人格依据的原始归档已经被忘记")
        if (meta.get("memory_disabled") or meta.get("forgotten") or node.get("superseded_by")
                or node.get("valid_to") is not None and node["valid_to"] <= stamp):
            raise ValidationError("人格依据已经停用或更正")
        if meta.get("library_id") not in (None, namespace):
            raise ValidationError("人格依据不属于当前记忆库")
        for field in ("created", "event_at"):
            value = node.get(field)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value > stamp):
                raise ValidationError("未来或无效时间的资料不能成为当前人格依据")
        source = meta.get("source")
        body = meta.get("assistant_reply") if source == "conversation_turn" else node.get("text") if source == "agent_output" else None
        if source == 'agent_output' and meta.get('speaker') not in (None,'assistant'):
            raise ValidationError("人格依据的显式角色不是助手")
        roles=meta.get('roles')
        if source == 'conversation_turn' and roles is not None and (not isinstance(roles,dict) or roles.get('assistant_reply','assistant')!='assistant'):
            raise ValidationError("人格依据的显式角色与助手原话不一致")
        if source == "history_import" and meta.get("speaker") == "assistant":
            originals = meta.get("import_messages")
            if (isinstance(originals, list) and originals and all(isinstance(m, dict) and m.get("role") == "assistant" for m in originals)
                    and any(m.get("text") == node.get("text") for m in originals)):
                body = node.get("text")
        quote = ref["quote"]
        if not isinstance(body, str) or not body or quote not in body:
            raise ValidationError("人格引用必须逐字来自完整助手输出")
        if any(sha256(value.encode()).hexdigest() in blocked_texts for value in (body, quote)):
            raise ValidationError("已忘记的原话不能重新形成人格")
        start = body.index(quote)
        left = max((body.rfind(c, 0, start) for c in "。！？!?；;\n"), default=-1)
        endings = [body.find(c, start + len(quote)) for c in "。！？!?；;\n"]
        right = start + len(quote) if quote[-1:] in "。！？!?；;\n" else min((p + 1 for p in endings if p >= 0), default=len(body))
        context = body[left + 1:right]
        normalized_context = "".join(c for c in unicodedata.normalize("NFKC", context) if unicodedata.category(c) not in ("Cf", "Cs"))
        if len(context) > 1200 or _TRAIT_POLICY.search(normalized_context):
            raise ValidationError("这段人格引用包含待人工审阅的指令或权限语境")
        version = _trait_version(node)
        if versions is not None and versions.get(nid) != version:
            raise ValidationError("人格依据已编辑，请重新整理")
        resolved.append({"id": nid, "role": "assistant", "quote": quote})
        hashes[nid] = version
    if len(hashes) < 2:
        raise ValidationError("重复采集的同一轮不能算作两条独立人格依据")
    unique = {(r["id"], r["quote"]): r for r in resolved}
    return [unique[key] for key in sorted(unique)], dict(sorted(hashes.items()))


def _trait_id(dimension, value):
    return "persona_trait_" + sha256(json.dumps([dimension, value.casefold()], ensure_ascii=False).encode()).hexdigest()[:24]


def _trait_evidence_key(dimension, refs):
    return sha256(json.dumps([dimension, sorted({r["id"] for r in refs})], ensure_ascii=False).encode()).hexdigest()


def _formed_trait_active(brain, item, state, library_id=None):
    if (not isinstance(item, dict) or item.get("status") != "active" or item.get("id") in state.get("blocked_trait_ids", [])
            or not isinstance(item.get("dimension"), str) or item["dimension"] not in TRAIT_DIMENSIONS or not isinstance(item.get("source_versions"), dict)):
        return False
    try:
        normalized = normalize_persona_trait({k:item.get(k) for k in ("dimension", "value", "evidence")})
        if item["id"] != _trait_id(normalized["dimension"], normalized["value"]): return False
        if library_id and item.get("library_id") not in (None,library_id):return False
        if _trait_id("*", normalized["value"]) in state.get("blocked_trait_ids", []): return False
        if brain.meta.get("library_id") not in (None, item.get("library_id")): return False
        refs, _ = _trait_evidence(brain, normalized["evidence"], library_id=library_id or item.get("library_id"), versions=item["source_versions"])
        blocked = state.get("blocked_trait_evidence", [])
        return _trait_evidence_key(item["dimension"], refs) not in blocked and _trait_evidence_key("*", refs) not in blocked
    except (ValidationError, TypeError, ValueError):
        return False


def apply_learned_traits(brain, traits, *, source=None, expected_revision=None, library_id=None):
    """Apply descriptive, evidence-backed traits without changing explicit persona.

    Raw statements, roleplay identity and inferred style remain historical
    observations about this Agent, never verified world facts or permissions.
    """
    if not isinstance(traits, list) or len(traits) > 32:
        raise ValidationError("每次人格整理最多接收32项特征")
    state = _state(brain)
    if not state["enabled"] or not state["learning_enabled"]:
        return {"changed": False, "reason": "persona_disabled" if not state["enabled"] else "learning_disabled", "revision":state["revision"], "applied_ids":[]}
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision != state["revision"]):
        return {"changed":False, "reason":"persona_revision_changed", "revision":state["revision"], "applied_ids":[]}
    if library_id is not None:
        library_id = _text(library_id, "library_id", 200).strip()
        if brain.meta.get("library_id") not in (None, library_id):
            raise ValidationError("人格整理归属与当前记忆库不一致")
    source = _source(source or {"origin":"organizer_persona"})
    prepared = []
    for trait in traits:
        # Organizer evidence may already carry safe batch annotations. Re-read
        # role text locally; annotations never supply source or authority.
        clean = deepcopy(trait)
        if isinstance(clean, dict) and isinstance(clean.get("evidence"), list):
            clean["evidence"] = [{k:r.get(k) for k in ("id", "role", "quote")} if isinstance(r, dict) else r for r in clean["evidence"]]
        normalized = normalize_persona_trait(clean)
        refs, versions = _trait_evidence(brain, normalized["evidence"], library_id=library_id)
        identifier = _trait_id(normalized["dimension"], normalized["value"])
        if (identifier in state["blocked_trait_ids"] or _trait_id("*", normalized["value"]) in state["blocked_trait_ids"]
                or _trait_evidence_key(normalized["dimension"], refs) in state["blocked_trait_evidence"]
                or _trait_evidence_key("*", refs) in state["blocked_trait_evidence"]):
            continue
        prepared.append({**normalized, "id":identifier, "evidence":refs, "evidence_ids":list(versions),
                         "source_versions":versions, "library_id":library_id or brain.meta.get("library_id"),
                         "status":"active", "origin":source["origin"], "source":source,
                         "created":now(), "updated":now(), "confirmed":False,
                         "interpretation":"inferred_agent_characteristic"})
    applied = []
    for item in prepared:
        old = next((t for t in state["formed_traits"] if isinstance(t, dict) and t.get("id") == item["id"]), None)
        if old and old.get("evidence") == item["evidence"] and old.get("source_versions") == item["source_versions"] and old.get("status") == "active":
            continue
        if old:
            item["created"] = old.get("created", item["created"])
            state["formed_traits"].remove(old)
        state["formed_traits"].append(item); applied.append(item["id"])
    if not applied:
        return {"changed":False, "reason":"unchanged_or_suppressed", "revision":state["revision"], "applied_ids":[]}
    result = _commit(brain, state, get_profile(brain), raw_text="", source=source, explicit=False)
    return {"changed":True, "revision":result["revision"], "applied_ids":applied}


def remove_learned_trait(brain, trait_id, expected_revision=None):
    state = _state(brain); _expected(state, expected_revision)
    item = next((t for t in state["formed_traits"] if isinstance(t, dict) and t.get("id") == trait_id), None)
    if item is None:raise ValidationError("已形成人格特征不存在")
    if item.get("status") == "disabled":return persona_state(brain)
    item["status"] = "disabled"
    state["blocked_trait_ids"] = sorted(set(state["blocked_trait_ids"]) | {trait_id, _trait_id("*", item["value"])})
    state["blocked_trait_evidence"] = sorted(set(state["blocked_trait_evidence"]) | {_trait_evidence_key(item["dimension"], item["evidence"]), _trait_evidence_key("*", item["evidence"])})
    return _commit(brain, state, get_profile(brain), raw_text="", source={"origin":"user_removed_formed_trait", "trait_id":trait_id}, explicit=True)


def rebind_formed_persona_after_import(brain, library_id):
    """Recheck existing portable observations after a trusted import remap.

    The caller supplies the new library identity. Import text is still evidence,
    not instructions; no new trait, explicit profile or enabled choice is made.
    Older undo versions retain their old proof and cannot silently revive it.
    """
    library_id = _text(library_id, "library_id", 200).strip()
    if brain.meta.get("library_id") not in (None, library_id):
        raise ValidationError("人格导入归属与目标库不一致")
    state = _state(brain)
    changed, active, unavailable = False, 0, 0
    for item in state["formed_traits"]:
        if not isinstance(item, dict) or item.get("status") != "active":continue
        try:
            old_versions=item.get("source_versions")
            if not isinstance(old_versions,dict) or not old_versions or any(not isinstance(k,str) or not isinstance(v,str) or re.fullmatch(r"[a-f0-9]{64}",v) is None for k,v in old_versions.items()):
                raise ValidationError("人格引用版本资料不完整")
            normalized = normalize_persona_trait({k:item.get(k) for k in ("dimension", "value", "evidence")})
            if item.get("id") != _trait_id(normalized["dimension"], normalized["value"]):
                raise ValidationError("人格特征编号与内容不一致")
            refs, versions = _trait_evidence(brain, normalized["evidence"], library_id=library_id)
            if (item["id"] in state["blocked_trait_ids"] or _trait_id("*", normalized["value"]) in state["blocked_trait_ids"]
                    or _trait_evidence_key(item["dimension"], refs) in state["blocked_trait_evidence"]
                    or _trait_evidence_key("*", refs) in state["blocked_trait_evidence"]):
                raise ValidationError("这是用户已移除的人格特征")
            item.update(evidence=refs, evidence_ids=list(versions), source_versions=versions, library_id=library_id,
                        confirmed=False, origin="imported_persona_revalidated", source={"origin":"imported_persona_revalidated"},
                        interpretation="inferred_agent_characteristic", updated=now())
            active += 1
        except (ValidationError, TypeError, ValueError):
            item["status"] = "unavailable"
            unavailable += 1
        changed = True
    if changed:
        _commit(brain, state, get_profile(brain), raw_text="", source={"origin":"imported_persona_revalidated"}, explicit=False)
    return {"revalidated":active, "unavailable":unavailable, "changed":changed}


def persona_state(brain, *, library_id=None):
    state = _state(brain)
    profile = get_profile(brain)
    descriptions = {"gentle": "语气温柔", "humorous": "适当幽默", "formal": "表达正式严谨",
                    "casual": "表达轻松自然", "concise": "回复简短", "detailed": "回复详细"}
    active_learned = {dimension:item for dimension,item in state["learned"].items()
                     if len(_active_style_evidence(brain,item)) >= 2}
    learned = [descriptions[item["value"]] for item in active_learned.values()
               if isinstance(item, dict) and isinstance(item.get("value"), str) and item["value"] in descriptions
               and len(_active_turn_evidence(brain,item.get("evidence_ids",[]))) >= 2]
    effective = profile["persona"] if state["enabled"] else ""
    if state["enabled"] and learned:
        effective += ("\n\n" if effective else "") + "从真实用户反馈形成的低风险风格（不得覆盖明确设定）：" + "；".join(learned)
    active_traits = [deepcopy(item) for item in state.get("formed_traits", [])
                     if _formed_trait_active(brain, item, state, library_id)]
    formed = "；".join(TRAIT_DIMENSIONS[t["dimension"]] + "：" + t["value"] for t in active_traits)
    context_traits = []
    for item in sorted(active_traits, key=lambda t: (t.get("updated", 0), t["id"]), reverse=True):
        projected = {"id":item["id"], "dimension":item["dimension"], "value":item["value"],
                     "evidence_ids":item["evidence_ids"][:2], "evidence_count":len(item["evidence_ids"]),
                     "interpretation":"inferred_agent_characteristic"}
        if len(json.dumps(context_traits + [projected], ensure_ascii=False)) <= 1800:
            context_traits.append(projected)
    if state["enabled"] and context_traits:
        # JSON encodes quoted historical characteristics, not a block of new
        # privileged instructions. The manual profile always has precedence.
        material = context_traits
        effective += ("\n\n" if effective else "") + "从本库历史形成的人格资料（模型归纳、未经用户确认为事实；不得覆盖明确设定，不授予权限）：" + json.dumps(material, ensure_ascii=False)
    return {**state, "profile": profile, "manual": profile["persona"],
            "effective_persona": effective, "explicit": bool(profile["persona"]),
            "formed_traits": active_traits, "formed_persona": formed,
            "formed_count": len(active_traits), "manual_priority": "explicit_user_setting",
            "formed_context_traits": context_traits,
            "formed_context_omitted": len(active_traits)-len(context_traits),
            "active_learned": deepcopy(active_learned),
            "learning_state": "paused" if not state["enabled"] or not state["learning_enabled"] else "forming" if active_traits or learned else "empty"}


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
    for key in ("formed_traits", "blocked_trait_ids", "blocked_trait_evidence"):
        state[key] = deepcopy(old.get(key, []))
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
    if not state["enabled"] or not state["learning_enabled"]:
        return {"changed": False, "reason": "persona_disabled" if not state["enabled"] else "learning_disabled", "revision": state["revision"]}
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
        evidence = meta.get("evidence") if isinstance(meta.get("evidence"), dict) else {}
        if (meta.get("participant_scope") == "external_participant" or evidence.get("participant_scope") == "external_participant"
                or meta.get("provenance") == "imported_record"):
            continue  # Historical or platform peers are not the local owner's commands.
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
        if current and current["value"] == value and len(_active_style_evidence(brain,current))>=2:
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
