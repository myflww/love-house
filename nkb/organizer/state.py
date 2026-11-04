"""Bounded prompt construction, evidence validation, transactional graph operations and undo."""
from copy import deepcopy
from hashlib import sha256
import json
import re

from ..core.brain import Brain
from ..errors import ValidationError
from ..retrieval.scoring import dice
from ..utils import now
from .config import get_profile, validate_profile
from .model import OrganizerConflict, OrganizerError
from .atoms import normalize_atom,make_atom,atom_signature,source_references,evidence_event_at
from .rules import RULES_VERSION, PERSONA_RULES_VERSION, SYSTEM_GUIDANCE, runtime_policy
from .experiences import normalize_episode,episode_key,episode_conflicts,make_experience,merge_experience,render_experience,SCHEMA as EXPERIENCE_SCHEMA
from ..retrieval.session import prepare_recall, PreparedRecall

LAYERS = {"fact": "fact", "preference": "preference", "experience": "episode", "commitment": "commitment", "persona": None}
ACTIONS = {"remember", "merge", "supersede", "relate", "candidate"}
RAW_SOURCES = {"conversation_turn", "tool_observation", "harness_recorded", "persona_import_source", "agent_output", "history_import"}
PERSONA_STATE_KEYS=('learned','formed_traits','enabled','learning_enabled','user_disabled',
                    'blocked_trait_ids','blocked_trait_evidence','learning_ignored_ids')
PERSONA_REJECTION_REASONS=frozenset(('schema','dimension','value','value_policy','evidence_schema',
    'evidence_count','evidence_role','evidence_id','evidence_quote','evidence_duplicate',
    'trait_collection','learning_disabled','evidence_source','evidence_quote_mismatch',
    'evidence_unavailable','evidence_truncated','evidence_current_batch','evidence_revalidation'))
PERSONA_RESULT_STATUSES=frozenset(('formed','partial','unchanged','empty','rejected','skipped','invalid'))
PERSONA_SKIP_REASONS=frozenset(('persona_disabled','learning_disabled','persona_revision_changed',
    'persona_evidence_changed','unchanged_or_suppressed','evidence_revalidation'))
HYPOTHETICAL = re.compile(r"假设|假如|如果|角色扮演|小说|想象|扮演|比如|例如|他说|她说|引用|骗你的|导入人格|人格设定")
RELATIONSHIP_ATTRIBUTE = re.compile(r"(?:^|[./:_-])(?:relationship|relation|bond|milestone|anniversary)(?:$|[./:_-])|关系状态|关系阶段|里程碑|纪念日|相识日", re.I)
TEMPORARY_REQUEST = re.compile(r"(?:这次|这一轮|本轮|本次|这条|这一条|当前)(?:[^。！？.!?\n]{0,24})(?:回答|回复|输出|用一句|说一句)|\b(?:for (?:this|the current) (?:reply|response|turn|task)|this (?:time|turn) only)\b", re.I)


def persona_result_view(result):
    """Safe aggregate for task status/errors, never model text or proof IDs."""
    if not isinstance(result,dict) or not isinstance(result.get('status'),str) or result['status'] not in PERSONA_RESULT_STATUSES:
        return None
    view={'status':result['status'],'changed':result.get('changed') is True}
    for key in ('accepted_count','applied_count','rejected_count'):
        value=result.get(key,0)
        view[key]=value if type(value) is int and 0<=value<=100000 else 0
    reasons=result.get('reasons',{})
    view['reasons']={key:value for key,value in reasons.items()
                     if key in PERSONA_REJECTION_REASONS and type(value) is int and 0<value<=100000} if isinstance(reasons,dict) else {}
    if isinstance(result.get('reason'),str) and result['reason'] in PERSONA_SKIP_REASONS:view['reason']=result['reason']
    if type(result.get('revision')) is int and result['revision']>=0:view['revision']=result['revision']
    return view


def _persona_summary(accepted, rejections, *, status=None):
    rejected=sum(rejections.values())
    return {'status':status or ('rejected' if rejected and not accepted else 'empty' if not accepted else 'unchanged'),
            'accepted_count':accepted,'applied_count':0,'rejected_count':rejected,'reasons':dict(rejections),'changed':False}


def relation_result_view(result):
    """Only counts and a fixed local reason; relationship suggestions may be private."""
    if not isinstance(result,dict):return None
    view={key:value for key in ('skipped_operations','ignored_links')
          if type(value:=result.get(key,0)) is int and 0<=value<=100000}
    if not any(view.values()):return None
    return {**view,'reason':'explicit_confirmation_required'}


def _skip_optional_relations(op,counts):
    """Presence in one batch or two valid quotes does not prove a relationship."""
    related=set(op.get('related_ids',[]))
    if op.get('action')=='relate':
        counts['skipped_operations']+=1
        counts['ignored_links']+=len(related-{op.get('target_id')})
        return True
    sources={e['id'] for e in op.get('evidence',[])}
    counts['ignored_links']+=len(related-sources-{op.get('target_id')})
    op['related_ids']=[]
    return False


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
        return {"user":node["text"],"assistant":metadata.get('assistant_reply','')}
    if source == "agent_output":
        return {"assistant":node["text"]}
    if source == 'history_import':
        messages=metadata.get('import_messages')
        if (metadata.get('speaker')=='assistant' and metadata.get('provenance')=='imported_record'
                and isinstance(messages,list) and messages and all(isinstance(m,dict) and m.get('role')=='assistant'
                    and isinstance(m.get('text'),str) for m in messages)):
            return {'assistant':node['text']}
        return {}
    return {"tool" if source == "tool_observation" else "assistant": node["text"]}


def _persona_roles(node):
    """Personality proof additionally rejects explicit role inconsistencies.

    Ordinary raw-output provenance remains source-owned: arbitrary speaker
    metadata must never turn historical assistant output into a user fact.
    """
    roles=_roles(node)
    meta=node.get('meta',{});source=meta.get('source')
    declared=meta.get('roles')
    conflict=(source=='agent_output' and meta.get('speaker') not in (None,'assistant')
              or source=='conversation_turn' and declared is not None
              and (not isinstance(declared,dict) or declared.get('assistant_reply','assistant')!='assistant'))
    if conflict:roles.pop('assistant',None)
    return roles


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
    if normalized.get("type") == "output":
        value=normalized.get("text")
        return {"assistant":value} if isinstance(value,str) else {}
    return {k: normalized[k] for k in ("user", "assistant") if isinstance(normalized.get(k), str)}


def context_input_bytes(profile):
    """Conservative input allowance only for a user-selected token window.

    UTF-8 bytes provide an upper-bound estimate, not a character/token identity.
    The default automatic window is left to the provider without local clipping.
    """
    context = profile.get('context_window',0)
    if not context:return None
    from .capabilities import effective_limits
    output = effective_limits(profile)['max_output_tokens']
    return max(0, context - output - len(SYSTEM_GUIDANCE.encode('utf-8')) - 1024)


def build_input(brain, library_id, items, profile, archives=None, *, purpose='memory'):
    available = context_input_bytes(profile)
    working_profile = profile
    for _ in range(32):
        payload, guards = _build_input(brain,library_id,items,working_profile,archives,purpose=purpose)
        if available is None:return payload,guards
        if not available:raise OrganizerError('所选上下文不足以容纳整理准则与输出预留，请提高上下文','input_budget')
        # Related recollections and older persona context are optional. Preserve
        # the current source text before spending this explicit input allowance.
        if len(json.dumps(payload,ensure_ascii=False).encode('utf-8')) > available:
            payload['related']=[];guards['existing_fingerprints']={}
            payload.pop('persona_context',None);guards['persona_fingerprints']={}
        encoded = len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))
        if encoded <= available:
            guards['input_char_budget']=profile['max_input_chars'] or len(json.dumps(payload,ensure_ascii=False))
            guards['context_input_bytes']=available
            return payload,guards
        longest = max((sum(len(text) for text in record['roles'].values()) for record in payload['raw']),default=0)
        previous = working_profile.get('_raw_slice_chars',longest)
        if previous <= 1:break
        # Rebuild from the same original cursors until the actual serialized
        # UTF-8 material fits. No cursor is committed by this read-only loop.
        working_profile={**profile,'_raw_slice_chars':max(1,min(previous-1,int(previous*available/encoded*.8)))}
    raise OrganizerError('所选上下文不足以容纳来源元数据，请提高上下文或减少每批条数','input_budget')


def _build_input(brain, library_id, items, profile, archives=None, *, purpose='memory'):
    """Selected unfinished sources and related memory; zero means full selected text."""
    from ..companion.dedup import is_duplicate,canonical_id
    budget = profile["max_input_chars"]
    full_selected = budget == 0
    records, progress, consumed, raw_hashes, aliases = [], {}, [], {}, []
    raw_budget = max(1200, int(budget * .65))
    each = max(300, raw_budget // max(1, len(items)) - 400)
    if '_raw_slice_chars' in profile:each=profile['_raw_slice_chars']
    for item in items:
        receipt_id = item["raw_id"]
        node = raw_node(brain, receipt_id)
        if node is None or disabled(node) or node.get("meta", {}).get("source") not in RAW_SOURCES:
            raise OrganizerError("待整理原文不存在或不是原始事件，未处理", "missing_raw")
        if node.get('meta',{}).get('library_id') not in (None,library_id):
            raise OrganizerError('待整理原文不属于当前存档','invalid_evidence')
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
        persona_right=True
        if purpose=='persona':
            graph_text=_persona_roles(node).get('assistant','')
            actual=roles.get('assistant','')
            # A persona profile must remain checkable in its live graph anchor.
            # Sample only the graph-backed original prefix, never an archive-only
            # continuation or a fabricated user/assistant pair.
            start=actual.find(graph_text) if graph_text else -1
            if start>=0:available=graph_text
            else:
                actual=actual.lstrip();start=0;length=0
                for left,right in zip(graph_text,actual):
                    if left!=right:break
                    length+=1
                available=graph_text[:length]
            persona_right=bool(available and start+len(available)>=len(actual))
            roles={'assistant':available}
        if node['meta']['source']=='agent_output' and set(roles)!={'assistant'}:
            raise OrganizerError('助手输出档案必须只有assistant原文，不能补入用户或工具角色','invalid_raw')
        if not roles or not any(isinstance(text,str) and text for text in roles.values()):
            raise OrganizerError("完整归档缺少角色原文，未假装完成整理", "missing_archive")
        if full_selected and '_raw_slice_chars' not in profile:
            # The batch is still bounded by its selected record count. Do not
            # fill the model window with unrelated records or silently retain
            # the former 18k/48k character ceiling for these selected sources.
            room = sum(len(text) for text in roles.values() if isinstance(text,str))
        for role, text in roles.items():
            offset = cursors.get(role, 0)
            if not isinstance(text, str):
                raise OrganizerError("原始角色文本格式不正确", "invalid_raw")
            piece = text[offset:offset + room]
            if piece:
                selected[role] = piece
                boundaries[role] = {"left":offset == 0 or text[offset-1] in "。！？!?；;\n",
                                    "right":(offset+len(piece) == len(text) and (purpose!='persona' or persona_right)) or piece[-1] in "。！？!?；;\n"}
                cursors[role] = offset + len(piece)
                room -= len(piece)
        records.append({"id": nid, "receipt_id": (evidence_meta.get('archive_receipt_id') if isinstance(evidence_meta,dict) else None) or receipt_id, "roles": selected, "boundaries":boundaries,
                        "created":node.get("created"),
                        "event_at":None if node.get("meta",{}).get("source_time_unknown") else node.get("event_at"),
                        "source_time_known":not bool(node.get("meta",{}).get("source_time_unknown")) and node.get("event_at") is not None,
                        "source_revision":fingerprint(node),
                        "source_recoverable":bool(brain._node_state(node,now()).get('recoverable')),
                        "recording_group":{"canonical_id":canonical_id(brain,node),
                            "capture_source_count":len(node.get('meta',{}).get('recording_sources',[]))},
                        "origin": node["meta"].get("origin", node["meta"]["source"]),
                        "source_kind": node["meta"]["source"],
                        "platform":(evidence_meta.get('platform') if isinstance(evidence_meta,dict) else None),
                        "outcome": node["meta"].get("outcome"), "source_url": str(node["meta"].get("source_url") or "")[:300],
                        "fiction_or_hypothesis_hint": bool(HYPOTHETICAL.search(roles.get("user", "") or
                            (roles.get('assistant','') if node['meta']['source']=='agent_output' else ''))),
                        "context_prefix": roles.get("user", "")[:160]})
        graph_assistant=_persona_roles(node).get('assistant','')
        records[-1]['persona_evidence_available']=bool(selected.get('assistant') and selected['assistant'] in graph_assistant
            and not node.get('superseded_by') and (node.get('valid_to') is None or node['valid_to']>now()))
        if isinstance(evidence_meta,dict) and evidence_meta.get('participant_scope')=='external_participant':
            records[-1]['participant_scope']='external_participant'
            participant=evidence_meta.get('participant_id')
            records[-1]['participant_id']=participant if isinstance(participant,str) and 0<len(participant)<=200 else 'unknown'
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
        entry={"id": node["id"], "kind": node["kind"], "text": node["text"][:900],
                        "key": node.get("meta", {}).get("organizer_key"), "protected": protected(node),
                        "atom":{k:deepcopy(node.get('meta',{}).get('memory_atom',{}).get(k)) for k in ('subject','predicate','value','qualifiers','layer')}}
        if isinstance(node.get('meta',{}).get('experience'),dict):
            entry['episode']={key:deepcopy(node['meta']['experience'].get(key)) for key in ('what','reason','outcome','event_at','status')}
        related.append(entry)
    payload = {"library_id": library_id, "memory_policy": runtime_policy(brain), "raw": records, "related": [] if purpose=='persona' else related}
    if purpose=='persona':payload['purpose']='persona'
    from ..companion.persona import persona_state
    persona=persona_state(brain,library_id=library_id)
    payload['memory_policy'].update(persona_learning=bool(persona['enabled'] and persona['learning_enabled']),
                                    persona_revision=persona['revision'],persona_rules_version=PERSONA_RULES_VERSION)
    while budget and related and len(json.dumps(payload, ensure_ascii=False)) > budget:
        related.pop()
    if budget and len(json.dumps(payload, ensure_ascii=False)) > budget:
        raise OrganizerError("本批输入超过预算，未发送", "input_budget")
    persona_fingerprints={}
    # Session cadence can have just one new turn. One older live assistant
    # record supplies personality context in this SAME request, never a second
    # fact source and never a re-run of completed ordinary queue items.
    if purpose=='memory' and payload['memory_policy']['persona_learning'] and sum(bool(r.get('persona_evidence_available')) for r in records)==1:
        current_ids={r['recording_group']['canonical_id'] for r in records}
        latest_current=max((r.get('created',0) for r in records),default=0)
        # Windows clocks can assign identical capture timestamps to adjacent
        # records. Preserve capture insertion order as the tie-breaker; a later
        # node cannot become an older persona source for the current batch.
        capture_order={nid:i for i,nid in enumerate(brain.nodes)}
        current_order=max((capture_order.get(cid,-1) for cid in current_ids),default=-1)
        tomb=brain.meta.get('memory_tombstones') or {}
        for node in reversed(brain.nodes.values()):
            meta=node.get('meta',{});cid=canonical_id(brain,node)
            body=_persona_roles(node).get('assistant','')
            if (cid in current_ids or disabled(node) or is_duplicate(node,brain)
                    or node.get('created',0)>latest_current
                    or node.get('created',0)==latest_current and capture_order[node['id']]>=current_order
                    or node.get('superseded_by') or node.get('valid_to') is not None and node['valid_to']<=now()
                    or meta.get('source') not in ('conversation_turn','agent_output','history_import')
                    or meta.get('library_id') not in (None,library_id)
                    or not body or node['id'] in tomb.get('node_ids',[])
                    or sha256(body.encode()).hexdigest() in tomb.get('text_hashes',[])
                    or not brain._node_state(node,now()).get('recoverable')):continue
            piece=body[:500]
            if len(body)>500:
                end=max((piece.rfind(c) for c in '。！？!?；;\n'),default=-1)
                if end<0:continue
                piece=piece[:end+1]
            proof=meta.get('evidence')
            context={'id':node['id'],'roles':{'assistant':piece},'source_kind':meta['source'],
                'source_recoverable':True,'persona_evidence_available':True,
                'boundaries':{'assistant':{'left':True,'right':len(piece)==len(body) and not (isinstance(proof,dict) and proof.get('content_truncated')) or piece[-1] in '。！？!?；;\n'}},
                'recording_group':{'canonical_id':cid},'receipt_id':proof.get('archive_receipt_id') if isinstance(proof,dict) else node['id']}
            payload['persona_context']=[context]
            if not budget or len(json.dumps(payload,ensure_ascii=False))<=budget:
                persona_fingerprints[node['id']]=fingerprint(node)
                break
            payload.pop('persona_context',None)
    return payload, {"raw_fingerprints": raw_hashes,
                     'input_char_budget':budget or len(json.dumps(payload,ensure_ascii=False)),
                     'persona_fingerprints':persona_fingerprints,
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


def _recorded_material(op, raw, *, reason):
    """Index a witnessed statement without deciding whether its claim is true.

    Uncertain content, imagined scenes and a speaker's later mistake remain
    searchable material. This conversion only creates a new literal record;
    it cannot change a previous fact, core persona or connection authority.
    """
    op['recorded_layer'] = op.get('recorded_layer', op['layer'])
    op['recorded_action'] = op.get('recorded_action', op['action'])
    op['action'], op['layer'], op['requires_review'] = 'remember', 'experience', False
    op.pop('target_id', None)
    op['related_ids'] = []
    op['attributed_material'] = True
    op['material_basis'] = reason
    roles = {e['role'] for e in op['evidence']}
    op['statement_attribution'] = next(iter(roles)) if len(roles) == 1 else 'mixed'
    op['statement_source_revisions'] = {e['id']: raw[e['id']]['source_revision'] for e in op['evidence']}
    op['source_excerpt'] = any(not e['complete_sentence'] for e in op['evidence'])
    # Full sentence contexts preserve negation, quotation and qualifiers. The
    # source/role stays alongside each quote; no model summary becomes a quote.
    op['verbatim_text'] = '\n'.join(dict.fromkeys(e['context'] for e in op['evidence']))
    op['text'] = op['verbatim_text']
    op['atom'] = None
    op['atom'] = normalize_atom(op)[0]
    subject = {'assistant':'agent', 'tool':'tool', 'user':'user'}.get(op['statement_attribution'], 'mixed')
    if subject=='user' and any(e.get('participant_scope')=='external_participant' for e in op['evidence']):
        subject='platform_participant'
    op['atom'].update(subject=subject,predicate='recorded_statement')
    # An actual tool response keeps its reported outcome even when the quoted
    # content is uncertain; recording it does not turn the response into truth.
    op['attributed_output_statement'] = False
    return op


def validate_plan(output, payload, guards, job_id, profile):
    if not isinstance(output, dict) or set(output) - {"version", "operations", "persona_traits"} or type(output.get("version")) is not int or output.get("version") != 1:
        raise OrganizerError("模型JSON顶层schema不合法", "invalid_output")
    operations = output.get("operations")
    if not isinstance(operations, list) or len(operations) > profile["max_ops"]:
        raise OrganizerError("模型操作数量不合法", "invalid_output")
    if payload.get('purpose')=='persona' and operations:
        raise OrganizerError('快速人格任务不能重写普通记忆','invalid_output')
    raw = {r["id"]: r for r in payload["raw"]}
    related = {r["id"] for r in payload["related"]}
    normalized = []
    relation_counts={'skipped_operations':0,'ignored_links':0}
    allowed = {"action", "layer", "key", "text", "evidence", "target_id", "aliases", "related_ids", "certainty", "domain", "atom", "episode"}
    for op in operations:
        if (not isinstance(op, dict) or set(op) - allowed or op.get("action") not in ACTIONS
                or op.get("layer") not in LAYERS):
            raise OrganizerError("模型操作schema不合法；不允许代码、删除或直接改原文", "invalid_output")
        op = deepcopy(op)
        # Direct Python callers may reuse the same reference dict in evidence
        # and episode fields; enrich evidence without mutating the model schema.
        if 'episode' in op:op['episode']=deepcopy(op['episode'])
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
            if record.get('participant_scope')=='external_participant':
                quote['participant_scope']='external_participant'
                quote['participant_id']=record.get('participant_id','unknown')
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
        episode=normalize_episode(op,raw)
        if episode is not None:op['episode']=episode
        if _skip_optional_relations(op,relation_counts):continue
        # This branch permits an observed autonomous episode to retain the
        # Agent's explicitly attributed reason without upgrading that reason
        # into a proven motive or a fact about its human owner.
        attributed_episode = bool(episode is not None and op['layer']=='experience'
            and episode['what']['role']=='tool'
            and episode['what'].get('claim_type')!='stated_intent'
            and raw[episode['what']['id']].get('outcome') in ('observed','success','failed')
            and (episode['outcome'] is None or episode['outcome']['role']=='tool'
                 and raw[episode['outcome']['id']].get('outcome') in ('observed','success','failed')))
        op['attributed_episode_observation']=attributed_episode
        attributed_statement=bool(op['action']=='remember' and op['layer']=='experience' and episode is None
            and op.get('atom') is None
            and all(e['role']=='assistant' and e['complete_sentence']
                    and raw[e['id']].get('source_kind')=='agent_output'
                    and raw[e['id']].get('source_time_known') and raw[e['id']].get('source_recoverable') for e in evidence))
        op['attributed_output_statement']=attributed_statement
        user_quotes = [e["context"] for e in evidence if e["role"] == "user"]
        tool_quotes = [e["quote"] for e in evidence if e["role"] == "tool"]
        observation = (not user_quotes and bool(tool_quotes) and op["layer"] in ("fact","experience")
                       and all(e["role"] == "tool" for e in evidence)
                       and all(raw[e["id"]].get("outcome") in ("observed","success","failed") for e in evidence))
        observation=observation or attributed_episode
        fiction = any(raw[e["id"]]["fiction_or_hypothesis_hint"] for e in evidence)
        op["requires_review"] = (op["action"] == "candidate" or op["layer"] == "persona"
                                  or bool(RELATIONSHIP_ATTRIBUTE.search(op["key"]))
                                  or op["certainty"] != "clear" or (not attributed_statement and (op["domain"] != "real" or fiction))
                                  or (not user_quotes and not observation and not attributed_statement)
                                  or (episode is not None and not attributed_episode)
                                  or any(not e["complete_sentence"] for e in evidence if e["role"] == "user")
                                  or len("\n".join(user_quotes)) > 2000)
        if op['layer']!='experience' and any(e.get('participant_scope')=='external_participant' for e in evidence):
            op['requires_review']=True
        if op['layer']=='preference' and any(TEMPORARY_REQUEST.search(value) for value in user_quotes):
            # A local instruction is a real utterance, but extracting it as a
            # lasting preference would lose its explicitly stated scope.
            op['requires_review']=True
        op["verbatim_text"] = "\n".join(dict.fromkeys(user_quotes))[:2000]
        if attributed_statement:
            statements='\n'.join(dict.fromkeys(e['context'] for e in evidence))
            if len(statements)>2000:op['requires_review']=True
            op['verbatim_text']=statements[:2000]
            op['statement_source_revisions']={e['id']:raw[e['id']]['source_revision'] for e in evidence}
        op["source_fiction"] = fiction
        op["observation"] = observation
        if observation:
            outcomes = list(dict.fromkeys(raw[e["id"]]["outcome"] for e in evidence if e['role']=='tool'))
            op['observation_outcomes']=outcomes
            op["verbatim_text"] = "工具观察（" + ",".join(outcomes) + "，不是用户确认事实）：\n" + "\n".join(dict.fromkeys(tool_quotes))[:1800]
        if episode is not None:
            if episode['time_status']=='conflicting':op['requires_review']=True
            if attributed_episode:
                op['verbatim_text']=render_experience({**episode,'schema':EXPERIENCE_SCHEMA})
        try:
            op['atom'],atom_review=normalize_atom(op)
        except OrganizerError as error:
            if error.code!='invalid_atom':raise
            # The optional machine extraction failed, not the already checked
            # source references. Retain only source-attributed literal material;
            # never keep an unsupported value, model summary, or target action.
            op.pop('atom',None)
            op.pop('target_id',None)
            op.update(action='candidate',aliases=[],related_ids=[],requires_review=True,
                      fallback_reason_code='invalid_atom_verbatim_fallback')
            op['atom']=normalize_atom(op)[0]
            op['verbatim_text']=op['atom']['value']
            op['text']=op['verbatim_text']
            op['fallback_source_fingerprints']={e['id']:guards['raw_fingerprints'][e['id']] for e in evidence}
            atom_review=True
        op['requires_review']=op['requires_review'] or atom_review
        protected_change = (op['layer']=='persona' or bool(RELATIONSHIP_ATTRIBUTE.search(op['key'])))
        source_available = all(raw[e['id']].get('source_recoverable') is True for e in evidence)
        # Review remains for changes to protected settings. Content uncertainty
        # alone is not permission to hide a real utterance from the memory index.
        # A failed optional atom also needs no human transcription: the checked
        # literal evidence is sufficient for a separate attributed record.
        if source_available and (op.get('fallback_reason_code')=='invalid_atom_verbatim_fallback'
                                 or op['requires_review'] and not protected_change):
            _recorded_material(op, raw, reason='literal_atom_fallback' if op.get('fallback_reason_code')
                               else 'attributed_source_statement')
        normalized.append(op)
    persona_raw={**raw,**{r['id']:r for r in payload.get('persona_context',[])}}
    traits=output.get('persona_traits',[])
    rejected={}
    def reject_trait(reason,count=1):
        reason=reason if isinstance(reason,str) and reason in PERSONA_REJECTION_REASONS else 'schema'
        rejected[reason]=rejected.get(reason,0)+count
    # Optional model material cannot invalidate otherwise valid factual work.
    # Invalid material is omitted from the cached plan, retaining only counts.
    if not isinstance(traits,list) or len(traits)>8:
        reject_trait('trait_collection',len(traits) if isinstance(traits,list) else 1)
        traits=[]
    if traits and not payload.get('memory_policy',{}).get('persona_learning'):
        reject_trait('learning_disabled',len(traits));traits=[]
    from ..companion.persona import normalize_persona_trait
    checked_traits=[]
    for trait in traits:
        try:trait=normalize_persona_trait(trait)
        except ValidationError as error:
            reject_trait(getattr(error,'persona_trait_reason','schema'));continue
        independent=set()
        reason=None
        for evidence in trait['evidence']:
            record=persona_raw.get(evidence['id'])
            if record is None or record.get('source_kind') not in ('conversation_turn','agent_output','history_import'):
                reason='evidence_source';break
            if evidence['quote'] not in record.get('roles',{}).get('assistant',''):
                reason='evidence_quote_mismatch';break
            if not record.get('source_recoverable') or not record.get('persona_evidence_available'):
                reason='evidence_unavailable';break
            if not _sentence(record,'assistant',evidence['quote'])[1]:
                reason='evidence_truncated';break
            independent.add(record.get('recording_group',{}).get('canonical_id') or evidence['id'])
        if not reason and len(independent)<2:reason='evidence_duplicate'
        if not reason and not any(e['id'] in raw for e in trait['evidence']):reason='evidence_current_batch'
        if reason:
            reject_trait(reason);continue
        checked_traits.append(trait)
    persona_validation=_persona_summary(len(checked_traits),rejected)
    if payload.get('purpose')=='persona' and rejected and not checked_traits:
        error=OrganizerError('人格特征均未通过校验，未形成人格；原文仍保留，请检查资料后明确重试','invalid_persona_traits')
        error.persona_result={**persona_validation,'status':'invalid'}
        raise error
    return {"version": 1, "rules_version": RULES_VERSION, "job_id": job_id, "library_id": payload["library_id"],
            "profile": deepcopy(profile), "operations": normalized, 'persona_traits':checked_traits,
            'persona_validation':persona_validation,
            'relation_policy':'explicit-only/v1','relation_counts':relation_counts,
            'persona_revision':payload.get('memory_policy',{}).get('persona_revision'),
            'persona_rules_version':PERSONA_RULES_VERSION,'purpose':payload.get('purpose','memory'), **deepcopy(guards)}


def _check(brain, plan, library_id):
    if plan.get("library_id") != library_id:
        raise OrganizerConflict("整理结果属于另一个库，未应用")
    if plan.get("rules_version") != RULES_VERSION:
        raise OrganizerConflict("整理准则已更新，旧缓存结果需按当前规则重新校验")
    if (plan.get('persona_traits') or plan.get('purpose')=='persona') and plan.get('persona_rules_version')!=PERSONA_RULES_VERSION:
        raise OrganizerConflict('人格准则已更新，未应用旧人格计划')
    if plan.get('purpose')=='persona' and plan.get('operations'):
        raise OrganizerConflict('快速人格计划不能修改普通记忆')
    saved_profile=plan.get('profile')
    if not isinstance(saved_profile,dict):raise OrganizerConflict('整理配置指纹不合法，未应用旧结果')
    saved_profile=deepcopy(saved_profile)
    # Normalize only retired defaults, using exactly the same legacy rule as
    # get_profile. A valid cached plan must not buy another model call merely
    # because upgrade removed daily ceilings or added automatic capabilities.
    if not any(key in saved_profile for key in ('context_window','max_output_tokens','reasoning_effort')) and saved_profile.get('max_input_chars')==18000:
        saved_profile['max_input_chars']=0
    try:saved_profile=validate_profile(saved_profile)
    except ValidationError:raise OrganizerConflict('整理配置指纹不合法，未应用旧结果') from None
    if get_profile(brain) != saved_profile or not get_profile(brain)["enabled"]:
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
    relation_counts={key:0 for key in ('skipped_operations','ignored_links')}
    # New plans already stripped suggestions; old cached plans must pass the
    # same gate here without discarding legal facts or making another API call.
    checked_relations=relation_result_view(plan.get('relation_counts'))
    if checked_relations:
        for key in relation_counts:relation_counts[key]=checked_relations.get(key,0)
    candidates = deepcopy(brain.meta.get("organizer_candidates", []))
    touched = set()
    try:
        for index, original in enumerate(plan["operations"]):
            op=deepcopy(original)
            if _skip_optional_relations(op,relation_counts):continue
            if 'atom' not in op:op['atom']=normalize_atom(op)[0]
            target = brain.get(op.get("target_id", ""))
            expected_layer = "experience" if op.get("observation") else op["layer"]
            incompatible = (target is not None and op["action"] in ("merge","supersede")
                            and (protected(target) or target["meta"].get("organizer_key") != op["key"]
                                 or target["meta"].get("organizer_layer") != expected_layer))
            incoming_atom={**op['atom'],'layer':expected_layer}
            signature=atom_signature(incoming_atom)
            incoming_episode=op.get('episode')
            statement_record=bool(op.get('attributed_material') or op.get('attributed_output_statement'))
            def same_statement_source(node):
                if not statement_record:return True
                meta=node.get('meta',{})
                if not (meta.get('attributed_material') or meta.get('statement_attribution')=='assistant'):return False
                refs=lambda values:{(e.get('id'),e.get('role'),e.get('context',e.get('quote')))
                                    for e in values if isinstance(e,dict)}
                return (refs(meta.get('organizer_evidence',[]))==refs(op['evidence'])
                        and meta.get('statement_source_revisions')==op.get('statement_source_revisions'))
            duplicate=next((n for n in brain.nodes.values()
                 if n.get('meta',{}).get('source')=='organizer' and not disabled(n) and n.get('valid_to') is None
                 and same_statement_source(n)
                 and n['meta'].get('organizer_layer')==expected_layer
                 and ((bool(incoming_episode) and episode_key(incoming_episode)==episode_key(n['meta'].get('experience')))
                      or (not incoming_episode and not n['meta'].get('experience')
                          and ((n['meta'].get('organizer_key')==op['key'] and n['text']==op['verbatim_text'])
                               or (signature and signature==atom_signature(n['meta'].get('memory_atom'))))))),None)
            if op['action']=='merge' and target is not None:
                same_verbatim=target['text']==op['verbatim_text']
                same_atom=bool(signature and signature==atom_signature(target['meta'].get('memory_atom')))
                if incoming_episode or target['meta'].get('experience'):
                    incompatible=incompatible or episode_conflicts(target['meta'].get('experience'),incoming_episode)
                else:incompatible=incompatible or not (same_verbatim or same_atom)
            review = op["requires_review"] or incompatible or bool(duplicate and protected(duplicate) and op['action']=='remember')
            if incoming_episode and duplicate and episode_conflicts(duplicate['meta'].get('experience'),incoming_episode):review=True
            # A proposed merge may conflict only after comparison with the live
            # target. Keep that new statement separately rather than asking a
            # person to adjudicate which ordinary memory is true. Protected
            # settings still follow their explicit user-choice path.
            if (review and not op['requires_review'] and op['layer']!='persona'
                    and not RELATIONSHIP_ATTRIBUTE.search(op['key'])
                    and not (target is not None and protected(target))
                    and not (duplicate is not None and protected(duplicate))
                    and all(brain._node_state(brain.get(e['id']),now()).get('recoverable')
                            for e in op['evidence'])):
                sources={e['id']:{'source_revision':plan['raw_fingerprints'][e['id']]} for e in op['evidence']}
                _recorded_material(op,sources,reason='incompatible_source_statements')
                target=duplicate=None
                incoming_episode=op.get('episode')
                review=False
            if review:
                cid = "orgc_" + sha256(f"{plan['job_id']}:{index}".encode()).hexdigest()[:24]
                # Review protects explicit settings and unavailable evidence.
                # An accumulated backlog must not roll back unrelated valid work
                # or leave this validated batch retrying the same plan forever.
                candidate={"id": cid, "job_id": plan["job_id"], "library_id":library_id,"status": "pending", "operation": deepcopy(op),
                           "reason": "涉及受保护设定，或来源当前不可用，需要检查", "at": now()}
                if op.get('fallback_reason_code')=='invalid_atom_verbatim_fallback':
                    candidate.update(reason='机器记录未通过校验，仅保留已核对原文供审阅',reason_code='invalid_atom_verbatim_fallback')
                candidates.append(candidate)
                result["candidates"].append(cid)
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
                if op.get('statement_source_revisions'):
                    target['meta'].setdefault('statement_source_revisions',{}).update(op['statement_source_revisions'])
                target["meta"]["organizer_evidence"] = evidence[-24:]
                if not isinstance(target['meta'].get('memory_atom'),dict):
                    target['meta']['memory_atom']=make_atom(op,target,library_id,sources)
                else:
                    target['meta']['memory_atom']['evidence']=deepcopy(sources)
                    target['meta']['memory_atom']['event_at']=evidence_event_at(sources)
                target['meta']['source_time_unknown']=target['meta']['memory_atom'].get('event_at') is None
                if incoming_episode:
                    target['meta']['experience']=merge_experience(target['meta'].get('experience'),make_experience(op,target,library_id))
                target["meta"]["organizer_aliases"] = list(dict.fromkeys(target["meta"].get("organizer_aliases", []) + op["aliases"]))[:16]
                for other in list(dict.fromkeys(e['id'] for e in op['evidence']))[:12]:
                    if other!=target['id'] and brain._key(target['id'],other) not in brain.edges:
                        brain.link(target['id'],other,.35)
                        touched.add(other)
                        result['linked'].append([target['id'],other])
                result["merged"].append(target["id"])
                continue
            if op["action"] == "supersede" and target["meta"].get("organizer_key") != op["key"]:
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
                        "organizer_aliases": op["aliases"], "organizer_job": plan["job_id"], "domain": op['domain'],
                        "organizer_sources":source_references(op['evidence'])}
            if op.get('attributed_material'):
                metadata.update(attributed_material=True,statement_attribution=op['statement_attribution'],
                    statement_source_revisions=deepcopy(op['statement_source_revisions']),
                    certainty=op['certainty'],recorded_layer=op['recorded_layer'],
                    material_basis=op['material_basis'],source_excerpt=op['source_excerpt'])
            if op.get('attributed_output_statement'):
                metadata.update(statement_attribution='assistant',domain=op['domain'],statement_source_revisions=deepcopy(op['statement_source_revisions']))
            if op.get("observation"):
                metadata["organizer_layer"] = "experience"
                metadata["evidence_scope"] = "tool_observation"
                outcomes=op.get('observation_outcomes',['observed'])
                metadata['outcome']='failed' if 'failed' in outcomes else 'observed' if 'observed' in outcomes else 'success' 
            if kind == "commitment": metadata["status"] = "open"
            brain.add(op["layer"] + " · " + op["verbatim_text"][:60], op["verbatim_text"], kind=kind, id=nid, salience=.7, meta=metadata)
            brain.nodes[nid]['meta']['memory_atom']=make_atom(op,brain.nodes[nid],library_id)
            brain.nodes[nid]['meta']['source_time_unknown']=brain.nodes[nid]['meta']['memory_atom'].get('event_at') is None
            if incoming_episode:brain.nodes[nid]['meta']['experience']=make_experience(op,brain.nodes[nid],library_id)
            touched.add(nid)
            result["created"].append(nid)
            if op["action"] == "supersede":
                touched.add(target["id"])
                brain.supersede(target["id"], nid)
                if isinstance(target['meta'].get('memory_atom'),dict):target['meta']['memory_atom']['valid_to']=target['valid_to']
                result["superseded"].append(target["id"])
            for other in list(dict.fromkeys(e["id"] for e in op["evidence"]))[:8]:
                if other != nid:
                    brain.link(nid, other, .35)
                    touched.add(other)
        brain.meta["organizer_candidates"] = candidates
        if any(relation_counts.values()):result['relations']=relation_result_view(relation_counts)
        persona_before=None
        if 'persona_validation' in plan or plan.get('persona_traits') or plan.get('purpose')=='persona':
            validation=persona_result_view(plan.get('persona_validation')) or _persona_summary(len(plan.get('persona_traits',[])),{})
            result['persona']={**validation,'accepted_count':len(plan.get('persona_traits',[])),
                               'applied_count':0,'changed':False}
        if plan.get('persona_traits'):
            from ..companion.persona import apply_learned_traits,PersonaConflict,_state as persona_record_state
            persona_before={key:deepcopy(value) for key,value in persona_record_state(brain).items() if key in PERSONA_STATE_KEYS}
            context_changed=False
            try:
                for nid,digest in plan.get('persona_fingerprints',{}).items():
                    node=brain.get(nid)
                    if (node is None or disabled(node) or fingerprint(node)!=digest
                            or not brain._node_state(node,now()).get('recoverable')
                            or node.get('valid_to') is not None and node['valid_to']<=now()):
                        context_changed=True
                        raise PersonaConflict('补充人格依据已变化，未应用旧人格资料')
                learned=apply_learned_traits(brain,plan['persona_traits'],
                    source={'origin':'organizer_persona','job_id':plan['job_id']},
                    expected_revision=plan.get('persona_revision'),library_id=library_id)
                result['persona'].update(learned)
                result['persona']['applied_count']=len(learned.get('applied_ids',[]))
                result['persona']['status']=('partial' if result['persona']['rejected_count'] else 'formed') if learned.get('changed') else (
                    'skipped' if learned.get('reason') in ('persona_disabled','learning_disabled','persona_revision_changed') else 'unchanged')
            except PersonaConflict:
                result['persona'].update(status='skipped',changed=False,
                    reason='persona_evidence_changed' if context_changed else 'persona_revision_changed')
            except ValidationError:
                # Live proof is rechecked by the helper. Rejecting this optional
                # component must not roll back valid, independent factual work.
                reasons={**result['persona']['reasons'],'evidence_revalidation':len(plan['persona_traits'])}
                result['persona']=_persona_summary(0,reasons,status='rejected')
                result['persona']['reason']='evidence_revalidation'
        changed_nodes = {i for i in before["nodes"].keys() | brain.nodes.keys() if before["nodes"].get(i) != brain.nodes.get(i)}
        changed_edges = {k for k in before["edges"].keys() | brain.edges.keys() if before["edges"].get(k) != brain.edges.get(k)}
        entry = {"job_id": plan["job_id"], "library_id":library_id,"rules_version": RULES_VERSION,"at": now(), "result": deepcopy(result), "rolled_back": False,
                 "before_nodes": {i: deepcopy(before["nodes"].get(i)) for i in changed_nodes},
                 "before_edges": {k: deepcopy(before["edges"].get(k)) for k in changed_edges},
                 "after_nodes": {i: fingerprint(brain.nodes[i]) for i in changed_nodes if i in brain.nodes},
                 "after_edges": {k: deepcopy(brain.edges.get(k)) for k in changed_edges}}
        if result.get('persona',{}).get('changed'):
            entry['before_persona']=deepcopy(persona_before)
            entry['after_persona_hash']=sha256(json.dumps(brain.meta.get('companion_persona'),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
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
    return {"text": node.get("text"), "kind": node.get("kind"), "atom": atom,
            "experience":deepcopy(node.get('meta',{}).get('experience'))}


def rollback(brain, job_id):
    entry = next((r for r in brain.meta.get("organizer_log", []) if r["job_id"] == job_id), None)
    if entry is None or entry.get("rolled_back"):
        raise OrganizerConflict("该整理任务不可回滚或已回滚")
    if 'after_persona_hash' in entry:
        current_hash=sha256(json.dumps(brain.meta.get('companion_persona'),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if current_hash!=entry['after_persona_hash']:
            raise OrganizerConflict('人格在整理后已有新变化，未覆盖后续选择')
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
    if 'after_persona_hash' in entry:
        # Undo is a NEW user choice, not an ABA reset to an old revision number.
        # Keep the monotonic revision/history and current manual text while
        # restoring only the learned state which this organizer job changed.
        from ..companion.persona import _state as persona_record_state,_commit as persona_record_commit
        from ..companion.memory import get_profile as persona_profile
        current=persona_record_state(brain);old=entry['before_persona']
        for key in PERSONA_STATE_KEYS:
            current[key]=deepcopy(old[key])
        persona_record_commit(brain,current,persona_profile(brain),raw_text='',
            source={'origin':'organizer_undo','job_id':job_id},explicit=True)
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
    if op.get('action')=='relate':
        raise OrganizerError('自动关联建议不能作为事实采用；请查看两端内容后使用明确的手工连接','manual_relation_required')
    atom_fallback=op.get('fallback_reason_code')=='invalid_atom_verbatim_fallback'
    if atom_fallback:
        # A reviewed fallback creates a literal source record only. It cannot
        # restore an earlier merge/relate/supersede or import a persona summary.
        revisions=op.get('fallback_source_fingerprints',{})
        if not revisions or any(brain.get(nid) is None or disabled(brain.get(nid))
                                or fingerprint(brain.get(nid))!=revision for nid,revision in revisions.items()):
            raise OrganizerConflict('候选来源已改变，未采用旧的逐字回退')
    if op["layer"] == "persona" and not atom_fallback:
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
              "organizer_layer":"experience" if op.get('observation') or atom_fallback and op['layer']=='persona' else op['layer']}
    if atom_fallback:metadata['organizer_fallback_reason_code']='invalid_atom_verbatim_fallback'
    if op.get('observation'):
        outcomes=op.get('observation_outcomes',['observed'])
        metadata.update(evidence_scope='tool_observation',outcome='failed' if 'failed' in outcomes else 'observed' if 'observed' in outcomes else 'success')
    nid = brain.add("用户审阅 · " + op["text"][:60],op['verbatim_text'] if op.get('observation') or atom_fallback else op['text'],
                    kind='episode' if op.get('observation') or atom_fallback and op['layer']=='persona' else LAYERS[op['layer']],meta=metadata)
    library_id=next((entry.get('library_id') for entry in brain.meta.get('organizer_log',[]) if entry.get('job_id')==candidate['job_id']),None)
    # Candidate evidence/node IDs are local; the original plan's owning library is
    # retained on the candidate itself rather than inferred from an external ID.
    library_id=candidate.get('library_id',library_id or '')
    brain.nodes[nid]['meta']['memory_atom']=make_atom(op,brain.nodes[nid],library_id)
    brain.nodes[nid]['meta']['source_time_unknown']=brain.nodes[nid]['meta']['memory_atom'].get('event_at') is None
    if op.get('episode'):brain.nodes[nid]['meta']['experience']=make_experience(op,brain.nodes[nid],library_id)
    candidate["status"] = "accepted"
    return {"id": candidate_id, "node_id": nid, "status": "accepted"}


def semantic_recall(brain, query, k=8, *, prepared=None, **kwargs):
    """Scoped read-only retrieval with conservative time cues and alias evidence.

    A prepared object may be shared by the two lanes of one context request.
    Every call rechecks live eligibility and encoding inputs; it never caches a
    previous response or treats time words as permission to recover old facts.
    """
    from ..retrieval.query import plan_query, topic_alias_match, source_event_time
    if not isinstance(query, str) or not query.strip():
        raise ValidationError('查询内容不能为空')
    if prepared is not None and (not isinstance(prepared, PreparedRecall) or prepared.brain is not brain):
        raise ValidationError('召回准备资料不属于当前记忆库')
    prepared = prepared or prepare_recall(brain)
    stamp = now() if kwargs.get('as_of') is None else kwargs['as_of']
    # Keep the core's validation of explicit timestamps, including bool/NaN.
    stamp = brain._number(stamp, 'as_of')
    plan = plan_query(query, stamp)
    candidates = kwargs.pop('candidate_ids', None)
    if candidates is not None and (not isinstance(candidates, (set, frozenset, list, tuple))
                                   or any(not isinstance(i, str) for i in candidates)):
        raise ValidationError('candidate_ids必须是本图节点ID集合')
    if plan.needs_clarification or plan.invalid_date:
        return {'query': query, 'hits': [], 'steps': kwargs.get('steps', brain.config.steps),
                'seeds': [], 'trail': [], 'visited': 0, 'semantic_expansions': [],
                'query_understanding': plan.public(),
                'note': '请补充要回忆的话题或有效日期，未猜测你指的是哪段经历'}
    view, selected_ids = prepared.view(candidates, plan=plan)
    options = {**kwargs, 'as_of': stamp, 'candidate_ids': selected_ids}
    search = plan.search
    count = max(k, k * 3) if plan.intent in ('recent', 'historical') else k
    base = view.recall(search, k=count, **options)
    base['query'] = query
    hits = {h["id"]: h for h in base["hits"]}
    matches = []
    qv = set(brain.encoder(search.casefold()))
    for nid in selected_ids:
        node = brain.get(nid)
        metadata = node.get("meta", {})
        if metadata.get('source') != 'organizer' or not view._node_state(view.get(nid), stamp)['recoverable']:
            continue
        aliases = metadata.get('organizer_aliases', [])
        aliases = aliases if isinstance(aliases, list) else []
        terms, weight = [], 0.0
        for term in aliases:
            if not isinstance(term, str) or not term.strip():
                continue
            exact = term.casefold() in search.casefold()
            score = 1.0 if exact else max(.8 if topic_alias_match(search, term) else 0,
                                         dice(qv, set(brain.encoder(term.casefold()))))
            if exact or score >= .35:
                terms.append(term)
                weight = max(weight, score)
        if terms:
            matches.append((weight, nid, terms))
    # Strongest alias evidence wins over graph insertion order. Combining at
    # most four matching aliases needs one extra recall, rather than four full
    # graph copies/exports/scans. This is a query budget, never a storage limit.
    matches.sort(key=lambda item: (-item[0], item[1]))
    expansions = [{'memory_id': nid, 'terms': terms} for _, nid, terms in matches[:4]]
    if expansions:
        material = ' '.join(brain.get(item['memory_id'])['label'] + ' ' + brain.get(item['memory_id'])['text'][:180]
                            for item in expansions)
        expanded = view.recall(search + ' ' + material, k=count, **options)
        for h in expanded["hits"]:
            if h["id"] not in hits:
                match = next((item for item in expansions if item['memory_id'] in h.get('path', [])), None)
                match = match or next((item for item in expansions if item['memory_id'] == h['id']), expansions[0])
                metadata = brain.get(match['memory_id']).get('meta', {})
                hits[h["id"]] = {**h, 'semantic_match': {**match,
                    'evidence_ids': [e['id'] for e in metadata.get('organizer_evidence', []) if isinstance(e, dict) and isinstance(e.get('id'), str)]}}
    def rank(hit):
        node = brain.get(hit['id'])
        event = source_event_time(node)
        known = (type(event) in (int, float) and 0 <= event <= stamp
                 and not node.get('meta', {}).get('source_time_unknown'))
        bonus = 0.0
        if known and plan.intent in ('recent', 'historical'):
            age = max(0, stamp - event) / 86400
            recent = 1 / (1 + age / 7)
            bonus = .12 * (recent if plan.intent == 'recent' else 1 - recent)
            hit['temporal_match'] = {'intent': plan.intent, 'event_at': event, 'ranking_only': True}
        return (-hit['score'] - bonus, -hit['score'])
    selected = sorted(hits.values(), key=rank)[:k]
    for hit in selected:
        node = brain.get(hit["id"])
        metadata = node.get("meta", {})
        if metadata.get("source") == "organizer":
            hit["organizer"] = {"layer":metadata.get("organizer_layer"), "key":metadata.get("organizer_key"),
                                "evidence":deepcopy(metadata.get("organizer_evidence",[])),
                                "valid_from":node.get("valid_from"), "valid_to":node.get("valid_to"),
                                "current":node.get("valid_to") is None}
    return {**base, "hits": selected, "semantic_expansions": expansions, 'query_understanding': plan.public()}


def forget_plan_data(brain, raw_ids, node_ids=None):
    """Call in root's graph-forget transaction; these logs can contain copied before-images/quotes."""
    # A library privacy reset drops only organizer bookkeeping, never source/ordinary memory nodes.
    counts = {"logs":len(brain.meta.get("organizer_log",[])), "candidates":len(brain.meta.get("organizer_candidates",[]))}
    brain.meta["organizer_log"] = []
    brain.meta["organizer_candidates"] = []
    return counts
