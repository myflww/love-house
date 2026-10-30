"""Evidence-aware recording aliases. Raw nodes and archive receipts are never deleted.

Automatic/manual capture can observe the same dialogue twice. A confirmed alias
is a presentation/retrieval decision, not a change to what either source said.
Unknown window identity or partial quotations remain review candidates.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from bisect import bisect_left,bisect_right

from ..errors import ValidationError

WINDOW_SECONDS = 120.0
MAX_SOURCES = 48
MAX_CANDIDATES = 24
PASSIVE_ORIGINS = {"harness_hook", "api_proxy", "connected_chat", "harness", "automatic_capture"}
MANUAL_ORIGINS = {"manual_record", "manual_harness", "harness_manual", "manual_import"}


def _normalize(text):
    # Only transport line endings and outer padding; punctuation/case/negation matter.
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def pair_hash(node):
    m = node.get("meta", {})
    values = (node.get("text"), m.get("assistant_reply"))
    if any(not isinstance(v, str) for v in values):
        return ""
    return sha256(json.dumps([_normalize(v) for v in values], ensure_ascii=False).encode()).hexdigest()


def recording_version(node):
    """Stable review guard; dedup annotations themselves must not stale the dialog."""
    m = node.get("meta", {})
    material = [node.get("id"), pair_hash(node), node.get("session_id"), node.get("created"),
                m.get("origin"), m.get("recorded_by"), m.get("memory_disabled"), node.get("valid_to")]
    return sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_recording_source(*, origin="manual_record", external_session_id=None,
                              source_event_id=None, connection_id=None):
    result = {"origin": origin, "external_session_id": external_session_id,
              "source_event_id": source_event_id, "connection_id": connection_id}
    for key, value in result.items():
        if value is None and key != "origin": continue
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValidationError(f"记录来源{key}须为1~200字的字符串")
        try: value.encode("utf-8")
        except UnicodeError: raise ValidationError("记录来源包含无法保存的字符") from None
        result[key] = value.strip()
    return result


def _raw(node):
    return isinstance(node, dict) and node.get("meta", {}).get("source") == "conversation_turn" and bool(pair_hash(node))


def _source(node):
    m = node.get("meta", {})
    origin = m.get("recording_origin") or m.get("origin") or ("manual_harness" if m.get("recorded_by") == "harness" else "manual_record")
    if not isinstance(origin,str):origin="unknown"
    channel = m.get("recording_channel")
    if channel not in ("manual", "passive", "unknown"):
        channel = "manual" if origin in MANUAL_ORIGINS else "passive" if m.get("connection_id") or origin in PASSIVE_ORIGINS else "unknown"
    result = {"node_id": node["id"], "origin": str(origin)[:200], "channel": channel,
              "session_id": node.get("session_id"), "external_session_id": m.get("external_session_id"),
              "recorded_at": node.get("created", 0)}
    for key, value in (("source_event_id", m.get("recording_event_id")), ("connection_id", m.get("connection_id"))):
        if isinstance(value, str) and value: result[key] = value
    evidence = m.get("evidence") or {}
    if isinstance(evidence, dict) and isinstance(evidence.get("archive_receipt_id"), str):
        result["archive_receipt_id"] = evidence["archive_receipt_id"]
    return result


def _windows(node):
    m = node.get("meta", {})
    return {v for v in (node.get("session_id"), m.get("external_session_id")) if isinstance(v, str) and v}


def canonical_id(brain, node_or_id):
    node = brain.get(node_or_id) if isinstance(node_or_id, str) else node_or_id
    if not isinstance(node, dict): return None
    original, seen = node["id"], set()
    for _ in range(16):
        if node["id"] in seen: return original
        seen.add(node["id"])
        m = node.get("meta", {})
        target = m.get("duplicate_of")
        if not target or not m.get("exclude_for_recall"): return node["id"]
        guard = m.get("dedup_source_hash")
        if not guard or guard != pair_hash(node): return original
        parent = brain.get(target)
        if parent is None:
            if target in brain.meta.get("memory_tombstones",{}).get("node_ids",[]):return target
            # Capacity eviction is not intentional forgetting. Promote one still
            # preserved observation in this group instead of exposing every alias.
            group=m.get("dedup_group_id")
            survivors=[n for n in brain.nodes.values() if _raw(n)
                       and n.get("meta",{}).get("dedup_group_id")==group
                       and n.get("meta",{}).get("dedup_source_hash")==pair_hash(n)] if group else []
            return _prefer(survivors)["id"] if survivors else original
        if pair_hash(parent) != m.get("dedup_canonical_hash"): return original
        node = parent
    return original


def is_duplicate(node, brain=None):
    if not _raw(node): return False
    m = node.get("meta", {})
    if not (m.get("duplicate_of") and m.get("exclude_for_recall") and m.get("dedup_status") == "confirmed"):
        return False
    if m.get("dedup_source_hash") != pair_hash(node): return False
    return canonical_id(brain, node) != node["id"] if brain is not None else True


def canonical_turns(brain, session_id=None):
    """One primary turn per confirmed source group; aliases supply session membership."""
    result = []
    for node in brain.nodes.values():
        if not _raw(node) or is_duplicate(node, brain): continue
        if session_id is not None:
            aliases = {node.get("session_id")}
            aliases.update(s.get("session_id") for s in node.get("meta", {}).get("recording_sources", []) if isinstance(s, dict))
            if session_id not in aliases: continue
        result.append(node)
    return result


def _group_members(brain, node):
    root = canonical_id(brain, node)
    if root is None: return []
    return [n for n in brain.nodes.values() if _raw(n) and canonical_id(brain, n) == root]


def _prefer(nodes):
    return min(nodes, key=lambda n: (_source(n)["channel"] != "passive", n.get("created", 0), n["id"]))


def _link_group(brain, nodes, *, reason, preferred=None):
    nodes = list({n["id"]: n for n in nodes}.values())
    primary = preferred or _prefer(nodes); ids = {n["id"] for n in nodes}
    sources = [_source(n) for n in sorted(nodes, key=lambda n: (n.get("created", 0), n["id"]))]
    # The originals are retained, so a bounded display list never destroys evidence.
    for n in nodes:
        m = n["meta"]
        m["recording_sources"] = deepcopy(sources[:MAX_SOURCES])
        m["dedup_group_id"] = "recordings_" + sha256(json.dumps(sorted(ids)).encode()).hexdigest()[:24]
        m["dedup_status"] = "confirmed";m["dedup_confirmation"] = reason
        m.pop("dedup_manual_separate",None)
        m["dedup_source_hash"] = pair_hash(n);m["dedup_canonical_hash"] = pair_hash(primary)
        m["possible_duplicate_ids"] = [i for i in m.get("possible_duplicate_ids", []) if i not in ids]
        refs = [i for i in m.get("source_ids", []) if i not in ids]
        if n is primary:
            m.pop("duplicate_of", None);m.pop("exclude_for_recall", None)
            if refs: m["source_ids"] = refs
            else: m.pop("source_ids", None)
        else:
            m["duplicate_of"] = primary["id"];m["exclude_for_recall"] = True
            m["source_ids"] = list(dict.fromkeys([*refs, primary["id"]]))
    return primary


def _near(a, b):
    try:
        x, y = float(a.get("created", 0)), float(b.get("created", 0))
        return math.isfinite(x) and math.isfinite(y) and x>0 and y>0 and abs(x-y) <= WINDOW_SECONDS
    except (ValueError, TypeError): return False


def _cross(a, b):
    return {_source(a)["channel"], _source(b)["channel"]} == {"manual", "passive"}


def _same_event(a, b):
    sa, sb = _source(a), _source(b)
    return bool(_windows(a) & _windows(b) and sa.get("source_event_id")
                and sa.get("source_event_id") == sb.get("source_event_id"))


def annotate_turn_recording(brain, nid, *, origin=None, external_session_id=None,
                            source_event_id=None, connection_id=None, _peers=None, _ambiguous=False):
    node = brain.get(nid)
    if not _raw(node): raise ValidationError("只能为真实完成对话登记记录来源")
    m = node["meta"]
    if origin is not None:
        config = validate_recording_source(origin=origin, external_session_id=external_session_id,
                                          source_event_id=source_event_id, connection_id=connection_id)
        m["recording_origin"] = config["origin"]
        m["recording_channel"] = "manual" if config["origin"] in MANUAL_ORIGINS else "passive" if config.get("connection_id") or config["origin"] in PASSIVE_ORIGINS else "unknown"
        for field, dest in (("external_session_id", "external_session_id"), ("source_event_id", "recording_event_id"), ("connection_id", "connection_id")):
            if config.get(field): m[dest] = config[field]
    if m.get("dedup_manual_separate"):
        m["recording_sources"]=[_source(node)]
        return {"canonical_id":nid,"duplicate_of":None,"deduplicated":False}
    if is_duplicate(node, brain):
        primary = brain.get(canonical_id(brain,node))
        _link_group(brain,_group_members(brain,primary),reason=m.get("dedup_confirmation","exact_cross_capture"),preferred=primary)
        return {"canonical_id":primary["id"],"duplicate_of":primary["id"],"deduplicated":True}
    members=_group_members(brain,node) if m.get("dedup_status")=="confirmed" else []
    if len(members)>1:
        primary=brain.get(canonical_id(brain,node))
        _link_group(brain,members,reason=m.get("dedup_confirmation","exact_cross_capture"),preferred=primary)
        return {"canonical_id":primary["id"],"duplicate_of":primary["id"] if primary["id"]!=nid else None,"deduplicated":True}
    candidates, exact = [], []
    user = _normalize(node["text"])
    for peer in (_peers if _peers is not None else brain.nodes.values()):
        if peer["id"] == nid or not _raw(peer) or is_duplicate(peer,brain): continue
        if peer.get("meta",{}).get("memory_disabled") or peer.get("meta",{}).get("forgotten") or peer.get("meta",{}).get("dedup_manual_separate"): continue
        if not _cross(node,peer): continue
        same_event=_same_event(node,peer)
        if not same_event and not _near(node,peer): continue
        if _normalize(peer["text"]) != user: continue
        candidates.append(peer)
        if pair_hash(node) != pair_hash(peer) or not (_windows(node)&_windows(peer)): continue
        members=_group_members(brain,peer)
        # One observation from each capture channel. Identical repeated dialogue
        # later in the same window must not be swallowed by an earlier pair.
        family=_source(node)["channel"]
        if not same_event and any(_source(n)["channel"]==family for n in members): continue
        exact.append(peer)
    if len(exact)==1 and (not _ambiguous or _same_event(node,exact[0])):
        members=[node,*_group_members(brain,exact[0])]
        primary=_link_group(brain,members,reason="same_source_event" if _same_event(node,exact[0]) else "exact_cross_capture")
        return {"canonical_id":primary["id"],"duplicate_of":primary["id"] if primary["id"]!=nid else None,"deduplicated":True}
    # More than one equally plausible match is deliberately left for review.
    for peer in candidates:
        for a,b in ((node,peer),(peer,node)):
            old=a["meta"].get("possible_duplicate_ids",[])
            a["meta"]["possible_duplicate_ids"]=list(dict.fromkeys([*old,b["id"]]))[-MAX_CANDIDATES:]
    m.setdefault("recording_sources",[_source(node)])
    return {"canonical_id":nid,"duplicate_of":None,"deduplicated":False,"possible_duplicates":[n["id"] for n in candidates]}


def reconcile_recordings(brain):
    """Explicit local maintenance, to be called by the owning library transaction."""
    before={i:canonical_id(brain,n) for i,n in brain.nodes.items() if _raw(n)}
    rows=sorted([n for n in brain.nodes.values() if _raw(n)],key=lambda n:(n.get("created",0),n["id"]))
    buckets={};events={}
    for node in rows:
        buckets.setdefault(_normalize(node["text"]),[]).append(node)
        event=_source(node).get('source_event_id')
        if event:events.setdefault(event,[]).append(node)
    indexed={key:([n.get('created',0) for n in values],values) for key,values in buckets.items()}
    for node in rows:
        if is_duplicate(node,brain):continue
        times,values=indexed[_normalize(node['text'])];t=node.get('created',0)
        start=bisect_left(times,t-WINDOW_SECONDS);end=bisect_right(times,t+WINDOW_SECONDS)
        peers=values[start:end];many=len(peers)>256
        # A mass import with ambiguous near-identical turns is a review group,
        # never a license to select an arbitrary capture and erase its identity.
        peers=peers[:256]
        event=_source(node).get('source_event_id')
        if event:peers=list({n['id']:n for n in [*peers,*events.get(event,[])]}.values())
        annotate_turn_recording(brain,node["id"],_peers=peers,_ambiguous=many)
    after={i:canonical_id(brain,n) for i,n in brain.nodes.items() if _raw(n)}
    return {"raw_turns":len(after),"canonical_turns":len(set(after.values())),
            "confirmed_aliases":sum(i!=c for i,c in after.items()),
            "new_aliases":sum(i!=c and before.get(i)==i for i,c in after.items()),
            "possible_groups":len(possible_groups(brain)),"raw_deleted":0}


def possible_groups(brain, limit=50):
    if type(limit) is not int or not 1<=limit<=100: raise ValidationError("候选组数量须为1~100")
    nodes={n["id"]:n for n in canonical_turns(brain) if not n.get("meta",{}).get("dedup_manual_separate")};seen=set();out=[]
    for nid,node in nodes.items():
        if nid in seen: continue
        connected=set();stack=[nid]
        while stack:
            i=stack.pop()
            if i in connected or i not in nodes:continue
            connected.add(i)
            stack.extend(c for j in nodes[i].get("meta",{}).get("possible_duplicate_ids",[]) if (c:=canonical_id(brain,j)) in nodes)
        seen.update(connected)
        if len(connected)<2:continue
        records=sorted((nodes[i] for i in connected),key=lambda n:(n.get("created",0),n["id"]))
        total_records=len(records);records=records[:25]
        primary=_prefer(records)
        out.append({"id":"possible_"+sha256(json.dumps(sorted(connected)).encode()).hexdigest()[:24],
                    "canonical_id":primary["id"],"node_ids":[n["id"] for n in records],"total_records":total_records,"additional_count":total_records-len(records),
                    "reason":"相近时间存在相同用户原话，但窗口或完整回复不足以证明是同一轮；需要确认。",
                    "expected":{n["id"]:recording_version(n) for n in records},
                    "records":[{"id":n["id"],"label":n["label"],"user_excerpt":n["text"][:400],
                       "assistant_excerpt":n["meta"].get("assistant_reply","")[:400],"origin":_source(n)["origin"],
                       "channel":_source(n)["channel"],"recorded_at":n.get("created")} for n in records]})
        if len(out)>=limit:break
    return out


def confirm_duplicate(brain, canonical, alias_ids, expected=None):
    if not isinstance(canonical,str) or not isinstance(alias_ids,list) or not 1<=len(alias_ids)<=24 or any(not isinstance(i,str) for i in alias_ids):
        raise ValidationError("请选择一个主记录及1~24个重复来源")
    ids=list(dict.fromkeys([canonical,*alias_ids]))
    if canonical in alias_ids or len(ids)<2:raise ValidationError("主记录不能同时为重复来源")
    nodes=[brain.get(i) for i in ids]
    if any(not _raw(n) for n in nodes):raise ValidationError("记录已删除或不是完成对话")
    if not isinstance(expected,dict) or set(expected)!=set(ids) or any(expected[n['id']]!=recording_version(n) for n in nodes):
        raise ValidationError("原文或状态已变化，请刷新重复候选再确认")
    tomb=set(brain.meta.get('memory_tombstones',{}).get('node_ids',[]))
    if tomb&set(ids) or any(n['meta'].get('memory_disabled') for n in nodes):raise ValidationError("停用或已忘记的来源不能重新合并")
    all_nodes={n['id']:n for node in nodes for n in _group_members(brain,node)}
    primary=_link_group(brain,list(all_nodes.values()),reason='user_confirmed',preferred=brain.get(canonical))
    return {"canonical_id":primary['id'],"alias_ids":[i for i in all_nodes if i!=primary['id']],"raw_deleted":0,"confirmed":True}


def separate_recordings(brain, node_id, expected=None):
    """Undo a display merge. Never recreate a deleted node or re-enable paused memory."""
    node=brain.get(node_id)
    if not _raw(node):raise ValidationError("原始记录不存在")
    nodes=_group_members(brain,node)
    if len(nodes)<2:raise ValidationError("这条记录没有合并来源")
    if not isinstance(expected,dict) or set(expected)!={n['id'] for n in nodes} or any(expected[n['id']]!=recording_version(n) for n in nodes):
        raise ValidationError("原文或状态已变化，请刷新来源后再取消合并")
    ids={n['id'] for n in nodes}
    for n in nodes:
        m=n['meta']
        for key in ('duplicate_of','exclude_for_recall','dedup_group_id','dedup_status','dedup_confirmation','dedup_source_hash','dedup_canonical_hash'):
            m.pop(key,None)
        m['source_ids']=[i for i in m.get('source_ids',[]) if i not in ids]
        m['possible_duplicate_ids']=[];m['recording_sources']=[_source(n)];m['dedup_manual_separate']=True
    return {'separated':True,'node_ids':sorted(ids),'raw_deleted':0}
