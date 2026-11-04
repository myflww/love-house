"""Scoped, evidence-attributed experiences and explicit commitment follow-up.

This module never invents an event, infers a completed task from prose, schedules
a message, or changes a connection. Management authentication is owned by host.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import math
import re

from ..errors import ValidationError
from ..utils import now

STATUSES = ('open', 'done', 'cancelled')
_HISTORY = re.compile(r'以前|之前|过去|历史|当时|完成|结果|取消|结束|后来|上次|曾经|\b(?:history|historical|past|done|completed|cancelled|canceled|outcome)\b', re.I)
_CORRECTION = re.compile(r'^(?:(?:请)?(?:更正|纠正)(?:一下|记忆)?[：:,，\s]|(?:你|这件事|这个|这里).{0,8}记错了[：:,，。！!?？\s]|我(?:现在|以后|已经)(?:不再|不喜欢|不喝|不吃|改成|改为|不想|不需要))',re.I)


def nominal_topic(value):
    return (isinstance(value,str) and 1<=len(value)<=80
            and not re.search(r'[\n\r，。；：:;"“”]|喜欢|讨厌|偏爱|不再|必须|应该|(?:^|\s)(?:like|love|hate|must|should)\b',value,re.I))


def safe_topic_tags(node):
    tags=node.get('tags',[])
    return [tag for tag in tags if nominal_topic(tag)][:32] if isinstance(tags,list) else []


def correction_source(brain, source_id, *, allow_external=False):
    """Only a direct, first-party captured turn can suggest a review candidate."""
    node=brain.get(source_id)
    if node is None:return None
    meta=node.get('meta',{});evidence=meta.get('evidence') if isinstance(meta.get('evidence'),dict) else {}
    origin=meta.get('recording_origin',meta.get('origin'))
    external=meta.get('participant_scope')=='external_participant' or evidence.get('participant_scope')=='external_participant'
    if (meta.get('source')!='conversation_turn' or origin not in ('harness_hook','api_proxy','connected_chat','harness','automatic_capture','agent_hook','agent_source_adapter')
            or meta.get('library_id') not in (None,brain.meta.get('library_id'))
            or meta.get('provenance')=='imported_record' or meta.get('memory_disabled') or meta.get('forgotten')
            or external and not allow_external
            or not isinstance(meta.get('connection_id'),str) or not isinstance(evidence.get('archive_receipt_id'),str)
            or not brain._node_state(node,now()).get('recoverable')):return None
    text=node.get('text')
    if not isinstance(text,str) or any(marker in text for marker in ('<memory_material','"memory_context"','"material_role"')):return None
    # Quoted dialogue, fenced examples, reported speech and imported transcripts
    # are never interpreted as an owner's new correction request.
    text=re.sub(r'```[\s\S]*?```','',text)
    lines=[line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith(('>','“','「','"',"'"))]
    statement=lines[0] if lines and _CORRECTION.search(lines[0]) else None
    return {'node':node,'statement':statement,'actor_scope':'external_participant' if external else 'direct_capture',
            'participant_id':str(evidence.get('participant_id',''))[:200] if external else None} if statement else None


def correction_candidates(brain, *, library_id=None, limit=10, source_id=None):
    """Read-only review hints; no natural-language claim is auto-confirmed."""
    if library_id and brain.meta.get('library_id') not in (None,library_id):raise ValidationError('纠正候选不属于当前记忆库')
    library_id=library_id or brain.meta.get('library_id')
    if type(limit) is not int or not 1<=limit<=50:raise ValidationError('纠正候选数量须为1~50')
    resolved={n.get('meta',{}).get('correction_source_id') for n in brain.nodes.values()
              if isinstance(n.get('meta',{}).get('correction_source_id'),str)}
    sources=[]
    for node in ([brain.nodes[source_id]] if isinstance(source_id,str) and source_id in brain.nodes else [] if source_id is not None else brain.nodes.values()):
        if node['id'] in resolved or node.get('meta',{}).get('library_id') not in (None,library_id):continue
        source=correction_source(brain,node['id'],allow_external=True)
        if source:sources.append(source)
    sources.sort(key=lambda item:(item['node'].get('created',0),item['node']['id']),reverse=True)
    from ..organizer.state import prepare_recall,semantic_recall
    prepared=prepare_recall(brain)
    from .structured import _record
    eligible={node['id'] for node in brain.nodes.values() if node.get('kind') in ('fact','preference','commitment')
              and node.get('meta',{}).get('library_id') in (None,library_id)
              and not _record(brain,node,now(),library_id)[1]}
    proposals=[]
    for source in sources[:limit]:
        node,statement=source['node'],source['statement']
        earlier={nid for nid in eligible if brain.nodes[nid].get('created',0)<=node.get('created',0)}
        # QQ/group peers are not implicitly the owner. Their text may be
        # reviewed, but cannot select or rewrite the owner's facts by itself.
        external=source['actor_scope']=='external_participant'
        hits=[] if external else semantic_recall(brain,statement,k=3,candidate_ids=earlier,prepared=prepared)['hits']
        targets=[{'id':hit['id'],'title':str(brain.nodes[hit['id']].get('label',''))[:100],
                  'text':str(brain.nodes[hit['id']].get('text',''))[:1000]} for hit in hits]
        proposals.append({'id':'correction_'+sha256((node['id']+'\n'+statement).encode()).hexdigest()[:24],
                          'source_id':node['id'],'source_text':statement[:4000],
                          'source_text_truncated':len(statement)>4000,'recorded_at':node.get('created'),
                          'candidates':targets,'target_selection_required':True,'requires_explicit_confirmation':True,
                          'actor_scope':source['actor_scope'],'participant_id':source['participant_id'],
                          'requires_identity_confirmation':external,
                          'status':'review_required','auto_applied':False,'read_only':True})
    return proposals


def commitment_status(node):
    if node.get('kind') != 'commitment':return None
    status=node.get('meta',{}).get('status','open')
    return status if status in STATUSES else 'open'


def include_closed_commitments(query):
    return bool(_HISTORY.search(query))


def set_commitment_status(brain, nid, status, note='', *, at=None):
    """An explicit local-user action; result remains a user report, not tool proof."""
    node=brain.get(nid)
    if node is None or node.get('kind')!='commitment':raise ValidationError('请选择当前库内的约定')
    if (node.get('meta',{}).get('forgotten') or node.get('superseded_by')
            or node.get('meta',{}).get('memory_disabled')
            or nid in brain.meta.get('memory_tombstones',{}).get('node_ids',[])):
        raise ValidationError('已停用、被更正或忘记的约定不能更新跟进状态')
    if status not in STATUSES:raise ValidationError('约定状态须为 open、done 或 cancelled')
    if not isinstance(note,str) or len(note)>4000:raise ValidationError('约定说明须为不超过4000字的文本')
    try:note.encode('utf-8')
    except UnicodeError:raise ValidationError('约定说明包含无法保存的字符') from None
    stamp=now() if at is None else at
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<0:
        raise ValidationError('约定状态时间无效')
    previous=commitment_status(node)
    meta=node.setdefault('meta',{})
    changed=previous!=status or meta.get('status_note','')!=note.strip()
    if changed:
        meta.update(status=status,status_at=stamp,status_note=note.strip(),status_origin='explicit_user_action')
        if status=='done':meta['done_at']=stamp
        elif status=='cancelled':meta['cancelled_at']=stamp
        else:
            meta.pop('done_at',None);meta.pop('cancelled_at',None)
        node['updated']=stamp
    return {'id':nid,'previous_status':previous,'status':status,'changed':changed,
            'follow_up':status=='open','history_preserved':True,
            'will_send_message':False,'basis':'explicit_user_action','read_only':False}


def _stamp(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None


def timeline(brain, *, library_id=None, cursor=None, limit=20, view='all', query=''):
    """Paginated management view of original events; never a generated life story."""
    if library_id and brain.meta.get('library_id') not in (None,library_id):
        raise ValidationError('时间线不属于当前记忆库')
    if type(limit) is not int or not 1<=limit<=50:raise ValidationError('时间线每页显示1~50条')
    if view not in ('all','open','closed','corrections','experiences'):raise ValidationError('请选择有效的时间线筛选')
    if not isinstance(query,str) or len(query)>200:raise ValidationError('时间线搜索词最多200字')
    try:query.encode('utf-8')
    except UnicodeError:raise ValidationError('时间线搜索词包含无法保存的字符') from None
    tomb=set(brain.meta.get('memory_tombstones',{}).get('node_ids',[]))
    rows=[]
    stamp=now()
    for node in brain.nodes.values():
        meta=node.get('meta',{})
        if (node['id'] in tomb or meta.get('forgotten') or meta.get('demo')
                or library_id and meta.get('library_id') not in (None,library_id)):continue
        if node.get('created',stamp)>stamp or not brain._node_state(node,stamp).get('history_available'):continue
        correction=bool(meta.get('corrects') or node.get('superseded_by'))
        kind=node.get('kind')
        if kind not in ('episode','commitment') and not correction:continue
        # A model's narrative remains visible only through its verified sources.
        episode=None
        if meta.get('source')=='organizer':
            from .structured import _record
            record,reason=_record(brain,node,now(),library_id)
            if reason:continue
            episode=record.get('experience')
        status=commitment_status(node)
        if node.get('superseded_by'):status='superseded'
        elif meta.get('memory_disabled'):status='disabled'
        elif correction:status='corrected'
        elif status is None:status='recorded'
        if view=='open' and (kind!='commitment' or status!='open'):continue
        if view=='closed' and (kind!='commitment' or status not in ('done','cancelled')):continue
        if view=='corrections' and not correction:continue
        if view=='experiences' and kind!='episode':continue
        if query and query.casefold() not in (str(node.get('label',''))+'\n'+str(node.get('text',''))).casefold():continue
        recorded=_stamp(node.get('created'))
        event=_stamp(node.get('event_at')) if not meta.get('source_time_unknown') else None
        role='user' if meta.get('source')=='conversation_turn' else meta.get('speaker','unknown')
        source={'kind':str(meta.get('source','local'))[:100],'role':role if role in ('user','assistant','tool') else 'unknown',
                'basis':'user_confirmed_statement' if meta.get('source')=='user_confirmed' and meta.get('confirmed') is True else 'attributed_historical_material'}
        entry={'id':node['id'],'title':str(node.get('label',''))[:100],'text':str(node.get('text',''))[:4000],
               'text_truncated':len(str(node.get('text','')))>4000,'kind':kind,'status':status,
               'event_at':event,'recorded_at':recorded,'time_basis':'source_event' if event is not None else 'recorded_time_only',
               'temporal_status':'future_source_time' if event is not None and event>stamp else 'recorded',
               'source':source,'follow_up':kind=='commitment' and status=='open'}
        for field in ('status_at','done_at','cancelled_at','due'):
            if _stamp(meta.get(field)) is not None:entry[field]=meta[field]
        if isinstance(meta.get('status_note'),str):entry['status_note']=meta['status_note'][:4000]
        if meta.get('status_origin')=='explicit_user_action':entry['status_origin']='explicit_user_action'
        if isinstance(meta.get('corrects'),str) and meta['corrects'] in brain.nodes:entry['corrects']=meta['corrects']
        if node.get('superseded_by') in brain.nodes:entry['superseded_by']=node['superseded_by']
        if episode:entry['experience']=episode
        rows.append(entry)
    rows.sort(key=lambda r:(r['event_at'] if r['event_at'] is not None else r['recorded_at'] or 0,r['id']),reverse=True)
    signature=sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    offset=0
    if cursor:
        try:
            if not isinstance(cursor,str) or len(cursor)>2048:raise ValueError()
            value=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
            if value[:4]!=[library_id,signature,view,query] or len(value)!=5 or type(value[4]) is not int or not 0<=value[4]<=len(rows):raise ValueError()
            offset=value[4]
        except (ValueError,TypeError,UnicodeError,IndexError):
            raise ValidationError('时间线已变化，请刷新后继续查看') from None
    selected=rows[offset:offset+limit]
    next_offset=offset+len(selected)
    next_cursor=base64.urlsafe_b64encode(json.dumps([library_id,signature,view,query,next_offset],ensure_ascii=False).encode()).decode().rstrip('=') if next_offset<len(rows) else None
    return {'schema':'love-house-memory-timeline/v1','library_id':library_id,'entries':selected,
            'total':len(rows),'next_cursor':next_cursor,'view':view,'read_only':True,'will_call_model':False,
            'interpretation':'attributed_records_not_generated_biography'}


def verify_citations(brain, delivery, response_node_id, references, *, archived_reply=None):
    """Verify exact quoted spans in an actual same-window archived reply.

    The host resolves archived_reply from its archive, never a caller's body.
    A literal reference proves a citation, not private model thought/adoption.
    """
    node=brain.get(response_node_id)
    meta=node.get('meta',{}) if node else {}
    evidence=meta.get('evidence') if isinstance(meta.get('evidence'),dict) else {}
    tomb=brain.meta.get('memory_tombstones',{}).get('node_ids',[])
    if (node is None or meta.get('source')!='conversation_turn' or meta.get('memory_disabled') or meta.get('forgotten')
            or node.get('superseded_by') or response_node_id in tomb
            or meta.get('connection_id',evidence.get('connection_id'))!=delivery['connection_id']
            or meta.get('external_session_id',evidence.get('session_id'))!=delivery['session_id']
            or not isinstance(evidence.get('archive_receipt_id'),str)
            or node.get('created',0)<delivery['issued_at']
            or brain.meta.get('library_id') not in (None,delivery['library_id'])):
        raise ValidationError('引用必须来自本窗口这次记忆提供后实际归档的回复')
    reply=archived_reply if archived_reply is not None else meta.get('assistant_reply')
    if not isinstance(reply,str) or evidence.get('content_truncated') and archived_reply is None:
        raise ValidationError('完整归档回复暂不可核对')
    if not isinstance(references,list) or not 1<=len(references)<=128:
        raise ValidationError('请提供1~128项可核对的原文引用')
    verified=[]
    for reference in references:
        if not isinstance(reference,dict) or set(reference)!={'id','quote'}:raise ValidationError('引用仅接受记忆ID和逐字摘录')
        nid,quote=reference['id'],reference['quote']
        memory=brain.get(nid) if isinstance(nid,str) else None
        from .structured import _record
        unavailable=memory is None or bool(_record(brain,memory,now(),delivery['library_id'])[1])
        if (nid not in delivery['node_ids'] or unavailable or nid in tomb
                or not isinstance(quote,str) or not 8<=len(quote)<=4000 or quote not in reply
                or quote not in str(memory.get('text','')) and quote not in str(memory.get('label',''))):
            raise ValidationError('引用须同时存在于已提供记忆和实际归档回复中')
        if nid not in verified:verified.append(nid)
    return verified
