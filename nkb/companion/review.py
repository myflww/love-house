"""Evidence-bound idle reviews. Proposals are data, never new user facts.

The host supplies an atomic graph/authorization snapshot and repeats this check
under its library write lock. Nothing here changes model parameters or activates
a retrieval strategy. Simulation material never enters ordinary memory.
"""
from copy import deepcopy
from hashlib import sha256
import json

from ..errors import ValidationError
from ..organizer.model import OrganizerConflict, OrganizerError
from ..organizer.state import fingerprint, _roles

SCHEMA = 'love-house-idle-review/v1'
REFLECTION_SCHEMA = 'love-house-review-reflection/v1'
DEFAULT_PROFILE = {'enabled': False, 'idle_seconds': 300, 'batch_size': 6}
SOURCE_KINDS = frozenset(('conversation_turn', 'agent_output', 'tool_observation', 'history_import'))
PROPOSAL_TYPES = frozenset(('reflection', 'strategy_candidate', 'simulation'))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _profile(stored):
    if not isinstance(stored, dict) or set(stored) - set(DEFAULT_PROFILE):
        raise ValidationError('空闲整理设置包含未知字段')
    profile = {**DEFAULT_PROFILE, **stored}
    if type(profile['enabled']) is not bool:
        raise ValidationError('空闲整理enabled须为布尔值')
    for name, low, high in (('idle_seconds', 30, 86400), ('batch_size', 1, 12)):
        if type(profile[name]) is not int or not low <= profile[name] <= high:
            raise ValidationError(f'{name}须为{low}~{high}的整数')
    return profile


def get_review_profile(brain):
    return _profile(brain.meta.get('idle_review_profile', {}))


def save_review_profile(brain, **settings):
    merged = {**get_review_profile(brain), **settings}
    result = _profile(merged)
    brain.meta['idle_review_profile'] = deepcopy(result)
    return result


def authorization(value):
    """A server-owned capability snapshot, never taken from a model or client."""
    if (not isinstance(value, dict) or set(value) - {'generation', 'connection_ids', 'allow_local', 'connection_scopes', 'source_scopes'}
            or not isinstance(value.get('generation'), str) or not value['generation']
            or len(value['generation']) > 200 or type(value.get('allow_local', False)) is not bool):
        raise ValidationError('回顾需要当前同库授权代次')
    ids = value.get('connection_ids', [])
    if (not isinstance(ids, list) or len(ids) > 10000
            or any(not isinstance(i, str) or not i or len(i) > 200 for i in ids)):
        raise ValidationError('回顾授权连接列表格式不正确')
    scopes = value.get('connection_scopes', {})
    if not isinstance(scopes, dict) or set(scopes) != set(ids):
        raise ValidationError('回顾连接窗口范围格式不正确')
    for cid, scope in scopes.items():
        if (not isinstance(scope, dict) or set(scope) != {'policy', 'window_id', 'binding_revision'}
                or scope['policy'] not in ('any', 'fixed', 'next_session')
                or type(scope['binding_revision']) is not int or scope['binding_revision'] < 0
                or scope['window_id'] is not None and (not isinstance(scope['window_id'], str)
                    or not scope['window_id'] or len(scope['window_id']) > 200)):
            raise ValidationError('回顾连接窗口范围格式不正确')
    source_scopes = value.get('source_scopes', {})
    if not isinstance(source_scopes, dict) or set(source_scopes) - set(ids):
        raise ValidationError('回顾来源身份范围格式不正确')
    for scope in source_scopes.values():
        if (not isinstance(scope, dict) or set(scope) != {'source_id', 'runtime_agent_id'}
                or any(not isinstance(v, str) or not v or len(v) > 200 for v in scope.values())):
            raise ValidationError('回顾来源身份范围格式不正确')
    return {'generation': value['generation'], 'connection_ids': sorted(set(ids)),
            'allow_local': value.get('allow_local', False), 'connection_scopes': deepcopy(scopes),
            'source_scopes': deepcopy(source_scopes)}


def source_record(brain, node, library_id, auth, *, stamp=None, blocked_evidence=None, _validated_auth=False):
    """Validate one primary source. Directory reads use current controls, not a graph scan."""
    from ..core.brain import _now
    from .structured import _record
    if not isinstance(node, dict):
        return None
    if not _validated_auth:auth = authorization(auth)
    if brain.meta.get('library_id') not in (None, library_id):
        return None
    stamp = _now() if stamp is None else stamp
    allowed = auth['connection_scopes']  # validated keys; O(1) membership per source
    blocked = brain.meta.get('memory_tombstones', {}).get('raw_ids', [])
    if blocked_evidence is None:
        controls = brain.meta.get('memory_source_controls')
        if not isinstance(controls, dict) or controls.get('schema') != 'love-house-source-controls/v1' or not isinstance(controls.get('blocked_by'), dict):
            return None  # Legacy sources need a one-time complete controls rebuild.
        blockers = controls['blocked_by'].get(node['id'], [])
        if not isinstance(blockers, list):
            return None
        def live_blocker(nid):
            other=brain.get(nid)
            if not other or not other.get('meta',{}).get('memory_disabled'):return False
            m=other.get('meta',{})
            atom=m.get('memory_atom') if isinstance(m.get('memory_atom'),dict) else {}
            return any(isinstance(collection,list) and any(isinstance(ref,dict) and ref.get('id')==node['id'] for ref in collection)
                       for collection in (m.get('organizer_evidence'),m.get('organizer_sources'),atom.get('evidence')))
        blocked_nodes = {node['id']} if any(live_blocker(nid) for nid in blockers) else set()
    else:
        blocked_nodes = blocked_evidence
    meta = node.get('meta', {})
    if (meta.get('source') not in SOURCE_KINDS or node.get('kind') == 'reflection'
            or meta.get('review_origin') or meta.get('simulation') or meta.get('internal_review')
            or node['id'] in blocked_nodes):
        return None
    from .versions import readable
    if not readable(brain,node,stamp,'history',library_id):
        return None
    connection = meta.get('connection_id')
    if (connection and connection not in allowed) or (not connection and not auth['allow_local']):
        return None
    evidence = meta.get('evidence') if isinstance(meta.get('evidence'), dict) else {}
    scope = auth['connection_scopes'].get(connection)
    if scope:
        from .ingestion import connected_session_id
        window = scope['window_id']
        if scope['policy'] != 'any' and (not window or node.get('session_id') != connected_session_id(connection, window)):
            return None
        if 'binding_revision' in evidence and evidence['binding_revision'] != scope['binding_revision']:
            return None
    source_scope = auth['source_scopes'].get(connection)
    if source_scope:
        if (evidence.get('source_id') != source_scope['source_id']
                or evidence.get('source_runtime_agent_id') != source_scope['runtime_agent_id']):
            return None
    elif evidence.get('source_id') or evidence.get('source_runtime_agent_id'):
        return None  # Registered-source evidence needs an explicit live identity.
    if evidence.get('archive_receipt_id') in blocked:
        return None
    record, reason = _record(brain, node, stamp, library_id,blocked_evidence=blocked_nodes,view='history')
    if reason:
        return None
    roles = _roles(node)
    # Historical imports have transport-owned role lists; never promote an
    # unknown imported speaker to the owner just because the prose says so.
    if meta.get('source') == 'history_import' and not roles:
        roles = {'unknown': node.get('text', '')}
    content = [{'role': role, 'text': text} for role, text in roles.items()
               if isinstance(text, str) and text]
    if not content:
        return None
    return {'id': node['id'], 'hash': fingerprint(node), 'content': content,
                    'connection_id': connection, 'session_id': node.get('session_id'),
                    'recorded_at': node.get('created'), 'source_kind': meta.get('source'),
                    'participant_scope': evidence.get('participant_scope', meta.get('participant_scope')),
                    'participant_id': evidence.get('participant_id', meta.get('participant_id')),
                    'source_id': evidence.get('source_id'), 'runtime_agent_id': evidence.get('source_runtime_agent_id'),
                    'total_chars': sum(len(part['text']) for part in content),
                    'label': node.get('label',''), 'revision': deepcopy(record.get('revision')),
                    'event_at': None if meta.get('source_time_unknown') else node.get('event_at',node.get('created'))}

def source_records(brain, library_id, auth, *, stamp=None):
    """Enumerate a finite authorized primary-source cohort once."""
    from .memory import _disabled_evidence
    auth = authorization(auth)
    if brain.meta.get('library_id') not in (None, library_id):
        raise ValidationError('目录快照不属于当前记忆库')
    blocked = _disabled_evidence(brain)
    records = []
    for node in brain.nodes.values():
        row = source_record(brain, node, library_id, auth, stamp=stamp, blocked_evidence=blocked, _validated_auth=True)
        if row is not None:
            records.append(row)
    return sorted(records, key=lambda row: (row['recorded_at'], row['id']))


def source_fragment(source, offset, limit=0):
    remaining = limit or source['total_chars']
    content = []
    cursor = 0
    consumed = 0
    for part in source['content']:
        size = len(part['text'])
        start = max(0, offset - cursor)
        if start < size and remaining:
            end = min(size, start + remaining)
            content.append({'role': part['role'], 'text': part['text'][start:end],
                            'offset': start, 'end': end, 'total': size})
            consumed += end - start
            remaining -= end - start
        cursor += size
    return {**{key: deepcopy(value) for key, value in source.items() if key not in ('content', 'total_chars')},
            'content': content, 'offset': offset, 'end': offset + consumed,
            'total_chars': source['total_chars']}


def validate_proposals(raw, fragments):
    """Only exact supplied quotes can support a proposal; no model-owned flags."""
    if (not isinstance(raw, dict) or set(raw) != {'proposals'}
            or not isinstance(raw['proposals'], list) or len(raw['proposals']) > 12):
        raise OrganizerError('回顾输出格式不正确，未保存提案', 'invalid_review_output')
    available = {item['id']: item for item in fragments}
    result = []
    for item in raw['proposals']:
        if not isinstance(item, dict) or set(item) - {'type', 'title', 'text', 'evidence', 'probe'}:
            raise OrganizerError('回顾提案包含未知字段', 'invalid_review_output')
        if item.get('type') not in PROPOSAL_TYPES:
            raise OrganizerError('回顾提案类型不正确', 'invalid_review_output')
        for field, maximum in (('title', 100), ('text', 4000)):
            if not isinstance(item.get(field), str) or not item[field].strip() or len(item[field]) > maximum:
                raise OrganizerError('回顾提案文字过长或为空', 'invalid_review_output')
        refs = item.get('evidence')
        if not isinstance(refs, list) or not 1 <= len(refs) <= 8:
            raise OrganizerError('回顾提案缺少逐字来源', 'invalid_review_output')
        evidence = []
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {'id', 'role', 'quote'}:
                raise OrganizerError('回顾提案证据格式不正确', 'invalid_review_output')
            source = available.get(ref.get('id')) if isinstance(ref.get('id'), str) else None
            quote = ref.get('quote')
            if (not source or not isinstance(quote, str) or not 4 <= len(quote) <= 2000
                    or not any(part['role'] == ref.get('role') and quote in part['text'] for part in source['content'])):
                raise OrganizerError('回顾提案引用未匹配本轮原文', 'invalid_review_output')
            evidence.append(deepcopy(ref))
        proposal = {'schema': SCHEMA, 'type': item['type'], 'title': item['title'].strip(),
                    'text': item['text'].strip(), 'evidence': evidence, 'status': 'pending',
                    'effectiveness': 'unverified', 'is_user_fact': False,
                    'is_real_experience': False, 'automatic_activation': False}
        if item['type'] == 'strategy_candidate':
            probe = item.get('probe')
            if not isinstance(probe, dict) or set(probe) != {'query', 'candidate_query', 'expected_source_ids'}:
                raise OrganizerError('策略候选需要可运行的查询回放', 'invalid_review_output')
            for field in ('query', 'candidate_query'):
                if not isinstance(probe[field], str) or not probe[field].strip() or len(probe[field]) > 300:
                    raise OrganizerError('策略回放查询格式不正确', 'invalid_review_output')
            ids = probe['expected_source_ids']
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 8
                    or any(not isinstance(nid, str) or nid not in available for nid in ids)):
                raise OrganizerError('策略回放目标须来自本轮真实证据', 'invalid_review_output')
            proposal['probe'] = deepcopy(probe)
        elif 'probe' in item:
            raise OrganizerError('只有策略候选可含检索回放', 'invalid_review_output')
        if item['type'] == 'simulation':
            proposal['hypothetical'] = True
            proposal['storage'] = 'review_only'
        result.append(proposal)
    return result


def replay_proposal(brain, library_id, auth, proposal):
    """Run retrieval, not a self score. These probes are not held-out evidence."""
    from ..organizer.state import semantic_recall, prepare_recall
    permitted = {row['id'] for row in source_records(brain, library_id, auth)}
    report = {'effectiveness': 'unverified', 'semantic_effectiveness': 'unverified', 'independent_evaluation': False,
              'probe_origin': 'proposal_not_held_out', 'model_parameters_changed': False,
              'strategy_activated': False, 'checks': {'evidence_current': all(ref['id'] in permitted for ref in proposal['evidence'])}}
    if proposal['type'] != 'strategy_candidate':
        return report
    probe = proposal['probe']
    prepared = prepare_recall(brain)
    before = semantic_recall(brain, probe['query'], k=8, candidate_ids=permitted, prepared=prepared)
    after = semantic_recall(brain, probe['candidate_query'], k=8, candidate_ids=permitted, prepared=prepared)
    a, b = ([hit['id'] for hit in result['hits']] for result in (before, after))
    targets = set(probe['expected_source_ids'])
    report['retrieval'] = {'baseline_ids': a, 'candidate_ids': b, 'expected_ids': sorted(targets),
                           'baseline_found': len(targets & set(a)), 'candidate_found': len(targets & set(b)),
                           'baseline_first_rank': min((a.index(nid) + 1 for nid in targets if nid in a), default=None),
                           'candidate_first_rank': min((b.index(nid) + 1 for nid in targets if nid in b), default=None)}
    leaks = sorted((set(a) | set(b)) - permitted)
    report['boundary'] = {'checked': True, 'restricted_to_authorized_current_evidence': True, 'leaked_ids': leaks}
    report['checks']['retrieval_boundary'] = not leaks
    return report


def revalidate_sources(brain, library_id, auth, expected, generation):
    auth = authorization(auth)
    if auth['generation'] != generation:
        raise OrganizerConflict('授权区域已经变化，未应用过时回顾')
    controls = brain.meta.get('memory_source_controls')
    if isinstance(controls,dict) and controls.get('schema') == 'love-house-source-controls/v1':
        current = {}
        for nid in expected:
            row = source_record(brain, brain.get(nid), library_id, auth, _validated_auth=True)
            if row is not None:current[nid] = row['hash']
    else:
        current = {row['id']: row['hash'] for row in source_records(brain, library_id, auth)}
    if not expected or any(current.get(nid) != digest for nid, digest in expected.items()):
        raise OrganizerConflict('回顾来源已更正、停用或删除，未应用过时回顾')


def apply_review_plan(brain, plan, current_authorization):
    """Host-only transactional action; rollback never recreates any content."""
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA:
        raise ValidationError('回顾操作格式不正确')
    library_id = plan.get('library_id')
    if brain.meta.get('library_id') not in (None, library_id):
        raise ValidationError('回顾操作不属于当前记忆库')
    nid = 'review_' + sha256(str(plan['proposal_id']).encode()).hexdigest()[:24]
    if plan.get('action') == 'rollback':
        node = brain.get(nid)
        if not node:
            return {'id': nid, 'changed': False, 'restored_content': False}
        if node.get('meta', {}).get('source') != 'idle_review' or node.get('meta', {}).get('review_proposal_id') != plan['proposal_id']:
            raise ValidationError('回顾撤回目标不正确')
        node['meta']['memory_disabled'] = True
        return {'id': nid, 'changed': True, 'restored_content': False}
    raise ValidationError('旧版回顾仅可撤回；不再生成或采纳新的派生建议')


def reflection_current(brain, node, library_id, stamp, *, blocked_evidence=None):
    """Live guard for every packet/catalog path, independently of SQLite state."""
    meta = node.get('meta', {})
    if (meta.get('review_schema') != REFLECTION_SCHEMA or meta.get('review_approved') is not True
            or meta.get('library_id') != library_id or meta.get('confirmed') is not False
            or meta.get('authorization_generation') != brain.meta.get('idle_review_current_authorization_generation')):
        return False
    revisions = meta.get('source_revisions')
    if not isinstance(revisions, dict) or not revisions:
        return False
    from .structured import _active
    from .memory import _disabled_evidence
    blocked = _disabled_evidence(brain) if blocked_evidence is None else blocked_evidence
    for nid, digest in revisions.items():
        source = brain.get(nid)
        if (nid in blocked or not source or source.get('meta', {}).get('source') not in SOURCE_KINDS
                or not _active(brain, source, stamp) or not brain._version_known(source, stamp)
                or source.get('meta', {}).get('library_id') not in (None, library_id)
                or fingerprint(source) != digest):
            return False
    return True
