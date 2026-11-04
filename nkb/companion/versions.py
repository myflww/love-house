"""Request-local views of recorded statements, without changing their truth.

History is an access mode, never permission to undo a pause or forget. The saved
graph stays unchanged; only scoring receives shallow temporal projections.
"""
from ..errors import ValidationError

VIEWS = ('current', 'history', 'comparison')
REVISION_SCHEMA = 'love-house-memory-revision/v1'


def resolve_view(view=None, *, query=None, stamp=None):
    if view is None:
        if query:
            from ..retrieval.query import plan_query
            intent = plan_query(query, stamp).intent
            return 'history' if intent == 'historical' else 'comparison' if intent == 'comparison' else 'current'
        return 'current'
    if not isinstance(view, str) or view not in VIEWS:
        raise ValidationError('view须为current、history或comparison')
    return view


def is_historical(node):
    meta = node.get('meta', {})
    marker = meta.get('memory_revision')
    return (bool(node.get('superseded_by')) or node.get('valid_to') is not None
            or isinstance(marker, dict) and marker.get('schema') == REVISION_SCHEMA
            and marker.get('status') == 'historical')


def historical_projection(node):
    """Relax version expiry only; retain explicit disable, age and source guards."""
    if not is_historical(node):
        return node
    projected = {**node}
    projected.pop('valid_to', None)
    projected.pop('superseded_by', None)
    return projected


def readable(brain, node, stamp, view='current', library_id=None, *, state=None):
    meta = node.get('meta', {})
    tomb = brain.meta.get('memory_tombstones', {})
    evidence = meta.get('evidence') if isinstance(meta.get('evidence'), dict) else {}
    if (meta.get('memory_disabled') or meta.get('forgotten') or node['id'] in tomb.get('node_ids', [])
            or evidence.get('archive_receipt_id') in tomb.get('raw_ids', [])
            or library_id and meta.get('library_id') not in (None, library_id)):
        return False
    if view == 'current' and is_historical(node):
        return False
    projected = historical_projection(node) if view != 'current' else node
    state = brain._node_state(projected, stamp) if state is None else state
    return bool(state.get('history_available') and state.get('recoverable'))


class RevisionIndex:
    """One linear relationship pass; no body copy or cross-request cache."""
    def __init__(self, brain):
        self.brain = brain
        self.previous = {}
        self.next = {}
        for nid, node in brain.nodes.items():
            other = node.get('superseded_by')
            marker=node.get('meta',{}).get('memory_revision')
            if not other and isinstance(marker,dict) and marker.get('schema')==REVISION_SCHEMA:
                other=marker.get('corrected_by')
            if isinstance(other, str) and other in brain.nodes:
                self.next[nid] = other
                self.previous.setdefault(other, []).append(nid)
        for values in self.previous.values():
            values.sort(key=lambda nid: (brain.nodes[nid].get('created', 0), nid))

    def related(self, ids):
        seen, queue = set(ids), list(ids)
        while queue:
            nid = queue.pop()
            neighbors = [*self.previous.get(nid, []), *([self.next[nid]] if nid in self.next else [])]
            for other in neighbors:
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        return seen


def revision_info(brain, node, library_id=None):
    marker = node.get('meta', {}).get('memory_revision')
    result = {'state': 'historical' if is_historical(node) else 'current',
              'world_truth_assessed': False}
    for field, value in (('previous_id', node.get('meta', {}).get('corrects')),
                         ('superseded_by', node.get('superseded_by'))):
        other = brain.get(value) if isinstance(value, str) else None
        if other and other.get('meta', {}).get('library_id') in (None, library_id):
            result[field] = value
    if isinstance(marker, dict) and marker.get('schema') == REVISION_SCHEMA:
        result['reason'] = marker.get('reason', 'later_correction')
        if type(marker.get('at')) in (int, float):
            result['changed_at'] = marker['at']
        other = brain.get(marker.get('corrected_by')) if isinstance(marker.get('corrected_by'), str) else None
        if other and other.get('meta', {}).get('library_id') in (None, library_id):
            result['corrected_by'] = other['id']
    return result


def read_memory_versions(brain, library_id, nid, *, cursor=None, limit=20):
    """A paginated chain for the local manager; unavailable bodies never return."""
    from hashlib import sha256
    import json
    from ..utils import now
    from ..organizer.state import fingerprint
    from .memory import _disabled_evidence
    from .structured import _record
    from .catalog import _cursor,_offset
    from ..service.controls import history_restore_preview
    if brain.meta.get('library_id') not in (None,library_id):raise ValidationError('历史条目不属于当前记忆库')
    node=brain.get(nid)
    if node is None or node.get('meta',{}).get('library_id') not in (None,library_id):raise ValidationError('本库没有该历史条目')
    if type(limit) is not int or not 1<=limit<=100:raise ValidationError('每页历史条目数量须为1~100')
    ids=RevisionIndex(brain).related([nid])
    nodes=[brain.nodes[i] for i in ids if brain.nodes[i].get('meta',{}).get('library_id') in (None,library_id)]
    nodes.sort(key=lambda n:(n.get('created',0),n['id']))
    blocked=_disabled_evidence(brain);stamp=now()
    digest=sha256(json.dumps({'target':nid,'view':'history','states':{n['id']:fingerprint(n) for n in nodes},
                             'blocked':sorted(ids&blocked)},sort_keys=True).encode()).hexdigest()
    offset=_offset(cursor,library_id,digest,len(nodes))
    entries=[];current_id=None
    for item in nodes:
        if not is_historical(item) and item['id'] not in blocked and readable(brain,item,stamp,'history',library_id):current_id=item['id']
    for item in nodes[offset:offset+limit]:
        record,reason=(None,'paused_evidence') if item['id'] in blocked else _record(brain,item,stamp,library_id,blocked_evidence=blocked,view='history')
        if record:
            entries.append({'id':item['id'],'label':item.get('label',''),'text':item.get('text',''),
                'role':record['subject'],'recorded_at':record['recorded_at'],'source_time':record['source_time'],
                'revision':record['revision'],'source_ids':[r['id'] for r in record['source']['evidence']],
                'source':record['source'],'available':True})
        else:entries.append({'id':item['id'],'available':False,'reason':reason})
    next_offset=offset+len(entries)
    legacy=history_restore_preview(brain,nid)
    return {'schema':'love-house-memory-versions/v1','library_id':library_id,'id':nid,'view':'history',
            'entries':entries,'current_id':current_id,'total_versions':len(nodes),
            'next_cursor':_cursor(library_id,digest,next_offset) if next_offset<len(nodes) else None,
            'legacy_history_requires_confirmation':bool(legacy['node_count']),
            'read_only':True,'world_truth_assessed':False,'will_call_model':False}
