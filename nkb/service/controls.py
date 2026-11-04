"""Explicit user control over active memories without rewriting historical speech."""
from copy import deepcopy
from hashlib import sha256
import json
import time
from ..errors import ValidationError

def refs(node):
    m=node.get('meta',{})
    values=set(m.get('members',[]))
    values.update(e.get('id') for e in m.get('organizer_evidence',[]) if isinstance(e,dict) and isinstance(e.get('id'),str))
    atom=m.get('memory_atom') if isinstance(m.get('memory_atom'),dict) else {}
    sources=m.get('organizer_sources') if isinstance(m.get('organizer_sources'),list) else []
    values.update(e.get('id') for e in [*sources,*(atom.get('evidence') or [])] if isinstance(e,dict) and isinstance(e.get('id'),str))
    values.update(m.get('source_ids',[]))
    if m.get('corrects'):values.add(m['corrects'])
    return values

def related(brain,ids,include_sources=False):
    ids=set(ids)
    # Expand sources only from the explicitly selected target. A downstream
    # summary may also cite independent B; forgetting A must not erase B.
    if include_sources:
        sources=set(ids)
        while True:
            old=set(sources)
            for nid in old:
                if nid in brain.nodes:sources.update(refs(brain.nodes[nid]))
            sources.intersection_update(brain.nodes)
            if sources==old:break
        ids=sources
    while True:
        old=set(ids)
        for nid,n in brain.nodes.items():
            if refs(n)&ids:ids.add(nid)
        ids.intersection_update(brain.nodes)
        if ids==old:return ids

def set_enabled(brain,nid,enabled):
    if type(enabled) is not bool:raise ValidationError('enabled必须是布尔值')
    if nid not in brain.nodes:raise ValidationError('记忆不存在')
    ids=related(brain,[nid])
    for i in ids:
        brain.nodes[i]['meta'].update(memory_disabled=not enabled,
            memory_disabled_origin='explicit_user_action',memory_enabled_changed_at=time.time())
    rebuild_source_controls(brain,changed=True)
    return {'id':nid,'enabled':enabled,'affected_ids':sorted(ids)}


def rebuild_source_controls(brain,*,changed=False):
    """Rebuild after opaque edits/imports under the graph write transaction.

    The map is only an index of user controls, never a source of permission.
    Readers still check each indexed blocker against its live disabled state.
    Explicit control/opaque edits invalidate cursors even for a raw source with
    no derived blockers; an unchanged startup rebuild stays idempotent.
    """
    mapping={}
    for nid,node in brain.nodes.items():
        meta=node.get('meta',{})
        if not meta.get('memory_disabled'):continue
        atom=meta.get('memory_atom') if isinstance(meta.get('memory_atom'),dict) else {}
        for collection in (meta.get('organizer_evidence'),meta.get('organizer_sources'),atom.get('evidence')):
            if isinstance(collection,list):
                for item in collection:
                    if isinstance(item,dict) and isinstance(item.get('id'),str):
                        mapping.setdefault(item['id'],set()).add(nid)
    previous=brain.meta.get('memory_source_controls',{})
    generation=previous.get('generation',0) if isinstance(previous,dict) else 0
    blocked_by={nid:sorted(ids) for nid,ids in mapping.items()}
    unchanged=(isinstance(previous,dict) and previous.get('schema')=='love-house-source-controls/v1'
               and previous.get('blocked_by')==blocked_by and type(generation) is int and generation>=1)
    value={'schema':'love-house-source-controls/v1','generation':generation+1 if type(generation) is int else 1,
           'blocked_by':blocked_by}
    if unchanged and not changed:value['generation']=generation
    brain.meta['memory_source_controls']=value
    return {'schema':value['schema'],'generation':value['generation'],'blocked_sources':len(mapping)}


def _refresh_unchanged_source_guards(brain,previous):
    """Advance exact guards across our metadata-only history attribution.

    A literal record whose guard already failed (edited text/provenance) stays
    unavailable. This never grants permission or adopts a model interpretation.
    """
    from ..organizer.state import fingerprint
    current={nid:fingerprint(brain.nodes[nid]) for nid in previous if nid in brain.nodes}
    for node in brain.nodes.values():
        meta=node.get('meta',{});guards=meta.get('statement_source_revisions')
        if meta.get('source')!='organizer' or not isinstance(guards,dict):continue
        for nid,guarded_revision in tuple(guards.items()):
            if nid in previous and guarded_revision==previous[nid] and nid in current:guards[nid]=current[nid]


def history_restore_preview(brain,nid):
    """Legacy flags have no provenance: show exact scope before a user restores."""
    if nid not in brain.nodes:raise ValidationError('记忆不存在')
    from ..companion.versions import RevisionIndex
    from ..organizer.state import fingerprint,RAW_SOURCES
    chain=RevisionIndex(brain).related([nid])
    proof=[]
    for old_id in chain:
        old=brain.nodes[old_id];new=brain.get(old.get('superseded_by'))
        if (new and new.get('meta',{}).get('corrects')==old_id
                and new.get('meta',{}).get('source')=='user_confirmed'
                and new.get('meta',{}).get('corrected_at')==old.get('valid_to')):
            proof.append(old_id)
    relevant=related(brain,proof) if proof else set()
    # Only earlier dependents could have been affected by the legacy action.
    latest=max((brain.nodes[i].get('valid_to') or 0 for i in proof),default=0)
    relevant={i for i in relevant if brain.nodes[i].get('created',0)<=latest}
    for target in list(relevant):
        relevant.update(ref for ref in refs(brain.nodes[target]) if ref in brain.nodes
                        and brain.nodes[ref].get('meta',{}).get('source') in RAW_SOURCES)
    tomb=set(brain.meta.get('memory_tombstones',{}).get('node_ids',[]))
    library=brain.meta.get('library_id')
    selected=[]
    for target in sorted(relevant):
        node=brain.nodes[target];meta=node.get('meta',{})
        if (target in tomb or meta.get('forgotten') or meta.get('library_id') not in (None,library)
                or meta.get('memory_disabled_origin')=='explicit_user_action'):
            continue
        if meta.get('memory_disabled') and not meta.get('memory_disabled_origin'):
            selected.append(target)
    # Sources not paused by the user need historical attribution as well, but
    # are never implicitly enabled by restoring a downstream legacy entry.
    sources=sorted(i for i in relevant if brain.nodes[i].get('meta',{}).get('source') in RAW_SOURCES
                   and not brain.nodes[i].get('meta',{}).get('memory_disabled')
                   and i not in tomb and not brain.nodes[i].get('meta',{}).get('forgotten')
                   and brain.nodes[i].get('meta',{}).get('library_id') in (None,library)) if selected else []
    revisions={i:fingerprint(brain.nodes[i]) for i in sorted(set(selected)|set(sources)|set(proof))}
    digest=sha256(json.dumps({'library':library,'target':nid,'revisions':revisions},sort_keys=True).encode()).hexdigest()
    return {'id':nid,'library_id':library,'read_only':True,'requires_confirmation':True,
            'expected_revision':digest,'node_ids':selected,'source_ids':sources,
            'entries':[{'id':i,'label':brain.nodes[i].get('label',''),'legacy_state':'unknown_pause_origin'} for i in selected],
            'node_count':len(selected),'source_count':len(sources),'current_memory_restored':False,
            'note':'旧版标记无法区分自动更正和手动停用；确认后仅恢复下列条目的历史读取，不恢复为当前说法。'}


def restore_history(brain,nid,*,confirm=False,expected_revision=None):
    if confirm is not True:raise ValidationError('请先查看并确认旧版历史恢复范围')
    plan=history_restore_preview(brain,nid)
    if expected_revision!=plan['expected_revision']:raise ValidationError('历史恢复范围已变化，请重新预览')
    from ..companion.versions import REVISION_SCHEMA
    from ..organizer.state import fingerprint,RAW_SOURCES
    changed=set(plan['node_ids'])|set(plan['source_ids'])
    original_sources={i:fingerprint(brain.nodes[i]) for i in changed
                      if brain.nodes[i].get('meta',{}).get('source') in RAW_SOURCES}
    stamp=time.time()
    for target in plan['node_ids']:
        meta=brain.nodes[target]['meta'];meta['memory_disabled']=False
        meta['memory_disabled_origin']='legacy_history_restore'
    for target in changed:
        brain.nodes[target]['meta']['memory_revision']={'schema':REVISION_SCHEMA,'status':'historical',
            'reason':'legacy_history_restore','at':stamp}
    _refresh_unchanged_source_guards(brain,original_sources)
    rebuild_source_controls(brain,changed=True)
    return {'id':nid,'library_id':brain.meta.get('library_id'),'restored':True,
            'historical_ids':sorted(set(plan['node_ids'])|set(plan['source_ids'])),
            'node_count':plan['node_count'],'source_count':plan['source_count'],
            'current_memory_restored':False,'world_truth_assessed':False}

def correct(brain,nid,text,label=None,source_id=None,source_confirmed_as_self=False):
    if nid not in brain.nodes:raise ValidationError('记忆不存在')
    if not isinstance(text,str) or not text.strip() or len(text)>40000:raise ValidationError('更正内容须为1~40000字')
    if label is not None and (not isinstance(label,str) or not label.strip() or len(label)>100):raise ValidationError('标题须为1~100字')
    if type(source_confirmed_as_self) is not bool or source_confirmed_as_self and source_id is None:
        raise ValidationError('更正来源身份确认须对应明确选择的原始发言')
    source_ownership=None
    if source_id is not None:
        from ..companion.lifecycle import correction_source,correction_candidates
        source=correction_source(brain,source_id,allow_external=source_confirmed_as_self) if isinstance(source_id,str) else None
        if source is None:
            raise ValidationError('纠正来源须为当前库内可核对的本人直接发言')
        if source['actor_scope']=='external_participant':
            if brain.get(nid).get('kind') not in ('fact','preference','commitment'):
                raise ValidationError('请手动选择这次本人更正对应的事实、偏好或约定')
            source_ownership='explicit_user_confirmation'
        else:
            proposals=correction_candidates(brain,library_id=brain.meta.get('library_id'),source_id=source_id)
            if not proposals or nid not in {item['id'] for item in proposals[0]['candidates']}:
                raise ValidationError('这项记忆不属于该纠正发言的可核对候选，请重新选择或手动更正')
            source_ownership='direct_first_party_capture'
    old=brain.nodes[nid]
    if old.get('superseded_by') or old.get('meta',{}).get('forgotten'):
        raise ValidationError('这条记忆已有更正或已被忘记，请打开当前有效条目再更正')
    historical=related(brain,[nid])
    # Preserve the complete original utterance as dated evidence. Related
    # excerpts are no longer current assertions, but are not privacy-disabled.
    from ..organizer.state import RAW_SOURCES
    for target in list(historical):
        historical.update(ref for ref in refs(brain.nodes[target])
                          if ref in brain.nodes and brain.nodes[ref].get('meta',{}).get('source') in RAW_SOURCES)
    from ..organizer.state import fingerprint
    original_sources={i:fingerprint(brain.nodes[i]) for i in historical
                      if brain.nodes[i].get('meta',{}).get('source') in RAW_SOURCES}
    stamp=time.time()
    # Nominal topic tags aid the same question after a correction; sentences or
    # outdated preference assertions must never become the replacement's title.
    from ..companion.lifecycle import safe_topic_tags,nominal_topic
    tags=safe_topic_tags(old)
    subject=old.get('meta',{}).get('organizer_subject')
    new=brain.add(label or text.strip().splitlines()[0][:80],text.strip(),kind=old['kind'] if old['kind'] in ('fact','preference','episode','commitment') else 'fact',
       salience=.8,tags=tags,session_id=old.get('session_id'),meta={'source':'user_confirmed','confirmed':True,
                        'important':bool(old.get('important') or old.get('meta',{}).get('important')),
                        'speaker':'user','corrects':nid,'corrected_at':stamp,
                        **({'correction_source_id':source_id,'source_ids':[source_id],
                            'correction_source_ownership':source_ownership} if source_id is not None else {}),
                        **({'retrieval_subject':subject} if nominal_topic(subject) else {}),
                        **({'library_id':brain.meta['library_id']} if brain.meta.get('library_id') else {}),
                        **({field:old.get('meta',{})[field] for field in ('status','status_origin','status_at','status_note','done_at','cancelled_at')
                            if field in old.get('meta',{})} if old['kind']=='commitment' else {})})
    brain.supersede(nid,new,at=stamp)
    from ..companion.versions import REVISION_SCHEMA
    for target in historical:
        brain.nodes[target]['meta']['memory_revision']={'schema':REVISION_SCHEMA,'status':'historical',
            'reason':'later_correction','corrected_by':new,'at':stamp}
    _refresh_unchanged_source_guards(brain,original_sources)
    verification=verify_correction(brain,nid,new)
    return {'id':new,'previous_id':nid,'disabled_ids':[],'historical_ids':sorted(historical),'saved':True,
            'change_scope':{'library_id':brain.meta.get('library_id'),'previous_id':nid,
                            'replacement_id':new,'disabled_count':0,'historical_count':len(historical),
                            'disabled_ids':[],'historical_ids':sorted(historical),'original_preserved':True,
                            'history_available':True,'world_truth_assessed':False},
            'verification':verification}

def verify_correction(brain,previous_id,replacement_id,query=None):
    """Re-run selection against this committed/scoped snapshot, never a model ACK."""
    old,new=brain.get(previous_id),brain.get(replacement_id)
    if (old is None or new is None or new.get('meta',{}).get('corrects')!=previous_id
            or old.get('superseded_by')!=replacement_id):
        raise ValidationError('找不到同一库内的有效更正关系')
    from ..companion.memory import build_context
    if query is not None and (not isinstance(query,str) or not query.strip() or len(query)>40000):
        raise ValidationError('核验问题须为1~40000字')
    from ..companion.lifecycle import commitment_status
    probe=query or old['label'][:4000]
    if query is None and commitment_status(new) in ('done','cancelled'):probe='历史约定状态：'+probe
    # A previous label may itself say “以前”; this probe verifies the current
    # selection contract, rather than allowing wording to switch to history.
    result=build_context(brain,probe,library_id=brain.meta.get('library_id'),view='current')
    ids=result['memory_ids']
    affected=related(brain,[previous_id])-{replacement_id}
    leaks=sorted(set(ids)&affected)
    return {'checked_at':time.time(),'query':probe,
            'previous_excluded':previous_id not in ids,'replacement_included':replacement_id in ids,
            'disabled_material_excluded':not leaks,'leaked_ids':leaks,'provided_ids':ids,
            'selection_verified':replacement_id in ids and not leaks,
            'model_adoption_verified':False,'will_call_model':False,'read_only':True}

def forget_plan(brain,nid,extra_ids=()):
    if nid not in brain.nodes:raise ValidationError('记忆不存在')
    ids=related(brain,[nid,*extra_ids],include_sources=True)
    raw_ids=set();texts=set()
    for i in ids:
        n=brain.nodes[i];m=n.get('meta',{});e=m.get('evidence') or {}
        if isinstance(e,dict) and e.get('archive_receipt_id'):raw_ids.add(e['archive_receipt_id'])
        for text in (n.get('text'),m.get('assistant_reply')):
            if isinstance(text,str) and text:texts.add(text)
    return {'node_ids':sorted(ids),'raw_ids':sorted(raw_ids),'texts':sorted(texts)}

def forget(brain,plan):
    ids=set(plan['node_ids']);raw_ids=set(plan['raw_ids'])
    tomb=brain.meta.setdefault('memory_tombstones',{'node_ids':[],'raw_ids':[],'text_hashes':[]})
    for key,values in (('node_ids',ids),('raw_ids',raw_ids),('text_hashes',{sha256(t.encode()).hexdigest() for t in plan['texts']})):
        tomb[key]=sorted(set(tomb.get(key,[]))|set(values))
    for i in ids:
        if i in brain.nodes:brain.remove(i)
    # Undo snapshots and candidate text may contain deleted evidence. Clear them
    # rather than keeping a hidden second copy of the user's forgotten material.
    brain.meta.pop('organizer_log',None);brain.meta.pop('organizer_candidates',None)
    persona=brain.meta.pop('companion_persona',None)
    profile=brain.meta.get('companion_profile',{})
    if profile.get('persona') and any(profile['persona'] in t for t in plan['texts']):profile['persona']=''
    brain.meta.pop('companion_ingestion',None)
    def redacted(text):
        if not isinstance(text,str):return text
        for forgotten in plan['texts']:
            if len(forgotten)>3:text=text.replace(forgotten,'[用户已忘记]')
            elif text==forgotten:text='[用户已忘记]'
        return text
    # Remove copied quotations from remaining notes, labels and anchor excerpts.
    # This is explicit privacy redaction, not a rewrite of their historical meaning.
    for node in brain.nodes.values():
        for field in ('text','label'):node[field]=redacted(node[field])
        m=node.get('meta',{})
        for field in ('assistant_reply','organizer_summary','source_url'):
            if field in m:m[field]=redacted(m[field])
        if 'organizer_aliases' in m:m['organizer_aliases']=[redacted(t) for t in m['organizer_aliases']]
        for snippet in (node.get('anchor_info') or {}).get('context_snippets',[]):
            if 'excerpt' in snippet:snippet['excerpt']=redacted(snippet['excerpt'])
        brain._vec[node['id']]=brain._vec_for(node)
    for key in list(profile):profile[key]=redacted(profile[key])
    rebuild_source_controls(brain,changed=True)
    return {'forgotten':True,'removed_nodes':len(ids),'raw_ids':sorted(raw_ids),
            'persona_history_cleared':persona is not None}
