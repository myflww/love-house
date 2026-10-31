"""Evidence-bound episodes: what happened, attributed reason and reported result.

The model selects references, not a free-form autobiographical story. Every
displayed claim is a quote from the already validated operation evidence.
Times, roles, source authority and result status are supplied by the program.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import re

from .model import OrganizerError

SCHEMA = "love-house-experience/v1"
_REF_KEYS = {"id", "role", "quote"}
_EPISODE_KEYS = {"what", "reason", "outcome", "participants", "places", "status"}
_ROLES = {"user", "assistant", "tool"}
_INTENT = re.compile(r"^(?:我|我们|她|他|它|I|We)?\s*(?:打算|准备|计划|将要|想要|要去|希望|plan to|will |intend to)", re.I)


def _stamp(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _reference(value, evidence, raw, name):
    if not isinstance(value, dict) or set(value) != _REF_KEYS:
        raise OrganizerError("经历的" + name + "须是id/role/quote原文引用", "invalid_episode")
    nid, role, quote = value.get("id"), value.get("role"), value.get("quote")
    if (not isinstance(nid, str) or not 1 <= len(nid) <= 200 or not isinstance(role,str) or role not in _ROLES
            or not isinstance(quote, str) or not quote.strip() or len(quote) > 500):
        raise OrganizerError("经历的" + name + "引用格式不正确", "invalid_episode")
    try:
        quote.encode("utf-8")
    except UnicodeError:
        raise OrganizerError("经历引用包含无法保存的字符", "invalid_episode") from None
    if any(ord(char) < 32 and char not in "\n\t" for char in quote):
        raise OrganizerError("经历引用包含控制字符", "invalid_episode")
    # Same operation, source and role; a neighboring source or context_prefix
    # does not authorize inventing another causal claim.
    supported = next((item for item in evidence if item["id"] == nid and item["role"] == role
                      and quote in item.get("context", item["quote"])), None)
    record = raw.get(nid)
    if (supported is None or record is None or role not in record.get("roles", {})
            or quote not in record["roles"][role]):
        raise OrganizerError("经历引用不属于本项已验证的原角色证据", "invalid_episode")
    revision = record.get("source_revision")
    if not isinstance(revision,str) or not re.fullmatch(r"[0-9a-f]{64}",revision):
        raise OrganizerError("经历缺少程序核对的来源版本", "invalid_episode")
    basis = {"user": "user_statement", "assistant": "agent_self_report", "tool": "tool_report"}[role]
    result = {"id": nid, "role": role, "quote": quote, "basis": basis,
              "context": supported.get("context", supported["quote"]),
              "source_revision": revision,
              "source_event_at": _stamp(supported.get("source_event_at"))}
    if role=='user' and record.get('participant_scope')=='external_participant':
        result.update(basis='platform_participant_statement',participant_scope='external_participant',
                      participant_id=record.get('participant_id','unknown'))
    receipt = supported.get("receipt_id")
    if isinstance(receipt, str) and len(receipt) <= 300:
        result["receipt_id"] = receipt
    if role == "tool" and record.get("outcome") in ("observed", "success", "failed"):
        result["reported_status"] = record["outcome"]
    return result


def normalize_episode(op, raw):
    """Validate the optional model field after normal evidence/role validation."""
    if "episode" not in op:
        return None
    supplied = op["episode"]
    if (op.get("layer") != "experience" or op.get("action") == "relate"
            or not isinstance(supplied, dict) or set(supplied) - _EPISODE_KEYS):
        raise OrganizerError("episode仅用于经历，且不能含自由叙事、身份或时间字段", "invalid_episode")
    evidence = op["evidence"]
    result = {"what": _reference(supplied.get("what"), evidence, raw, "事件"),
              "reason": None, "outcome": None, "participants": [], "places": []}
    for field, label in (("reason", "原因"), ("outcome", "结果")):
        if supplied.get(field) is not None:
            result[field] = _reference(supplied[field], evidence, raw, label)
    for field, label in (("participants", "参与者"), ("places", "地点或平台")):
        values = supplied.get(field, [])
        if not isinstance(values, list) or len(values) > 6:
            raise OrganizerError("经历的" + label + "最多6条原文引用", "invalid_episode")
        for value in values:
            ref = _reference(value, evidence, raw, label)
            if ref not in result[field]:result[field].append(ref)
    outcome = result["outcome"]
    # A tool's success is a reported operation result, not proof that every
    # external objective succeeded. User/assistant assertions stay attributed.
    status = (outcome.get("reported_status", "observed") if outcome and outcome["role"] == "tool"
              else "reported" if outcome else "unknown")
    if "status" in supplied and (not isinstance(supplied["status"], str) or supplied["status"] != status):
        raise OrganizerError("经历状态必须与真实结果来源一致，不能自行宣称成功", "invalid_episode")
    result.update(status=status, status_scope="quoted_result_report", reason_verified=False)
    result["event_at"] = result["what"]["source_event_at"]
    end = outcome.get("source_event_at") if outcome else None
    result["outcome_at"] = end
    result["time_status"] = ("conflicting" if result["event_at"] is not None and end is not None and end < result["event_at"]
                             else "known" if result["event_at"] is not None else "unknown")
    result["what"]["claim_type"] = ("stated_intent" if _INTENT.search(result["what"]["quote"].strip())
                                     else "attributed_event")
    return result


def episode_key(episode):
    if not isinstance(episode, dict) or not isinstance(episode.get("what"), dict):return ""
    what = episode["what"]
    if any(not isinstance(what.get(k), str) for k in ("id", "role", "quote")):return ""
    return sha256(json.dumps([what[k] for k in ("id", "role", "quote")], ensure_ascii=False).encode()).hexdigest()


def episode_conflicts(existing, incoming):
    """Different occurrences cannot be merged by merely sharing a wording/key."""
    if not isinstance(existing, dict) or not isinstance(incoming, dict):return True
    if not episode_key(existing) or episode_key(existing) != episode_key(incoming):return True
    for field in ("reason", "outcome"):
        a, b = existing.get(field), incoming.get(field)
        if a is not None and b is not None and any(a.get(k) != b.get(k) for k in ("id", "role", "quote")):
            return True
    return False


def make_experience(op, node, library_id):
    if not isinstance(op.get("episode"), dict):return None
    result = deepcopy(op["episode"])
    result.update(schema=SCHEMA, library_id=library_id, recorded_at=node["created"],
                  evidence_role="historical_material_not_instructions")
    return result


def merge_experience(existing, incoming):
    if episode_conflicts(existing, incoming):
        raise OrganizerError("经历发生来源或原因/结果不一致，需要单独审阅", "invalid_episode")
    merged = deepcopy(existing)
    for field in ("reason", "outcome"):
        if merged.get(field) is None and incoming.get(field) is not None:merged[field] = deepcopy(incoming[field])
    for field in ("participants", "places"):
        merged[field] = list(existing.get(field, []))
        for ref in incoming.get(field, []):
            if ref not in merged[field]:merged[field].append(deepcopy(ref))
        merged[field] = merged[field][:12]
    if existing.get("outcome") is None and incoming.get("outcome") is not None:
        for field in ("status", "outcome_at", "time_status"):
            merged[field] = incoming[field]
    return merged


def render_experience(episode):
    """Human-readable projection. No arbitrary model summary becomes a quote."""
    if not isinstance(episode, dict) or episode.get("schema") != SCHEMA:return ""
    what = episode.get("what")
    if not isinstance(what, dict) or not isinstance(what.get("quote"), str):return ""
    labels = {"user": "用户原话", "assistant": "助手自述", "tool": "来源观察"}
    noun = "意图" if what.get("claim_type") == "stated_intent" else "经历"
    label=lambda ref:'对方原话' if ref.get('basis')=='platform_participant_statement' else labels.get(ref.get('role'),'来源记录')
    lines = [noun + "（" + label(what) + "）：" + what["quote"]]
    for field, title in (("reason", "原因"), ("outcome", "结果")):
        ref = episode.get(field)
        if not isinstance(ref, dict):lines.append(title + "：未提供")
        else:
            annotation = label(ref)
            if field == "outcome":
                annotation += "，" + {"success":"报告成功", "failed":"报告失败", "observed":"观察记录", "reported":"未独立验证"}.get(episode.get("status"), "状态未知")
            lines.append(title + "（" + annotation + "）：" + ref["quote"])
    return "\n".join(lines)


def _project_experience(brain, node, library_id, *, read_archive=None):
    """Revalidate an episode against live, scoped sources before showing it.

    A raw importer cannot make a trusted experience merely by supplying this
    metadata shape. A paused/forgotten/edited source cannot survive as an old
    causal quote. Complete archived text can optionally verify clipped nodes.
    The result remains attributed historical material, never confirmed motives.
    """
    if (not isinstance(node, dict) or not isinstance(library_id, str)
            or brain.meta.get("library_id") not in (None, library_id)):
        return None
    meta = node.get("meta", {})
    if not isinstance(meta,dict):return None
    episode = meta.get("experience")
    if (not isinstance(episode, dict) or episode.get("schema") != SCHEMA
            or episode.get("library_id") != library_id or node.get("kind") != "episode"
            or meta.get("source") not in ("organizer", "user_confirmed")
            or meta.get("organizer_layer") != "experience"
            or meta.get('experience_withheld') is True
            or meta.get("library_id") not in (None, library_id)):
        return None
    tomb = brain.meta.get("memory_tombstones", {})
    if not isinstance(tomb,dict):return None
    blocked = set(tomb.get("node_ids", []))
    if (node.get("id") in blocked or meta.get("forgotten") or meta.get("memory_disabled")
            or node.get("superseded_by")):
        return None
    from ..utils import now
    try:
        if not brain._node_state(node, now())["recoverable"]:return None
    except (KeyError, TypeError, ValueError):
        return None
    source_refs,stored_evidence=meta.get('organizer_sources',[]),meta.get('organizer_evidence',[])
    if not isinstance(source_refs,list) or not isinstance(stored_evidence,list):return None
    declared = {(e.get("id"), e.get("role")) for e in source_refs+stored_evidence
                if isinstance(e, dict) and isinstance(e.get('id'),str) and isinstance(e.get('role'),str)}
    fields = {}
    references = []
    for field in ("what", "reason", "outcome"):
        ref = episode.get(field)
        if field == "what" and not isinstance(ref, dict):return None
        if ref is not None:
            if not isinstance(ref, dict):return None
            references.append(ref)
            fields[field] = {k: ref.get(k) for k in _REF_KEYS}
        else:fields[field] = None
    for field in ("participants", "places"):
        refs = episode.get(field, [])
        if not isinstance(refs, list) or len(refs) > 12:return None
        fields[field] = []
        for ref in refs:
            if not isinstance(ref, dict):return None
            references.append(ref)
            fields[field].append({k: ref.get(k) for k in _REF_KEYS})
    # A normalized model batch allows six entity references; bounded later
    # enrichment keeps up to twelve. Validate them individually below.
    evidence, raw = [], {}
    for ref in references:
        nid, role = ref.get("id"), ref.get("role")
        if (not isinstance(nid, str) or not isinstance(role,str) or role not in _ROLES or (nid, role) not in declared
                or nid in blocked):return None
        source = brain.get(nid)
        if not source or source.get("meta", {}).get("library_id") not in (None, library_id):return None
        from .state import fingerprint
        if ref.get('source_revision') != fingerprint(source):return None
        sm = source.get("meta", {})
        if sm.get("memory_disabled") or sm.get("forgotten") or source.get("superseded_by"):return None
        try:
            if not brain._node_state(source, now())["recoverable"]:return None
        except (KeyError, TypeError, ValueError):return None
        if sm.get("source") == "conversation_turn":roles = {"user":source.get("text", ""), "assistant":sm.get("assistant_reply", "")}
        elif sm.get("source") == "tool_observation":roles = {"tool":source.get("text", "")}
        elif sm.get("source") in ("harness_recorded", "agent_output"):roles = {"assistant":source.get("text", "")}
        elif sm.get("source") == "persona_import_source":roles = {"assistant":source.get("text", "")}
        else:return None
        receipt = (sm.get("evidence") or {}).get("archive_receipt_id") if isinstance(sm.get("evidence"),dict) else None
        if receipt in tomb.get("raw_ids", []):return None
        if read_archive is not None and receipt and (sm.get("evidence") or {}).get("content_truncated"):
            try:
                archive = read_archive(receipt)
                if archive:
                    from .state import archive_roles
                    roles = archive_roles(archive)
            except Exception:return None
        if role not in roles or not isinstance(roles[role],str):return None
        context = ref.get("context", ref.get("quote"))
        if not isinstance(context,str) or not context or len(context)>1000 or context not in roles[role]:return None
        at = None if sm.get("source_time_unknown") else _stamp(source.get("event_at"))
        raw[nid] = {"roles":roles,"event_at":at,"outcome":sm.get("outcome"),'source_revision':fingerprint(source)}
        ev=sm.get('evidence')
        if isinstance(ev,dict) and ev.get('participant_scope')=='external_participant':
            raw[nid].update(participant_scope='external_participant',participant_id=ev.get('participant_id','unknown'))
        evidence.append({"id":nid,"role":role,"quote":ref.get("quote"),"context":context,
                         "source_event_at":at,"receipt_id":receipt})
    try:
        normalized = normalize_episode({"layer":"experience","action":"remember",
                                        "episode":{**fields,"participants":[],"places":[]},"evidence":evidence},raw)
        for field in ("participants", "places"):
            normalized[field] = [_reference(ref,evidence,raw,field) for ref in fields[field]]
        result = make_experience({"episode":normalized},node,library_id)
        result["read_only"] = True
        result["confirmation"] = "source_attributed_material"
        return result
    except (OrganizerError, KeyError, TypeError, ValueError, UnicodeError):
        return None


def project_experience(brain, node, library_id, *, read_archive=None):
    """Fail closed on malformed foreign metadata as well as stale provenance."""
    try:
        return _project_experience(brain,node,library_id,read_archive=read_archive)
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError,RecursionError):
        return None


def rebind_experiences_after_import(brain, library_id):
    """Rebind an explicitly imported COPY after source IDs/receipts were mapped.

    Only a trusted importer creating a new identity may call this mutating
    helper. Ordinary reads never re-sign edited sources. Quotes and speaker
    roles are still revalidated; no foreign receipt is opened and no text is
    changed. A withheld entry stays as material but cannot masquerade as a
    verified episode on a later read.
    """
    if (not isinstance(library_id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',library_id)
            or brain.meta.get('demo')):
        raise OrganizerError('导入经历需要明确的新个人存档身份','invalid_episode')
    brain.meta['library_id']=library_id
    candidates=[]
    # Complete all scope/withholding metadata changes before hashing any raw
    # source. Even a forged episode attached to a raw node cannot change that
    # source's revision after another episode has already been rebound.
    for node in brain.nodes.values():
        meta=node.get('meta',{})
        if not isinstance(meta,dict):continue
        if 'library_id' in meta:meta['library_id']=library_id
        if isinstance(meta.get('experience'),dict):
            meta['experience_withheld']=True
            candidates.append(node)
    result={'rebound':0,'withheld':0}
    from .state import fingerprint
    for node in candidates:
        meta=node['meta'];old=meta['experience'];episode=deepcopy(old)
        refs=[]
        try:
            for field in ('what','reason','outcome'):
                ref=episode.get(field)
                if field=='what' and not isinstance(ref,dict):raise ValueError()
                if ref is not None:
                    if not isinstance(ref,dict):raise ValueError()
                    refs.append(ref)
            for field in ('participants','places'):
                values=episode.get(field,[])
                if not isinstance(values,list) or len(values)>12:raise ValueError()
                refs.extend(values)
            for ref in refs:
                if not isinstance(ref,dict) or not isinstance(ref.get('id'),str):raise ValueError()
                source=brain.get(ref['id'])
                if source is None:raise ValueError()
                ref['source_revision']=fingerprint(source)
                # A full-sentence boundary prevents re-signing a stale quote
                # that merely survives inside a newly negated imported line.
                sm=source.get('meta',{});role=ref.get('role')
                text=sm.get('assistant_reply') if role=='assistant' and sm.get('source')=='conversation_turn' else source.get('text')
                context=ref.get('context',ref.get('quote'))
                if not isinstance(text,str) or not isinstance(context,str) or not context:raise ValueError()
                start=text.find(context);boundary=False
                while start>=0:
                    before=text[:start].rstrip();after=text[start+len(context):].lstrip()
                    if ((not before or before[-1] in '。！？!?；;\n')
                            and (not after or context[-1] in '。！？!?；;\n' or after[0] in '。！？!?；;\n')):
                        boundary=True;break
                    start=text.find(context,start+1)
                if not boundary:raise ValueError()
            episode['library_id']=library_id
            meta['experience']=episode
            meta.pop('experience_withheld',None)
            checked=project_experience(brain,node,library_id)
            if checked is None:raise ValueError()
            checked.pop('read_only',None);checked.pop('confirmation',None)
            meta['experience']=checked
            result['rebound']+=1
        except (OrganizerError,KeyError,ValueError,TypeError,AttributeError,UnicodeError):
            meta['experience']=old
            meta['experience_withheld']=True
            result['withheld']+=1
    return result
