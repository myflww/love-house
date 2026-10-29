"""Read-only, scoped, evidence-labelled JSON context for connected agents.

The packet is data, never executable instructions or model weights. Human node
text is not rewritten. Oversized records are omitted whole, not sliced into a
potentially different assertion; the resulting JSON is always valid and bounded.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from collections import Counter
from urllib.parse import urlsplit

from ..errors import ValidationError
from ..utils import now
from .memory import build_context, _text, _count, MAX_TEXT
from .persona import persona_state

SCHEMA = "love-house-memory-context/v1"
ATOM_SCHEMA = "love-house-memory-atom/v1"
LAYERS = {"fact", "preference", "experience", "commitment", "persona"}
ROLES = {"user", "assistant", "tool", "unknown"}
_NEGATION = re.compile(r"不|没|无|否认|拒绝|不要|不能|\b(?:not|never|no|don't|doesn't|cannot)\b", re.I)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _url(value):
    if not isinstance(value, str) or not value or len(value)>4000:return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ("http","https") or not parsed.hostname or parsed.username or parsed.password:return None
        return parsed._replace(query="",fragment="").geturl()
    except ValueError:return None


def _identifier(value, field):
    return None if value is None else _text(value, field, 200).strip()


def _is_duplicate(node, brain):
    # Lazy import permits backwards-compatible source installs during migration.
    # The dedup guard validates the canonical and both content hashes.
    try:
        from .dedup import is_duplicate
    except ImportError:
        return False
    return bool(is_duplicate(node, brain))


def _canonical(brain, node):
    from .dedup import canonical_id
    return canonical_id(brain, node) or node["id"]


def _active(brain, node, stamp):
    meta = node.get("meta", {})
    tomb = brain.meta.get("memory_tombstones", {})
    if (node["id"] in tomb.get("node_ids", []) or meta.get("memory_disabled")
            or meta.get("forgotten") or node.get("superseded_by")):
        return False
    return bool(brain._node_state(node, stamp).get("recoverable"))


def _role(node):
    meta = node.get("meta", {})
    if meta.get("source") == "conversation_turn":
        return "user"
    if meta.get("source") == "tool_observation":
        return "tool"
    if meta.get("source") == "harness_recorded":
        return "assistant"
    value = meta.get("speaker")
    return value if value in ROLES else "unknown"


def _source_refs(brain, node, atom, stamp):
    meta = node.get("meta", {})
    evidence = atom.get("evidence") if isinstance(atom, dict) else None
    evidence = evidence or meta.get("organizer_sources") or meta.get("organizer_evidence") or []
    result = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        source = brain.get(item["id"])
        if source is None or not _active(brain, source, stamp):
            return [], False, 0
        role = item.get("role", _role(source))
        if role not in ROLES:
            role = "unknown"
        # A reference cannot relabel an assistant/tool result as a user statement.
        actual = _role(source)
        if actual in ("assistant", "tool") and role != actual:
            role = actual
        canonical = _canonical(brain, source)
        target = brain.get(canonical)
        if target is None or not _active(brain, target, stamp):
            return [], False, 0
        ref = {"id": canonical, "source_node_id": source["id"], "role": role,
               "source_event_at": _number(item.get("source_event_at", source.get("event_at", source.get("created"))))}
        receipt = _dict(source.get("meta", {}).get("evidence")).get("archive_receipt_id") or item.get("receipt_id")
        outcome=source.get("meta",{}).get("outcome")
        if outcome in ("observed","success","failed"):ref["outcome"]=outcome
        source_url=_url(source.get("meta",{}).get("source_url"))
        if source_url:ref["source_url"]=source_url
        if isinstance(receipt, str) and receipt:
            if receipt in brain.meta.get("memory_tombstones", {}).get("raw_ids", []):
                return [], False, 0
            ref["receipt_id"] = receipt[:300]
        if ref not in result:
            result.append(ref)
    if not result:
        # Directly entered/archived material has itself as its source. Explicit
        # confirmation remains separate from what role the original material had.
        ref = {"id": node["id"], "role": _role(node),
               "source_event_at": None if meta.get("source_time_unknown") else _number(node.get("event_at", node.get("created")))}
        receipt = _dict(meta.get("evidence")).get("archive_receipt_id")
        if isinstance(receipt, str) and receipt:
            if receipt in brain.meta.get("memory_tombstones", {}).get("raw_ids", []):
                return [], False, 0
            ref["receipt_id"] = receipt[:300]
        result.append(ref)
    return result[:8], True, len(result)


def _safe_atom(node):
    """Read only the known atom schema. Edited or inconsistent atoms fall back verbatim."""
    raw = node.get("meta", {}).get("memory_atom")
    if not isinstance(raw, dict) or raw.get("schema") != ATOM_SCHEMA:
        return None
    if node.get("updated") is not None and (_number(raw.get("recorded_at")) or 0) < node["updated"]:
        return None
    if raw.get("layer") not in LAYERS:
        return None
    if any(not isinstance(raw.get(k), str) or not raw[k] or len(raw[k]) > size
           for k, size in (("subject", 200), ("predicate", 200), ("value", MAX_TEXT))):
        return None
    value = raw["value"]
    text = node.get("text", "")
    if value not in text:
        return None
    qualifiers = raw.get("qualifiers") or {}
    if not isinstance(qualifiers, dict) or qualifiers.get("polarity", "unknown") not in ("affirmed", "negated", "unknown"):
        return None
    # This is conservative context protection, not natural-language inference.
    # A lexical affirmative cannot silently discard a surrounding negation.
    polarity = qualifiers.get("polarity", "unknown")
    if polarity == "affirmed" and _NEGATION.search(text):
        return None
    if polarity == "negated" and not _NEGATION.search(text):
        return None
    if raw.get("domain", "unknown") not in ("real", "roleplay", "unknown") or raw.get("certainty", "uncertain") not in ("clear", "uncertain", "conflict"):
        return None
    return deepcopy(raw)


def _record(brain, node, stamp, library_id):
    meta = node.get("meta", {})
    if library_id and meta.get("library_id") not in (None, library_id):
        return None, "different_library"
    if not _active(brain, node, stamp):
        return None, "inactive"
    if _is_duplicate(node, brain):
        return None, "confirmed_duplicate"
    if not isinstance(node.get("text"), str):return None, "invalid_record"
    origin = str(meta.get("source", "local"))[:100]
    atom = _safe_atom(node) if origin == "organizer" else None
    refs, refs_valid, evidence_total = _source_refs(brain, node, atom, stamp)
    if not refs_valid:
        return None, "unavailable_evidence"
    roles = {ref["role"] for ref in refs}
    linked_evidence = any(ref["id"] != node["id"] for ref in refs)
    role = _role(node)
    layer = {"episode": "experience"}.get(node.get("kind"), node.get("kind", "material"))
    predicate = "recorded_statement"
    value = node.get("text", "")
    subject = role
    qualifiers = {"polarity": "unknown"}
    domain, certainty, relation_status = meta.get("domain", "unknown"), "uncertain", "verbatim_fallback"
    if domain not in ("real", "roleplay", "unknown"):domain="unknown"
    if atom:
        subject, predicate, value = (atom[k] for k in ("subject", "predicate", "value"))
        qualifiers = {k: v for k, v in atom.get("qualifiers", {}).items()
                      if k in ("polarity", "scope", "unit") and isinstance(v, str) and len(v) <= 300}
        qualifiers.setdefault("polarity", "unknown")
        layer, domain, certainty = atom["layer"], atom.get("domain", "unknown"), atom.get("certainty", "uncertain")
        relation_status = atom.get("relation_status", "model_extracted")
        if relation_status not in ("model_extracted","verbatim_fallback"):relation_status="verbatim_fallback"
    if origin == "conversation_turn":
        layer, subject, predicate = "dialogue", "user", "said"
        status, interpretation = "historical_user_statement", "historical_evidence"
    elif origin == "harness_recorded":
        layer, subject, predicate = "suggestion", "agent", "suggested"
        status, interpretation = "agent_suggestion", "unverified_material"
    elif origin == "tool_observation" or (origin == "organizer" and roles == {"tool"}):
        layer, subject, predicate, value = "observation", "tool", "reported", node.get("text", "")
        qualifiers = {"polarity":"unknown"}
        status, interpretation = "tool_reported_observation", "historical_evidence"
    elif origin == "user_confirmed" and meta.get("confirmed") is True:
        status, interpretation = "user_confirmed_statement", "current_memory"
        subject = "user" if subject == "unknown" else subject
    elif origin == "organizer" and "user" in roles and linked_evidence:
        if atom and (domain != "real" or certainty != "clear"):
            status, interpretation = "uncertain_model_relation", "unverified_material"
        else:
            status, interpretation = "evidence_backed_statement", "current_memory"
    elif origin == "organizer" and roles == {"assistant"}:
        layer, subject, predicate, value = "agent_statement", "agent", "said", node.get("text", "")
        qualifiers = {"polarity":"unknown"}
        status, interpretation = "historical_assistant_statement", "historical_evidence"
    else:
        status, interpretation = "unverified_import", "unverified_material"
    if meta.get("demo") or brain.meta.get("demo"):
        status, interpretation, domain = "demonstration_material", "unverified_material", "unknown"
    record = {"id": node["id"], "canonical_id": _canonical(brain, node), "layer": layer,
              "subject": subject, "predicate": predicate, "value": value, "qualifiers": qualifiers,
              "epistemic_status": status, "interpretation": interpretation,
              "domain": domain, "certainty": certainty, "relation_status": relation_status,
              "source_time": None if meta.get("source_time_unknown") else _number((atom or {}).get("event_at", node.get("event_at", node.get("created")))),
              "recorded_at": _number(node.get("created")),
              "validity": {"active": True, "valid_from": _number(node.get("valid_from", node.get("created"))),
                           "valid_to": _number(node.get("valid_to")), "superseded_by": None},
              "source": {"kind": origin, "evidence": refs, "evidence_count": evidence_total,
                         "evidence_omitted": max(0, evidence_total - len(refs))},
              "display": {"title": str(node.get("label", ""))[:100]}}
    semantic_key=(atom or {}).get("key") or meta.get("organizer_key")
    if isinstance(semantic_key,str) and semantic_key.strip() and len(semantic_key)<=200:
        record["key"]=semantic_key
    if value != node.get("text", ""):
        record["display"]["text"] = node.get("text", "")
    else:
        record["display"]["text_ref"] = "value"
    if origin == "conversation_turn" and isinstance(meta.get("assistant_reply"), str):
        record["assistant_statement"] = {"role": "assistant", "value": meta["assistant_reply"], "is_user_fact": False}
    source_url=_url(meta.get("source_url"))
    if source_url:record["source"]["url"]=source_url
    if meta.get("outcome"):
        record["source"]["outcome"] = str(meta["outcome"])[:32]
    outcomes=sorted({r["outcome"] for r in refs if r.get("outcome") in ("observed","success","failed")})
    if outcomes:record["source"]["evidence_outcomes"]=outcomes
    possible = [i for i in (meta.get("possible_duplicate_ids") if isinstance(meta.get("possible_duplicate_ids"), list) else []) if isinstance(i, str) and brain.get(i)]
    if possible:
        record["possible_duplicate_ids"] = list(dict.fromkeys(possible))[:12]
        record["possible_duplicate_count"] = len(set(possible))
    sources = meta.get("recording_sources")
    if isinstance(sources, list) and sources:
        projected = []
        for item in sources[:8]:
            if not isinstance(item, dict):
                continue
            projected.append({k: item[k] for k in ("node_id", "origin", "channel", "archive_receipt_id", "recorded_at")
                              if isinstance(item.get(k), (str, int, float)) and not isinstance(item.get(k), bool)
                              and (not isinstance(item[k], float) or math.isfinite(item[k]))})
        record["source"]["recording_sources"] = projected
        record["source"]["recording_source_count"] = len(sources)
        record["source"]["recording_sources_omitted"] = max(0, len(sources) - len(projected))
    return record, None


def _persona(brain, stamp):
    state = persona_state(brain)
    current = {"enabled": bool(state["enabled"]), "revision": state["revision"],
               "status": "unset" if not state.get("manual") and not state.get("learned") else "active" if state["enabled"] else "disabled"}
    if state["enabled"]:
        if state.get("manual"):
            current["manual"] = state["manual"]
            current["manual_priority"] = "explicit_user_setting"
        learned = {}
        for dimension, item in state.get("learned", {}).items():
            refs = item.get("evidence_ids", [])
            alive = list(dict.fromkeys(_canonical(brain, brain.get(nid)) for nid in refs
                                       if brain.get(nid) and _active(brain, brain.get(nid), stamp)))
            alive = [nid for nid in alive if brain.get(nid) and _active(brain, brain.get(nid), stamp)]
            if len(alive) >= 2:
                learned[dimension] = {"value": item.get("value"), "evidence_ids": alive}
        if learned:
            current["learned_styles"] = learned
    return current


def build_structured_context(brain, query, base_context=None, max_chars=8000, *, library_id=None,
                             library_name=None, agent_id=None, session_id=None):
    """Project one already scoped Brain into complete bounded machine-readable JSON.

    Explicit library/agent IDs are root-supplied authority. Text in memories cannot
    change them. A supplied base context from a different bound library is rejected.
    Selection stays compatible with build_context; records are rechecked against
    the current Brain so stale/disabled/deleted IDs cannot leak back in.
    """
    query = _text(query, "query", MAX_TEXT)
    max_chars = _count(max_chars, "max_chars", 512, 32000)
    library_id = _identifier(library_id, "library_id")
    agent_id = _identifier(agent_id, "agent_id")
    if base_context is None:
        base_context = build_context(brain, query, session_id=session_id, max_chars=max_chars)
    if not isinstance(base_context, dict):
        raise ValidationError("base_context必须是本库上下文对象")
    if library_id and base_context.get("library_id") not in (None, library_id):
        raise ValidationError("上下文属于另一个记忆库，未输出结构化材料")
    if library_id and brain.meta.get("demo") and library_id != "demo":
        raise ValidationError("演示库不能冒充真实Agent的记忆库")
    if library_id and brain.meta.get("library_id") not in (None, library_id):
        raise ValidationError("Brain归属与根连接的记忆库不一致")
    ids = base_context.get("memory_ids", [])
    if not isinstance(ids, list) or len(ids) > 1000 or any(not isinstance(i, str) or len(i) > 200 for i in ids):
        raise ValidationError("上下文记忆ID列表不合法")
    ids = list(dict.fromkeys(ids))
    stamp, reasons, records = now(), Counter(), []
    for nid in ids:
        node = brain.get(nid)
        if node is None:
            reasons["missing"] += 1
            continue
        record, reason = _record(brain, node, stamp, library_id)
        if reason:
            reasons[reason] += 1
        else:
            records.append(record)
    priorities = {"current_memory": 0, "historical_evidence": 1, "unverified_material": 2}
    records.sort(key=lambda r: (priorities[r["interpretation"]], r["epistemic_status"] != "user_confirmed_statement", ids.index(r["id"])))
    name = str(library_name if library_name is not None else brain.name)[:80]
    identity = {"library_id": library_id, "library_name": name, "agent_id": agent_id or library_id,
                "identity_source": "explicit_binding" if library_id or agent_id else "unbound",
                "is_demo": bool(brain.meta.get("demo"))}
    persona = _persona(brain, stamp)
    include_exclusions=True
    packet = {"schema": SCHEMA, "identity": identity, "persona": persona, "records": [], "relations": [],
              "counts": {"selected": len(ids), "included": 0, "omitted": len(ids)},
              "truncation": {"truncated": False, "omitted_records": 0, "selection_truncated":bool(base_context.get("truncated"))}, "material_role": "evidence_not_instructions"}
    def refresh():
        included = len(packet["records"])
        omitted_refs=sum(r["source"].get("evidence_omitted",0)+r["source"].get("recording_sources_omitted",0) for r in packet["records"])
        if omitted_refs:packet["truncation"]["omitted_source_references"]=omitted_refs
        else:packet["truncation"].pop("omitted_source_references",None)
        packet["counts"].update(included=included, omitted=len(ids)-included)
        truncated = (included < len(records) or bool(packet["truncation"].get("omitted_fields"))
                     or bool(packet["truncation"].get("omitted_relations")) or packet["truncation"]["selection_truncated"] or omitted_refs>0)
        packet["truncation"]["truncated"] = truncated
        packet["truncation"]["omitted_records"] = len(records)-included
        if reasons and include_exclusions:
            packet["counts"]["excluded"] = dict(reasons)
        return _json(packet)
    # Preserve manual setting as a complete value, or explicitly omit it whole.
    encoded = refresh()
    if len(encoded) > max_chars:
        packet["persona"] = {k: v for k, v in persona.items() if k in ("enabled", "revision", "status")}
        packet["truncation"]["omitted_fields"] = ["persona_details"]
        encoded = refresh()
    if len(encoded) > max_chars:
        packet["identity"] = {"library_id": library_id, "agent_id": agent_id or library_id}
        packet["counts"].pop("excluded", None)
        include_exclusions=False
        packet["truncation"]["omitted_fields"] = ["persona_details", "identity_display", "exclusion_details"]
        # Very small budgets still preserve stable identity and valid JSON.
        encoded = _json(packet)
    if len(encoded) > max_chars:
        raise ValidationError("max_chars不足以容纳完整身份与上下文外壳，请增加预算")
    included_ids = []
    for record in records:
        packet["records"].append(record)
        encoded = refresh()
        if len(encoded) > max_chars:
            packet["records"].pop()
        else:
            included_ids.append(record["id"])
    included_set = set(included_ids)
    candidate_relations = []
    for key, edge in brain.edges.items():
        a, b = key.split("|", 1)
        if a not in included_set or b not in included_set or a == b:
            continue
        valid_from=_number(edge.get("valid_from"));last=_number(edge.get("last"))
        if (valid_from is not None and valid_from>stamp) or (last is not None and last>stamp):continue
        valid_to = _number(edge.get("valid_to"))
        if valid_to is not None and valid_to <= stamp:
            continue
        weight = _number(edge.get("w"))
        if weight is not None and weight>0:
            weight=min(1.0,weight)
            candidate_relations.append({"source": a, "target": b, "type": "associated", "weight": weight})
    relation_omitted = 0
    for relation in candidate_relations[:32]:
        packet["relations"].append(relation)
        if len(refresh()) > max_chars:
            packet["relations"].pop()
            relation_omitted += 1
    relation_omitted += max(0, len(candidate_relations)-32)
    if relation_omitted:
        packet["truncation"]["omitted_relations"] = relation_omitted
        packet["truncation"]["truncated"] = True
    encoded = refresh()
    # Accounting itself can require a few bytes. Evict whole lowest-priority
    # records rather than cutting JSON or a negated statement in half.
    while len(encoded) > max_chars and packet["records"]:
        removed = packet["records"].pop()["id"]
        included_ids.remove(removed)
        packet["relations"] = [e for e in packet["relations"] if removed not in (e["source"], e["target"])]
        encoded = refresh()
    if len(encoded) > max_chars:
        raise ValidationError("完整JSON上下文超过预算，未返回截断JSON")
    result = deepcopy(base_context)
    old_packet = result.get("packet")
    messages = result.get("messages", [])
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user" and message.get("content") == old_packet:
                message["content"] = encoded
    result.update(schema=SCHEMA, memory_context=packet, packet=encoded, memory_ids=included_ids,
                  hits=[h for h in result.get("hits", []) if h.get("id") in included_ids],
                  baseline=[n for n in result.get("baseline", []) if n.get("id") in included_ids],
                  packet_chars=len(encoded), truncated=packet["truncation"]["truncated"], read_only=True)
    return result
