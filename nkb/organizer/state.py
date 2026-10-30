"""Bounded prompt construction, evidence validation, transactional graph operations and undo."""
from copy import deepcopy
from hashlib import sha256
import json
import re

from ..core.brain import Brain
from ..errors import ValidationError
from ..retrieval.scoring import dice
from ..utils import now
from .config import get_profile
from .model import OrganizerConflict, OrganizerError
from .atoms import normalize_atom,make_atom,atom_signature,source_references,evidence_event_at
from .rules import RULES_VERSION, runtime_policy

LAYERS = {"fact": "fact", "preference": "preference", "experience": "episode", "commitment": "commitment", "persona": None}
ACTIONS = {"remember", "merge", "supersede", "relate", "candidate"}
RAW_SOURCES = {"conversation_turn", "tool_observation", "harness_recorded", "persona_import_source"}
HYPOTHETICAL = re.compile(r"假设|假如|如果|角色扮演|小说|想象|扮演|比如|例如|他说|她说|引用|骗你的|导入人格|人格设定")
RELATIONSHIP_ATTRIBUTE = re.compile(r"(?:^|[./:_-])(?:relationship|relation|bond|milestone|anniversary)(?:$|[./:_-])|关系状态|关系阶段|里程碑|纪念日|相识日", re.I)


def fingerprint(node):
    data = {k: node.get(k) for k in ("id", "label", "text", "kind", "session_id", "created", "event_at", "valid_to", "superseded_by", "updated", "important", "impact")}
    # Genuine use changes strength/counts, not the text or provenance a job saw.
    # All other metadata remains guarded, notably disabled/forgotten/evidence.
    data["meta"] = {key:value for key,value in node.get("meta", {}).items() if key != "memory_usage"}
    return sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _roles(node):
    metadata = node.get("meta", {})
    source = metadata.get("source")
    if source == "conversation_turn":
        return {"user": node["text"], "assistant": metadata.get("assistant_reply", "")}
    return {"tool" if source == "tool_observation" else "assistant": node["text"]}


def disabled(node):
    metadata = node.get("meta", {})
    return bool(metadata.get("memory_disabled") or metadata.get("forgotten"))


def raw_node(brain, raw_id):
    direct = brain.get(raw_id)
    if direct is not None:
        return direct
    return next((n for n in brain.nodes.values() if isinstance(n.get("meta", {}).get("evidence"), dict)
                 and n["meta"]["evidence"].get("archive_receipt_id") == raw_id), None)


def archive_roles(archive):
    normalized = archive
    for _ in range(4):
        if not isinstance(normalized, dict): break
        if isinstance(normalized.get("normalized"), dict):
            normalized = normalized["normalized"]
            break
        if isinstance(normalized.get("record"), dict):
            normalized = normalized["record"]
        else: break
    if normalized.get("type") == "tool":
        value = normalized.get("text", normalized.get("content", ""))
        return {"tool": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}
    return {k: normalized[k] for k in ("user", "assistant") if isinstance(normalized.get(k), str)}


def build_input(brain, library_id, items, profile, archives=None):
    """Only unfinished slices plus a small related-memory neighborhood, never the full archive."""
    from ..companion.dedup import is_duplicate,canonical_id
    budget = profile["max_input_chars"]
    records, progress, consumed, raw_hashes, aliases = [], {}, [], {}, []
    raw_budget = max(1200, int(budget * .65))
    each = max(300, raw_budget // max(1, len(items)) - 400)
    for item in items:
        receipt_id = item["raw_id"]
        node = raw_node(brain, receipt_id)
        if node is None or disabled(node) or node.get("meta", {}).get("source") not in RAW_SOURCES:
            raise OrganizerError("待整理原文不存在或不是原始事件，未处理", "missing_raw")
        nid = node["id"]
        if is_duplicate(node,brain):
            raw_hashes[nid]=fingerprint(node)
            progress[receipt_id]={"confirmed_alias":True}
            consumed.append(receipt_id);aliases.append(receipt_id)
            continue
        cursors = json.loads(item.get("progress") or "{}")
        selected, room = {}, each
        boundaries = {}
        archive = (archives or {}).get(receipt_id)
        evidence_meta = node.get("meta", {}).get("evidence")
        truncated = (isinstance(evidence_meta, dict) and evidence_meta.get("content_truncated")) or "节点摘录；完整" in node["text"]
        if truncated and not archive:
            raise OrganizerError("原文节点只是截断摘录，需完整归档才能继续整理", "missing_archive")
        roles = archive_roles(archive) if archive else _roles(node)
        if not roles or not any(isinstance(text,str) and text for text in roles.values()):
            raise OrganizerError("完整归档缺少角色原文，未假装完成整理", "missing_archive")
        for role, text in roles.items():
            offset = cursors.get(role, 0)
            if not isinstance(text, str):
                raise OrganizerError("原始角色文本格式不正确", "invalid_raw")
            piece = text[offset:offset + room]
            if piece:
                selected[role] = piece
                boundaries[role] = {"left":offset == 0 or text[offset-1] in "。！？!?；;\n",
                                    "right":offset+len(piece) == len(text) or piece[-1] in "。！？!?；;\n"}
                cursors[role] = offset + len(piece)
                room -= len(piece)
        records.append({"id": nid, "receipt_id": (evidence_meta.get('archive_receipt_id') if isinstance(evidence_meta,dict) else None) or receipt_id, "roles": selected, "boundaries":boundaries,
                        "created":node.get("created"),
                        "event_at":None if node.get("meta",{}).get("source_time_unknown") else node.get("event_at"),
                        "source_time_known":not bool(node.get("meta",{}).get("source_time_unknown")) and node.get("event_at") is not None,
                        "recording_group":{"canonical_id":canonical_id(brain,node),
                            "capture_source_count":len(node.get('meta',{}).get('recording_sources',[]))},
                        "origin": node["meta"].get("origin", node["meta"]["source"]),
                        "outcome": node["meta"].get("outcome"), "source_url": str(node["meta"].get("source_url") or "")[:300],
                        "fiction_or_hypothesis_hint": bool(HYPOTHETICAL.search(roles.get("user", ""))),
                        "context_prefix": roles.get("user", "")[:160]})
        progress[receipt_id] = cursors
        if all(cursors.get(role, 0) >= len(text) for role, text in roles.items()):
            consumed.append(receipt_id)
        raw_hashes[nid] = fingerprint(node)
    query = " ".join(" ".join(r["roles"].values())[:200] for r in records)
    related = []
    for hit in brain.recall(query, k=8)["hits"]:
        node = brain.get(hit["id"])
        if node["id"] in raw_hashes or disabled(node) or node.get("meta", {}).get("source") in RAW_SOURCES:
            continue
        related.append({"id": node["id"], "kind": node["kind"], "text": node["text"][:900],
                        "key": node.get("meta", {}).get("organizer_key"), "protected": protected(node),
                        "atom":{k:deepcopy(node.get('meta',{}).get('memory_atom',{}).get(k)) for k in ('subject','predicate','value','qualifiers','layer')}})
    payload = {"library_id": library_id, "memory_policy": runtime_policy(brain), "raw": records, "related": related}
    while related and len(json.dumps(payload, ensure_ascii=False)) > budget:
        related.pop()
    if len(json.dumps(payload, ensure_ascii=False)) > budget:
        raise OrganizerError("本批输入超过预算，未发送", "input_budget")
    return payload, {"raw_fingerprints": raw_hashes,
                     "existing_fingerprints": {r["id"]: fingerprint(brain.get(r["id"])) for r in related},
                     "progress": progress, "complete_ids": consumed,"alias_ids":aliases}


def protected(node):
    metadata = node.get("meta", {})
    return (metadata.get("source") != "organizer" or bool(node.get("important"))
            or bool(metadata.get("important")) or bool(metadata.get("confirmed"))
            or node.get("updated") is not None or abs(node.get("impact", 0)) >= .75)


def _string(value, name, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise OrganizerError(f"模型{name}字段不合法", "invalid_output")
    return value.strip()


def _sentence(record, role, quote):
    text = record["roles"][role]
    start = text.index(quote)
    end = start + len(quote)
    separators = "。！？!?；;\n"
    left = max((text.rfind(c,0,start) for c in separators),default=-1)
    endings = ([end-1] if end and text[end-1] in separators else
               [text.find(c,end) for c in separators if text.find(c,end) != -1])
    right = min(endings) + 1 if endings else len(text)
    context = text[left+1:right].strip()
    bounds = record.get("boundaries",{}).get(role,{"left":True,"right":True})
    complete = (left >= 0 or bounds["left"]) and (bool(endings) or bounds["right"]) and len(context) <= 1000
    return context if len(context)<=1000 else quote, complete


def validate_plan(output, payload, guards, job_id, profile):
    if not isinstance(output, dict) or set(output) - {"version", "operations"} or type(output.get("version")) is not int or output.get("version") != 1:
        raise OrganizerError("模型JSON顶层schema不合法", "invalid_output")
    operations = output.get("operations")
    if not isinstance(operations, list) or len(operations) > profile["max_ops"]:
        raise OrganizerError("模型操作数量不合法", "invalid_output")
    raw = {r["id"]: r for r in payload["raw"]}
    related = {r["id"] for r in payload["related"]}
    normalized = []
    allowed = {"action", "layer", "key", "text", "evidence", "target_id", "aliases", "related_ids", "certainty", "domain", "atom"}
    for op in operations:
        if (not isinstance(op, dict) or set(op) - allowed or op.get("action") not in ACTIONS
                or op.get("layer") not in LAYERS):
            raise OrganizerError("模型操作schema不合法；不允许代码、删除或直接改原文", "invalid_output")
        op = deepcopy(op)
        op["key"] = _string(op.get("key"), "key", 200)
        op["text"] = _string(op.get("text"), "text")
        op.setdefault("certainty", "uncertain")
        op.setdefault("domain", "unknown")
        if op["certainty"] not in ("clear", "uncertain", "conflict") or op["domain"] not in ("real", "roleplay", "unknown"):
            raise OrganizerError("模型确定性或现实域字段不合法", "invalid_output")
        evidence = op.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 6:
            raise OrganizerError("每项整理需要1~6条本批次原文证据", "invalid_evidence")
        for quote in evidence:
            if not isinstance(quote, dict) or set(quote) != {"id", "role", "quote"}:
                raise OrganizerError("证据schema不合法", "invalid_evidence")
            record = raw.get(quote["id"]) if isinstance(quote["id"], str) else None
            value = _string(quote.get("quote"), "quote", 500)
            if record is None or quote.get("role") not in ("user","assistant","tool") or quote.get("role") not in record["roles"] or value not in record["roles"][quote["role"]]:
                raise OrganizerError("模型引用不属于给定批次/库/角色的逐字证据", "invalid_evidence")
            quote["quote"] = value
            quote["context"], quote["complete_sentence"] = _sentence(record,quote["role"],value)
            quote["receipt_id"] = record["receipt_id"]
            quote["source_event_at"] = record.get("event_at")
        aliases = op.setdefault("aliases", [])
        neighbors = op.setdefault("related_ids", [])
        if not isinstance(aliases, list) or len(aliases) > 8:
            raise OrganizerError("查询别名数量不合法", "invalid_output")
        op["aliases"] = list(dict.fromkeys(_string(a, "alias", 80) for a in aliases))
        if not isinstance(neighbors, list) or len(neighbors) > 6 or any(not isinstance(i, str) or i not in related | set(raw) for i in neighbors):
            raise OrganizerError("关联线索超出给定库或批次", "invalid_evidence")
        if "target_id" in op and (not isinstance(op["target_id"],str) or op["target_id"] not in related | set(raw)):
            raise OrganizerError("目标不属于提供的库与批次", "invalid_evidence")
        if op["action"] in ("merge", "supersede") and op.get("target_id") not in related:
            raise OrganizerError("更新目标未出现在相关旧记忆中", "invalid_evidence")
        if op["action"] == "relate" and op.get("target_id") not in related | set(raw):
            raise OrganizerError("关联目标未出现在输入中", "invalid_evidence")
        user_quotes = [e["context"] for e in evidence if e["role"] == "user"]
        tool_quotes = [e["quote"] for e in evidence if e["role"] == "tool"]
        observation = (not user_quotes and bool(tool_quotes) and op["layer"] in ("fact","experience")
                       and all(e["role"] == "tool" for e in evidence)
                       and all(raw[e["id"]].get("outcome") in ("observed","success","failed") for e in evidence))
        fiction = any(raw[e["id"]]["fiction_or_hypothesis_hint"] for e in evidence)
        op["requires_review"] = (op["action"] == "candidate" or op["layer"] == "persona"
                                  or bool(RELATIONSHIP_ATTRIBUTE.search(op["key"]))
                                  or op["certainty"] != "clear" or op["domain"] != "real" or fiction
                                  or (not user_quotes and not observation)
                                  or any(not e["complete_sentence"] for e in evidence if e["role"] == "user")
                                  or len("\n".join(user_quotes)) > 2000)
        op["verbatim_text"] = "\n".join(dict.fromkeys(user_quotes))[:2000]
        op["source_fiction"] = fiction
        op["observation"] = observation
        if observation:
            outcomes = list(dict.fromkeys(raw[e["id"]]["outcome"] for e in evidence))
            op['observation_outcomes']=outcomes
            op["verbatim_text"] = "工具观察（" + ",".join(outcomes) + "，不是用户确认事实）：\n" + "\n".join(dict.fromkeys(tool_quotes))[:1800]
        op['atom'],atom_review=normalize_atom(op)
        op['requires_review']=op['requires_review'] or atom_review
        normalized.append(op)
    return {"version": 1, "rules_version": RULES_VERSION, "job_id": job_id, "library_id": payload["library_id"],
            "profile": deepcopy(profile), "operations": normalized, **deepcopy(guards)}


def _check(brain, plan, library_id):
    if plan.get("library_id") != library_id:
        raise OrganizerConflict("整理结果属于另一个库，未应用")
    if plan.get("rules_version") != RULES_VERSION:
        raise OrganizerConflict("整理准则已更新，旧缓存结果需按当前规则重新校验")
    if get_profile(brain) != plan["profile"] or not get_profile(brain)["enabled"]:
        raise OrganizerConflict("整理配置已改变或已关闭，未应用旧结果")
    for nid, digest in {**plan["raw_fingerprints"], **plan["existing_fingerprints"]}.items():
        node = brain.get(nid)
        if node is None or disabled(node) or fingerprint(node) != digest:
            raise OrganizerConflict()


def apply_plan(brain, plan, library_id):
    """Call under the owning library lock; outer callback persists before acknowledging success."""
    if not isinstance(plan, dict) or not isinstance(plan.get("job_id"), str):
        raise OrganizerError("整理计划格式不正确", "invalid_plan")
    log = brain.meta.get("organizer_log", [])
    previous = next((r for r in log if r["job_id"] == plan["job_id"]), None)
    if previous:
        if previous.get("rolled_back"):
            raise OrganizerConflict("该整理结果已被撤回，不能再次应用")
        return {**deepcopy(previous["result"]), "duplicate": True}
    _check(brain, plan, library_id)
    before = {k: deepcopy(getattr(brain, k)) for k in ("nodes", "edges", "meta", "_vec")}
    result = {"job_id": plan["job_id"], "created": [], "merged": [], "superseded": [], "candidates": [], "linked": []}
    candidates = deepcopy(brain.meta.get("organizer_candidates", []))
    touched = set()
    try:
        for index, original in enumerate(plan["operations"]):
            op=deepcopy(original)
            if 'atom' not in op:op['atom']=normalize_atom(op)[0]
            target = brain.get(op.get("target_id", ""))
            expected_layer = "experience" if op.get("observation") else op["layer"]
            incompatible = (target is not None and op["action"] in ("merge","supersede")
                            and (protected(target) or target["meta"].get("organizer_key") != op["key"]
                                 or target["meta"].get("organizer_layer") != expected_layer))
            incoming_atom={**op['atom'],'layer':expected_layer}
            signature=atom_signature(incoming_atom)
            duplicate=next((n for n in brain.nodes.values()
                 if n.get('meta',{}).get('source')=='organizer' and not disabled(n) and n.get('valid_to') is None
                 and n['meta'].get('organizer_layer')==expected_layer
                 and ((n['meta'].get('organizer_key')==op['key'] and n['text']==op['verbatim_text'])
                      or (signature and signature==atom_signature(n['meta'].get('memory_atom'))))),None)
            if op['action']=='merge' and target is not None:
                same_verbatim=target['text']==op['verbatim_text']
                same_atom=bool(signature and signature==atom_signature(target['meta'].get('memory_atom')))
                incompatible=incompatible or not (same_verbatim or same_atom)
            review = op["requires_review"] or incompatible or bool(duplicate and protected(duplicate) and op['action']=='remember')
            if review:
                cid = "orgc_" + sha256(f"{plan['job_id']}:{index}".encode()).hexdigest()[:24]
                if len(candidates) >= 100:
                    raise OrganizerError("待审整理候选已满，原文仍保留", "candidate_capacity")
                candidates.append({"id": cid, "job_id": plan["job_id"], "library_id":library_id,"status": "pending", "operation": deepcopy(op),
                                   "reason": "存在不确定性、现实域/角色边界或受保护旧设定，需要审阅", "at": now()})
                result["candidates"].append(cid)
                continue
            if op["action"] == "relate":
                for other in op["related_ids"]:
                    if other != target["id"]:
                        brain.link(target["id"], other, .3)
                        touched.update((target["id"], other))
                        result["linked"].append([target["id"], other])
                continue
            if op["action"] == "merge" or duplicate:
                target = target if op["action"] == "merge" else duplicate
                touched.add(target["id"])
                evidence = target["meta"].setdefault("organizer_evidence", [])
                for e in op["evidence"]:
                    if e not in evidence:
                        evidence.append(deepcopy(e))
                sources=source_references(target['meta'].get('organizer_sources',[])+evidence)
                target['meta']['organizer_sources']=sources
                target["meta"]["organizer_evidence"] = evidence[-24:]
                if not isinstance(target['meta'].get('memory_atom'),dict):
                    target['meta']['memory_atom']=make_atom(op,target,library_id,sources)
                else:
                    target['meta']['memory_atom']['evidence']=deepcopy(sources)
                    target['meta']['memory_atom']['event_at']=evidence_event_at(sources)
                target['meta']['source_time_unknown']=target['meta']['memory_atom'].get('event_at') is None
                target["meta"]["organizer_aliases"] = list(dict.fromkeys(target["meta"].get("organizer_aliases", []) + op["aliases"]))[:16]
                for other in list(dict.fromkeys([e['id'] for e in op['evidence']]+op['related_ids']))[:12]:
                    if other!=target['id'] and brain._key(target['id'],other) not in brain.edges:
                        brain.link(target['id'],other,.35)
                        touched.add(other)
                        result['linked'].append([target['id'],other])
                result["merged"].append(target["id"])
                continue
            if op["action"] == "supersede" and target["meta"].get("organizer_key") != op["key"]:
                if len(candidates) >= 100:
                    raise OrganizerError("待审整理候选已满，原文仍保留", "candidate_capacity")
                cid = "orgc_" + sha256(f"{plan['job_id']}:{index}".encode()).hexdigest()[:24]
                candidates.append({"id": cid, "job_id": plan["job_id"], "library_id":library_id,"status": "pending", "operation": deepcopy(op), "reason": "新旧记忆属性不一致", "at": now()})
                result["candidates"].append(cid)
                continue
            # Capacity eviction must never remove raw evidence as a side effect of a derived fact.
            if brain.config.max_nodes is not None and len(brain.nodes) >= brain.config.max_nodes:
                raise OrganizerError("记忆容量不足，未驱逐原文；任务保留供重试", "memory_capacity")
            nid = "org_" + sha256(f"{plan['job_id']}:{index}".encode()).hexdigest()[:24]
            kind = "episode" if op.get("observation") else LAYERS[op["layer"]]
            metadata = {"source": "organizer", "confirmed": False, "important": False, "organizer_key": op["key"],
                        "organizer_layer": op["layer"], "organizer_summary": op["text"], "organizer_evidence": deepcopy(op["evidence"]),
                        "organizer_aliases": op["aliases"], "organizer_job": plan["job_id"], "domain": "real",
                        "organizer_sources":source_references(op['evidence'])}
            if op.get("observation"):
                metadata["organizer_layer"] = "experience"
                metadata["evidence_scope"] = "tool_observation"
                outcomes=op.get('observation_outcomes',['observed'])
                metadata['outcome']='failed' if 'failed' in outcomes else 'observed' if 'observed' in outcomes else 'success' 
            if kind == "commitment": metadata["status"] = "open"
            brain.add(op["layer"] + " · " + op["verbatim_text"][:60], op["verbatim_text"], kind=kind, id=nid, salience=.7, meta=metadata)
            brain.nodes[nid]['meta']['memory_atom']=make_atom(op,brain.nodes[nid],library_id)
            brain.nodes[nid]['meta']['source_time_unknown']=brain.nodes[nid]['meta']['memory_atom'].get('event_at') is None
            touched.add(nid)
            result["created"].append(nid)
            if op["action"] == "supersede":
                touched.add(target["id"])
                brain.supersede(target["id"], nid)
                if isinstance(target['meta'].get('memory_atom'),dict):target['meta']['memory_atom']['valid_to']=target['valid_to']
                result["superseded"].append(target["id"])
            for other in list(dict.fromkeys([e["id"] for e in op["evidence"]] + op["related_ids"]))[:8]:
                if other != nid:
                    brain.link(nid, other, .35)
                    touched.add(other)
        brain.meta["organizer_candidates"] = candidates
        changed_nodes = {i for i in before["nodes"].keys() | brain.nodes.keys() if before["nodes"].get(i) != brain.nodes.get(i)}
        changed_edges = {k for k in before["edges"].keys() | brain.edges.keys() if before["edges"].get(k) != brain.edges.get(k)}
        entry = {"job_id": plan["job_id"], "library_id":library_id,"rules_version": RULES_VERSION,"at": now(), "result": deepcopy(result), "rolled_back": False,
                 "before_nodes": {i: deepcopy(before["nodes"].get(i)) for i in changed_nodes},
                 "before_edges": {k: deepcopy(before["edges"].get(k)) for k in changed_edges},
                 "after_nodes": {i: fingerprint(brain.nodes[i]) for i in changed_nodes if i in brain.nodes},
                 "after_edges": {k: deepcopy(brain.edges.get(k)) for k in changed_edges}}
        brain.meta["organizer_log"] = (deepcopy(log) + [entry])[-20:]
        return result
    except Exception:
        for key, value in before.items(): setattr(brain, key, value)
        raise


def _usage_semantics(node):
    """Usage can survive undo only when it still refers to the same statement."""
    atom = node.get("meta", {}).get("memory_atom")
    atom = ({key: deepcopy(atom.get(key)) for key in ("subject", "predicate", "value", "qualifiers")}
            if isinstance(atom, dict) else None)
    return {"text": node.get("text"), "kind": node.get("kind"), "atom": atom}


def rollback(brain, job_id):
    entry = next((r for r in brain.meta.get("organizer_log", []) if r["job_id"] == job_id), None)
    if entry is None or entry.get("rolled_back"):
        raise OrganizerConflict("该整理任务不可回滚或已回滚")
    for nid, digest in entry["after_nodes"].items():
        if brain.get(nid) is None or fingerprint(brain.get(nid)) != digest:
            raise OrganizerConflict("整理结果之后已被修改，未覆盖后续变更")
    for key, edge in entry["after_edges"].items():
        if brain.edges.get(key) != edge: raise OrganizerConflict("关联在整理后已变化，未覆盖后续变更")
    candidates = brain.meta.get("organizer_candidates", [])
    if any(c["job_id"] == job_id and c["status"] != "pending" for c in candidates):
        raise OrganizerConflict("候选已被用户审阅，请单独处理后续结果")
    for nid, node in entry["before_nodes"].items():
        if node is None:
            brain.nodes.pop(nid, None); brain._vec.pop(nid, None)
        else:
            current = brain.nodes.get(nid)
            restored = deepcopy(node)
            if (current is not None and _usage_semantics(current) == _usage_semantics(node)
                    and isinstance(current.get("meta", {}).get("memory_usage"), dict)):
                # Fingerprints deliberately ignore real use metadata. Undoing an
                # organizer merge must not erase later use of that same fact.
                # A changed statement/atom keeps its original pre-job statistics;
                # heat from a different version is never transferred to it.
                restored.setdefault("meta", {})["memory_usage"] = deepcopy(current["meta"]["memory_usage"])
                for field in ("reinforced", "decay_at", "recalls"):
                    if field in current:restored[field] = deepcopy(current[field])
            brain.nodes[nid] = restored; brain._vec[nid] = brain._vec_for(restored)
    for key, edge in entry["before_edges"].items():
        if edge is None: brain.edges.pop(key, None)
        else: brain.edges[key] = deepcopy(edge)
    brain.meta["organizer_candidates"] = [c for c in candidates if c["job_id"] != job_id]
    entry["rolled_back"] = True
    return {"job_id": job_id, "rolled_back": True}


def review_candidate(brain, candidate_id, action):
    candidate = next((c for c in brain.meta.get("organizer_candidates", []) if c["id"] == candidate_id), None)
    if candidate is None or candidate["status"] != "pending" or action not in ("accept", "reject"):
        raise OrganizerError("候选或审阅动作不正确", "invalid_review")
    op = candidate["operation"]
    if action == "reject":
        candidate["status"] = "rejected"
        return {"id": candidate_id, "status": "rejected"}
    if op["layer"] == "persona":
        from ..companion import import_persona
        state = import_persona(brain, op["text"], {"origin": "organizer_user_review", "candidate_id": candidate_id})
        candidate["status"] = "accepted"
        return {"id": candidate_id, "status": "accepted", "persona_revision": state["revision"]}
    if op["domain"] != "real" or op.get("source_fiction") or not op["verbatim_text"]:
        raise OrganizerError("角色扮演/未知现实域或无用户证据不能作为现实事实采用", "unsafe_review")
    if brain.config.max_nodes is not None and len(brain.nodes) >= brain.config.max_nodes:
        raise OrganizerError("容量不足，未驱逐原文", "memory_capacity")
    metadata={"source":"user_confirmed","confirmed":True,"important":True,
              "organizer_candidate":candidate_id,"organizer_evidence":op['evidence'],
              "organizer_sources":source_references(op['evidence']),
              "organizer_layer":"experience" if op.get('observation') else op['layer']}
    if op.get('observation'):
        outcomes=op.get('observation_outcomes',['observed'])
        metadata.update(evidence_scope='tool_observation',outcome='failed' if 'failed' in outcomes else 'observed' if 'observed' in outcomes else 'success')
    nid = brain.add("用户审阅 · " + op["text"][:60],op['verbatim_text'] if op.get('observation') else op['text'],
                    kind='episode' if op.get('observation') else LAYERS[op['layer']],meta=metadata)
    library_id=next((entry.get('library_id') for entry in brain.meta.get('organizer_log',[]) if entry.get('job_id')==candidate['job_id']),None)
    # Candidate evidence/node IDs are local; the original plan's owning library is
    # retained on the candidate itself rather than inferred from an external ID.
    library_id=candidate.get('library_id',library_id or '')
    brain.nodes[nid]['meta']['memory_atom']=make_atom(op,brain.nodes[nid],library_id)
    brain.nodes[nid]['meta']['source_time_unknown']=brain.nodes[nid]['meta']['memory_atom'].get('event_at') is None
    candidate["status"] = "accepted"
    return {"id": candidate_id, "node_id": nid, "status": "accepted"}


def semantic_recall(brain, query, k=8, **kwargs):
    """Read-only semantic aliases supplement lexical retrieval, with explicit match provenance."""
    from ..companion.dedup import is_duplicate
    data = deepcopy(brain.to_dict())
    data["nodes"] = {nid:n for nid,n in data["nodes"].items() if not disabled(n) and not is_duplicate(n,brain)}
    data["edges"] = {key:e for key,e in data["edges"].items() if all(i in data["nodes"] for i in key.split("|",1))}
    brain = Brain(data)
    base = brain.recall(query, k=k, **kwargs)
    hits = {h["id"]: h for h in base["hits"]}
    expansions = []
    qv = brain.encoder(query)
    for node in brain.export()["nodes"]:
        metadata = node.get("meta", {})
        if metadata.get("source") != "organizer" or disabled(node) or not node.get("recoverable"):
            continue
        terms = [term for term in metadata.get("organizer_aliases", [])
                 if term in query or dice(set(qv), set(brain.encoder(term))) >= .35]
        if not terms: continue
        expanded = brain.recall(query + " " + node["label"] + " " + node["text"][:180], k=k, **kwargs)
        for h in expanded["hits"]:
            if h["id"] not in hits:
                hits[h["id"]] = {**h, "semantic_match": {"terms": terms, "memory_id": node["id"],
                                                        "evidence_ids": [e["id"] for e in metadata.get("organizer_evidence", [])]}}
        expansions.append({"memory_id": node["id"], "terms": terms})
        if len(expansions) >= 4: break
    selected = sorted(hits.values(), key=lambda h: -h["score"])[:k]
    for hit in selected:
        node = brain.get(hit["id"])
        metadata = node.get("meta", {})
        if metadata.get("source") == "organizer":
            hit["organizer"] = {"layer":metadata.get("organizer_layer"), "key":metadata.get("organizer_key"),
                                "evidence":deepcopy(metadata.get("organizer_evidence",[])),
                                "valid_from":node.get("valid_from"), "valid_to":node.get("valid_to"),
                                "current":node.get("valid_to") is None}
    return {**base, "hits": selected, "semantic_expansions": expansions}


def forget_plan_data(brain, raw_ids, node_ids=None):
    """Call in root's graph-forget transaction; these logs can contain copied before-images/quotes."""
    # A library privacy reset drops only organizer bookkeeping, never source/ordinary memory nodes.
    counts = {"logs":len(brain.meta.get("organizer_log",[])), "candidates":len(brain.meta.get("organizer_candidates",[]))}
    brain.meta["organizer_log"] = []
    brain.meta["organizer_candidates"] = []
    return counts
