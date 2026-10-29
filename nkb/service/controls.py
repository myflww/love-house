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
    for i in ids:brain.nodes[i]['meta']['memory_disabled']=not enabled
    return {'id':nid,'enabled':enabled,'affected_ids':sorted(ids)}

def correct(brain,nid,text,label=None):
    if nid not in brain.nodes:raise ValidationError('记忆不存在')
    if not isinstance(text,str) or not text.strip() or len(text)>40000:raise ValidationError('更正内容须为1~40000字')
    if label is not None and (not isinstance(label,str) or not label.strip() or len(label)>100):raise ValidationError('标题须为1~100字')
    old=brain.nodes[nid]
    disabled=set_enabled(brain,nid,False)['affected_ids']
    new=brain.add(label or text.strip().splitlines()[0][:80],text.strip(),kind=old['kind'] if old['kind'] in ('fact','preference','episode','commitment') else 'fact',
       salience=.8,meta={'source':'user_confirmed','confirmed':True,'important':bool(old.get('important')),
                        'speaker':'user','corrects':nid,'corrected_at':time.time()})
    brain.link(nid,new,.35)
    return {'id':new,'previous_id':nid,'disabled_ids':disabled,'saved':True}

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
    return {'forgotten':True,'removed_nodes':len(ids),'raw_ids':sorted(raw_ids),
            'persona_history_cleared':persona is not None}
