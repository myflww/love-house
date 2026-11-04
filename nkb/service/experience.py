"""Read-only facts about explicitly connected windows and delivered memory.

No heartbeat, stored receipt or delivery is presented as model adoption. This
projection never changes a connection, reads provider secrets or calls a model.
"""
from __future__ import annotations

import time

from ..core.brain import Brain
from ..companion.structured import _record


def _stage(key, label, state, detail, *, at=None, count=None):
    value = {'id': key, 'label': label, 'state': state, 'detail': detail}
    if at is not None:
        value['at'] = at
    if count is not None:
        value['count'] = count
    return value


def experience_view(host, library_id):
    library = host.library(library_id)
    connections = host.connections.list(library_id)
    with host.organizer.db() as db:
        totals = {row['status']: row['count'] for row in db.execute(
            'SELECT status,COUNT(*) AS count FROM items WHERE library_id=? GROUP BY status', (library_id,))}
    result, brain = [], None
    for connection in connections:
        cid, revision = connection['id'], connection.get('binding_revision', 0)
        active = connection['enabled'] and not connection['revoked']
        policy = connection.get('session_scope_policy') or connection['session_scope']
        window = connection.get('bound_session_id')
        bound = bool(window) or policy == 'any'
        with host.connections.db() as db:
            latest = db.execute('''SELECT id,status,received,applied FROM receipts
                WHERE library_id=? AND connection_id=? AND binding_revision=? AND status!='forgotten'
                ORDER BY received DESC,id DESC LIMIT 1''', (library_id, cid, revision)).fetchone()
        capture = connection.get('capture', {})
        saved = sum(capture.get(key, 0) for key in
                    ('complete_dialogues_saved', 'tool_observations_saved', 'outputs_saved'))
        pending = capture.get('pending_records', 0)
        stages = [_stage('scope', '授权范围',
            'disconnected' if connection['revoked'] else 'paused' if not active else 'ready' if bound else 'waiting',
            '连接已断开' if connection['revoked'] else '连接已暂停' if not active else
            '仅限选定窗口' if window else '用户选择的整个连接范围' if policy == 'any' else '等待获准来源的首条消息')]
        stages.append(_stage('received', '收到来源', 'complete' if latest else 'waiting',
            '已收到来源记录' if latest else '尚未收到记录', at=latest['received'] if latest else None))
        stages.append(_stage('archived', '原文归档', 'complete' if latest else 'waiting',
            ('来源原文已持久保存；' + f'{saved} 条完整资料已写入记忆' +
             (f'，{pending} 条等待写入' if pending else '')) if latest else '等待来源原文',
            at=latest['received'] if latest else None))
        item_status = None
        if latest:
            with host.organizer.db() as db:
                item = db.execute('SELECT status FROM items WHERE library_id=? AND raw_id=?',
                                  (library_id, latest['id'])).fetchone()
                item_status = item['status'] if item else None
        labels = {'done': '最近一条来源已整理', 'pending': '最近一条来源等待整理',
                  'running': '最近一条来源正在整理', 'retry': '最近一条来源等待自动重试',
                  'failed': '最近一条来源需要检查', 'rejected': '最近一条来源已停止整理'}
        stages.append(_stage('organized', '记忆整理', 'complete' if item_status == 'done' else
            'pending' if item_status in ('pending', 'running', 'retry') else 'attention' if item_status == 'failed' else 'waiting',
            labels.get(item_status, '最近来源尚无整理记录；原文保存与整理分开进行')))
        recall = connection.get('last_recall')
        provided_count = sum(recall.get(key, 0) for key in ('organized_count', 'source_count', 'other_count')) if recall else 0
        stages.append(_stage('provided', '提供记忆', 'complete' if provided_count else 'empty' if recall else 'waiting',
            '已向运行程序提供记忆材料，尚未证明模型采纳' if provided_count else
            '取回请求已完成，本次没有匹配的记忆条目' if recall else '尚无本连接的取回记录',
            at=recall['at'] if recall else None,
            count=provided_count))
        delivery = None
        delivery_available = host.usage is not None
        if host.usage is not None and hasattr(host.usage, 'latest_delivery'):
            try:
                delivery = host.usage.latest_delivery(library_id, cid, binding_revision=revision)
            except Exception:
                delivery_available = False
        memory = []
        if delivery and active:
            if brain is None:
                brain = Brain(host.snapshot(library_id))
            for nid in delivery['node_ids']:
                node = brain.nodes.get(nid)
                if (node and not node.get('superseded_by') and not node.get('meta', {}).get('memory_disabled')
                        and not node.get('meta', {}).get('forgotten')
                        and not _record(brain,node,time.time(),library_id)[1]):
                    memory.append({'id': nid, 'label': node.get('label', ''), 'kind': node.get('kind', ''),
                                   'provided_at': delivery['issued_at']})
        result.append({'id': cid, 'name': connection['name'], 'host': connection['host'],
            'scope': {'library_id': library_id, 'policy': policy, 'window_id': window,
                      'binding_revision': revision}, 'enabled': active,
            'last_received_at': connection.get('last_received_at'), 'stages': stages,
            'recent_delivery': {'id': delivery['id'], 'session_id': delivery['session_id'],
                                'at': delivery['issued_at'], 'items': memory,
                                'unavailable_count': len(delivery['node_ids']) - len(memory)} if delivery and active else None,
            'delivery_record_available': delivery_available, 'model_adoption_verified': False})
    return {'schema': 'love-house-memory-experience/v1', 'read_only': True,
            'library': {'id': library_id, 'name': library['name'], 'is_demo': library['is_demo']},
            'connections': result, 'organizer_library_counts': totals,
            'model_calls': 0, 'scope_changed': False, 'generated_at': time.time()}
