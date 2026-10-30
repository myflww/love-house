"""Adaptive memory policy and deliberate, bounded records of meaningful use.

Policy is per memory identity. Reads never enable a policy, reinforce a memory,
or create a physical expiry date. The outer graph transaction owns persistence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import re

from ..errors import ValidationError
from ..utils import DAY, now as _now

SCHEMA = "love-house-retention/v1"
DEFAULT_POLICY = {"mode": "adaptive", "forgetting_pace": "balanced", "usage_reinforcement": True}
_FIELDS = frozenset(DEFAULT_POLICY)
MAX_USE_IDS = 128
MAX_TRACES = 16
PACE_EXPONENTS = {"gentle": 0.35, "balanced": 0.5, "fast": 0.7}
TRACE_SCALE = 7 * DAY  # A curve unit, never an expiry or protection deadline.


def adaptive_retention_enabled(brain):
    saved = brain.meta.get("memory_retention")
    return bool(isinstance(saved, dict) and saved.get("schema") == SCHEMA and saved.get("mode") == "adaptive")


def _validated(updates):
    if not isinstance(updates, dict) or set(updates) - _FIELDS:
        raise ValidationError("记忆策略仅接受淡化节奏和有效使用强化；不设置按天或条数删除")
    if "mode" in updates and updates["mode"] != "adaptive":
        raise ValidationError("个人记忆库使用自适应淡化策略")
    if "forgetting_pace" in updates and updates["forgetting_pace"] not in ("gentle", "balanced", "fast"):
        raise ValidationError("淡化节奏须为 gentle、balanced 或 fast")
    if "usage_reinforcement" in updates and type(updates["usage_reinforcement"]) is not bool:
        raise ValidationError("有效使用强化必须是开关")
    return dict(updates)


def get_retention_policy(brain):
    """A pure, safe projection; an old library is never migrated by reading it."""
    saved = brain.meta.get("memory_retention")
    settings = dict(DEFAULT_POLICY)
    if isinstance(saved, dict):
        for key in _FIELDS:
            if key in saved:
                try:
                    settings.update(_validated({key: saved[key]}))
                except ValidationError:
                    pass
    return {"schema": SCHEMA, **settings, "enabled": adaptive_retention_enabled(brain),
            "count_eviction": False if adaptive_retention_enabled(brain) else brain.config.max_nodes is not None,
            "automatic_deletion": False if adaptive_retention_enabled(brain) else not bool(brain.meta.get("long_term_archive")),
            "node_limit": None if adaptive_retention_enabled(brain) else brain.config.max_nodes,
            "read_only": True}


def enable_temporal_retention(brain, updates=None):
    """Explicit write migration: preserve every node and clear a legacy count cap.

    The name is kept as the host integration seam. This activates continuous
    adaptive decay, never a fixed time-to-live or a protected calendar window.
    """
    updates = _validated({} if updates is None else updates)
    current = get_retention_policy(brain)
    policy = {"schema": SCHEMA, **{key: current[key] for key in _FIELDS}, **updates}
    changed = (brain.meta.get("memory_retention") != policy or brain.config.max_nodes is not None
               or brain.meta.get("long_term_archive") is not True)
    brain.meta["memory_retention"] = policy
    brain.meta["long_term_archive"] = True
    brain.config.max_nodes = None
    return {**get_retention_policy(brain), "changed": changed, "read_only": False}


def save_retention_policy(brain, updates):
    previous = get_retention_policy(brain)["usage_reinforcement"]
    result = enable_temporal_retention(brain, updates)
    if result["usage_reinforcement"] != previous:
        # A local metadata-ingress boundary, not an age/retention cutoff. Old
        # queued uses must not revive after opt-out, even if the side journal's
        # acknowledgement/purge failed or more than one pending page existed.
        brain.meta["memory_usage_cutoff"] = _now()
    return result


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _usage(node):
    value = node.get("meta", {}).get("memory_usage")
    return value if isinstance(value, dict) else {}


def _day(value):
    try:return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError, TypeError):return None


def adaptive_strength(brain, node, ref):
    """ACT-R-inspired power-law practice model; engineering approximation.

    A = sum(weight * (1 + elapsed / scale) ** -d)
    strength = 1 - (1 - base_salience) ** A

    New evidence at its creation has A=1, preserving its entered salience.
    Meaningful use adds a bounded spaced-practice trace. Older than the newest
    16 uses are compressed to weighted mean time/mass, so lifetime frequency is
    not lost and metadata does not grow with the number of conversations.
    The power law has no deletion date or change at a calendar boundary.
    """
    policy = get_retention_policy(brain)
    usage = _usage(node)
    base = node.get("salience", 0.0)
    if _finite(usage.get("base_at")) and usage["base_at"] <= ref:
        base = usage.get("base_salience", base)
    base = max(0.0, min(1.0, float(base))) if _finite(base) else 0.0
    exponent = PACE_EXPONENTS[policy["forgetting_pace"]]
    traces = [{"at": node.get("created"), "weight": 1.0}]
    recent = usage.get("traces")
    if isinstance(recent, list):
        traces.extend(item for item in recent[-MAX_TRACES:] if isinstance(item, dict))
    prior = usage.get("prior_reinforced_at")
    if prior is None and not recent:
        prior = node.get("reinforced")
    if _finite(prior) and prior > node.get("created", prior):
        traces.append({"at": prior, "weight": 1.0})
    older = usage.get("older")
    if (isinstance(older, dict) and _finite(older.get("last_at"))
            and older["last_at"] <= ref):
        # Before the aggregate's latest event, omit it conservatively rather
        # than leak the mass of a future practice into a historical preview.
        traces.append({"at": older.get("at"), "weight": older.get("weight")})
    activation = 0.0
    for item in traces:
        at, weight = item.get("at"), item.get("weight")
        if not _finite(at) or not _finite(weight) or weight <= 0 or at > ref:
            continue
        activation += min(weight, 1e9) * (1.0 + max(0.0, ref-at) / TRACE_SCALE) ** -exponent
    if activation <= 0 or base <= 0:
        return 0.0
    if base >= 1:
        return 1.0
    return max(0.0, min(1.0, -math.expm1(math.log1p(-base) * activation)))


def _practice_trace(usage, at, weight, kind):
    raw_traces=usage.get("traces")
    traces = [dict(item) for item in (raw_traces[-MAX_TRACES:] if isinstance(raw_traces,list) else [])
              if isinstance(item, dict) and _finite(item.get("at")) and item["at"]>=0
              and _finite(item.get("weight")) and item["weight"]>0]
    traces.append({"at": at, "weight": weight, "kind": kind})
    traces.sort(key=lambda item: item["at"])
    older = usage.get("older")
    older = dict(older) if isinstance(older, dict) else {}
    for item in traces[:-MAX_TRACES]:
        mass, mean = older.get("weight", 0.0), older.get("at", item["at"])
        if not _finite(mass) or mass < 0:mass = 0.0
        if not _finite(mean):mean = item["at"]
        combined = mass + item["weight"]
        previous_last=older.get("last_at",item["at"])
        if not _finite(previous_last):previous_last=item["at"]
        older = {"weight": min(combined, 1e9), "at": mean + (item["at"]-mean) * item["weight"] / combined,
                 "last_at": max(previous_last, item["at"])}
    usage["traces"] = traces[-MAX_TRACES:]
    if older:usage["older"] = older


def record_memory_use(brain, ids, *, kind="recall", now=None):
    """Apply real retrieval/lexical re-mention evidence, never a background read.

    The host queues accepted use separately and calls this in a graph write
    transaction. A retry of the same daily evidence is harmless. No edges,
    profile assertions, source text, IDs in another library or arbitrary code
    are introduced here. Stale events never move reinforcement time backwards.
    """
    if kind not in ("recall", "mention"):
        raise ValidationError("使用类型须为 recall 或 mention")
    if not isinstance(ids, (list, tuple)) or len(ids) > MAX_USE_IDS or any(not isinstance(i, str) or not i or len(i)>200 for i in ids):
        raise ValidationError("一次最多提交128个本库存档记忆ID")
    ts = _now() if now is None else now
    if not _finite(ts) or ts < 0:
        raise ValidationError("使用时间必须是有限 Unix 时间")
    day=_day(ts)
    if day is None:raise ValidationError("使用时间超出有效范围")
    policy = get_retention_policy(brain)
    if not policy["enabled"] or not policy["usage_reinforcement"]:
        return {"kind": kind, "updated_ids": [], "reinforced_ids": [], "skipped_ids": list(ids), "nodes": 0,
                "at": ts, "reason": "usage_reinforcement_disabled", "read_only": False}
    cutoff = brain.meta.get("memory_usage_cutoff")
    if _finite(cutoff) and ts < cutoff:
        return {"kind":kind,"updated_ids":[],"reinforced_ids":[],"skipped_ids":list(ids),"nodes":0,
                "at":ts,"reason":"usage_before_last_setting_change","read_only":False}
    from .dedup import canonical_id
    updated, skipped, seen = [], [], set()
    for requested in dict.fromkeys(ids):
        nid = canonical_id(brain, requested)
        if nid is None or nid in seen:
            skipped.append(requested);continue
        seen.add(nid)
        node = brain.get(nid)
        if (node is None or node.get("meta",{}).get("forgotten")
                or nid in brain.meta.get("memory_tombstones",{}).get("node_ids",[])
                or not brain._node_state(node, ts)["recoverable"]):
            skipped.append(requested);continue
        saved = _usage(node)
        fields=('last_recall_at','last_mention_at','recall_count','mention_count','base_at','base_salience',
                'prior_reinforced_at','older')
        usage = {key:deepcopy(saved[key]) for key in fields if key in saved}
        if isinstance(saved.get('traces'),list):usage['traces']=deepcopy(saved['traces'][-MAX_TRACES:])
        last = usage.get("last_"+kind+"_at")
        if _finite(last) and (ts <= last or ts-last < DAY
                or _day(last) == day):
            skipped.append(requested);continue
        previous = [v for v in (usage.get("last_recall_at"),usage.get("last_mention_at"),node.get("created"))
                    if _finite(v) and v <= ts]
        spacing_days = max(0.0, ts-max(previous or [ts])) / DAY
        # Spaced practice has bounded additional weight; it never weakens
        # unrelated memories merely because many other messages arrived.
        weight = 0.75 + min(1.25, math.log1p(spacing_days) / 2)
        if not usage.get("traces") and "prior_reinforced_at" not in usage:
            prior=node.get("reinforced")
            if _finite(prior) and prior > node.get("created",prior):usage["prior_reinforced_at"]=prior
        base=usage.get("base_salience",node.get("salience",0.0))
        usage["base_salience"] = max(float(base) if _finite(base) else 0.0, brain.config.salience_bump)
        if not _finite(usage.get("base_at")):usage["base_at"]=ts
        count=usage.get(kind+"_count",0)
        usage[kind+"_count"]=min(1000000000,count+1) if type(count) is int and count>=0 else 1
        usage["last_"+kind+"_at"]=ts
        usage["evidence"]="delivered_retrieval" if kind=="recall" else "lexical_remention"
        _practice_trace(usage, ts, weight, kind)
        node.setdefault("meta",{})["memory_usage"]=usage
        node["reinforced"] = max(node.get("reinforced",ts), ts)
        node["decay_at"] = max(node.get("decay_at",ts), ts)
        if kind=="recall":node["recalls"] = node.get("recalls",0) + 1
        updated.append(nid)
    return {"kind": kind, "updated_ids": updated, "reinforced_ids": updated, "skipped_ids": skipped,
            "nodes": len(updated), "at": ts, "read_only": False}


def match_mentions(brain, user_text, session_id=None, *, now=None):
    """Conservative lexical re-mention evidence; not semantic fact confirmation."""
    if not isinstance(user_text,str) or len(user_text)>40000 or not user_text.strip():return []
    # Imported/context packets and fenced quotations are material, not proof
    # that a human independently re-mentioned every sentence in that material.
    if any(marker in user_text for marker in ("<memory_material", "love-house-memory-", '"memory_context"', '"material_role"')):
        return []
    text=re.sub(r"```[\s\S]*?```", "", user_text)
    stamp=_now() if now is None else now
    if not _finite(stamp):return []
    result=[]
    from .dedup import is_duplicate
    for node in brain.nodes.values():
        if (node.get("created",stamp)>=stamp or is_duplicate(node,brain)
                or node.get("meta",{}).get("forgotten")
                or (session_id is not None and node.get("session_id")!=session_id)
                or not brain._node_state(node,stamp)["recoverable"]):continue
        meta=node.get("meta",{})
        match=None
        raw=node.get("text","")
        raw=raw.strip() if isinstance(raw,str) else ""
        if (meta.get("source")=="conversation_turn"
                and 8<=len(raw)<=1000 and raw in text):match="verbatim_user_statement"
        label=node.get("label","")
        label=label.strip() if isinstance(label,str) else ""
        if (match is None and 8<=len(label)<=100 and label in text
                and not label.startswith(("对话 ·", "导入对话 ·", "工具观察", "示例", "关于「"))):match="complete_label"
        if match:result.append({"id":node["id"],"match":match,"evidence":"lexical_remention"})
        if len(result)>=32:break
    return result
