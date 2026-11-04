"""Incremental, leased local organization of already authorized source records.

Snapshots contain both the graph and server-owned authorization. The host
revalidates each short metadata commit under its binding and graph locks.
This worker calls no model and stores neither full source text nor credentials.
"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import base64
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from ..core.brain import Brain
from ..errors import ValidationError
from ..companion.review import (SCHEMA, authorization, get_review_profile, source_records,
    source_record)
from .model import (OrganizerError, OrganizerConflict)

# Kept as an import-compatible marker for old integrations. This worker never
# sends a prompt or calls a provider: ordinary Organizer owns model summaries.
GUIDANCE = '空闲整理只维护已授权原文的目录，不生成行为建议、不调用模型。'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _message(code):
    return {'stale_input': '原文或授权已变化，未保存过时目录',
            'directory_interrupted': '目录整理中断，未完成的原文保留待重试',
            'directory_storage_error': '目录暂未完成，原始记忆保留，可稍后重试'}.get(code, '目录暂未完成，原始记忆保留')


class IdleReviewer:
    LEASE_SECONDS = 90
    HEARTBEAT_SECONDS = 10

    def __init__(self, data_dir, *, snapshot, apply, credential, transport=None, finalize=None, idle_check=None):
        self.path = Path(data_dir) / 'idle-review.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.snapshot, self.apply, self.credential = snapshot, apply, credential
        self.transport = transport  # Legacy signature only; never invoked.
        self.idle_check = idle_check
        self.finalize = finalize
        self._stopping = threading.Event()
        self._stop_requested = threading.Event()
        self._commit_lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS review_epochs(library_id TEXT PRIMARY KEY,value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS review_leases(library_id TEXT PRIMARY KEY,owner TEXT NOT NULL,
                    expires REAL NOT NULL,heartbeat REAL NOT NULL,epoch INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS review_sources(library_id TEXT,source_id TEXT,source_hash TEXT,
                    generation TEXT,offset INTEGER,total INTEGER,updated REAL,
                    PRIMARY KEY(library_id,source_id,source_hash,generation));
                CREATE TABLE IF NOT EXISTS review_proposals(id TEXT PRIMARY KEY,library_id TEXT,
                    source_hashes TEXT,generation TEXT,proposal_json TEXT,status TEXT,node_id TEXT,created REAL);
                CREATE INDEX IF NOT EXISTS review_proposals_library ON review_proposals(library_id,created);
                CREATE TABLE IF NOT EXISTS review_retry(library_id TEXT PRIMARY KEY,attempts INTEGER,
                    next_run REAL,chunk_chars INTEGER,error_code TEXT);
                CREATE TABLE IF NOT EXISTS source_directory(library_id TEXT,source_id TEXT,source_hash TEXT,
                    generation TEXT,context_hash TEXT,entry_json TEXT,updated REAL,PRIMARY KEY(library_id,source_id));
                CREATE INDEX IF NOT EXISTS source_directory_order ON source_directory(library_id,generation,source_id);
                CREATE TABLE IF NOT EXISTS review_tombstones(library_id TEXT,item_id TEXT,
                    PRIMARY KEY(library_id,item_id));
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _library(value):
        if not isinstance(value, str) or not value or len(value) > 200:
            raise ValidationError('回顾缺少稳定记忆库ID')
        return value

    def _snapshot(self, library_id):
        value = self.snapshot(library_id)
        if not isinstance(value, dict) or set(value) != {'brain', 'authorization'}:
            raise ValidationError('回顾快照须原子包含记忆库和当前授权')
        raw = value['brain']
        brain = Brain(raw.to_dict() if isinstance(raw, Brain) else deepcopy(raw))
        auth = authorization(value['authorization'])
        # This runtime-only value cannot be inferred from a saved graph.
        brain.meta['idle_review_current_authorization_generation'] = auth['generation']
        return brain, auth

    @staticmethod
    def _epoch(db, library_id):
        row = db.execute('SELECT value FROM review_epochs WHERE library_id=?', (library_id,)).fetchone()
        return row[0] if row else 0

    def _inventory(self, library_id, brain, auth):
        rows = source_records(brain, library_id, auth)
        with self.db() as db:
            blocked = {row[0] for row in db.execute('SELECT item_id FROM review_tombstones WHERE library_id=?', (library_id,))}
            ready = {row['source_id']: (row['source_hash'], row['generation'], row['context_hash'])
                     for row in db.execute('SELECT source_id,source_hash,generation,context_hash FROM source_directory WHERE library_id=?', (library_id,))}
        rows = [row for row in rows if row['id'] not in blocked]
        entries = self._entries(rows, auth)
        pending = [row for row in entries if ready.get(row['id']) != (row['hash'], auth['generation'], row['context_hash'])]
        return entries, pending

    @staticmethod
    def _entries(rows, auth):
        groups = {}
        for row in rows:
            groups.setdefault((row['connection_id'], row['session_id']), []).append(row)
        entries = []
        for group in groups.values():
            for i, row in enumerate(group):
                previous = group[i-1]['id'] if i else None
                following = group[i+1]['id'] if i+1 < len(group) else None
                value = {key: deepcopy(row.get(key)) for key in ('id','hash','label','connection_id','session_id',
                    'recorded_at','event_at','source_kind','participant_scope','participant_id','source_id','runtime_agent_id','revision')}
                value.update(roles=[part['role'] for part in row['content']], chars=row['total_chars'],
                    previous_id=previous, next_id=following, content_is_original=False,
                    read_tool='memory_read', read_arguments={'memory_id': row['id'], 'view': 'history'})
                value['context_hash'] = sha256(_json([row['hash'], previous, following]).encode()).hexdigest()
                entries.append(value)
        return sorted(entries, key=lambda row: (row['recorded_at'], row['id']))

    def _claim(self, library_id):
        stamp, owner = time.time(), uuid.uuid4().hex
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM review_leases WHERE library_id=?', (library_id,)).fetchone()
            if current and current['expires'] > stamp:
                return None
            epoch = self._epoch(db, library_id)
            db.execute('INSERT INTO review_leases VALUES(?,?,?,?,?) ON CONFLICT(library_id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires,heartbeat=excluded.heartbeat,epoch=excluded.epoch',
                       (library_id, owner, stamp + self.LEASE_SECONDS, stamp, epoch))
        return {'library_id': library_id, 'owner': owner, 'epoch': epoch}

    def _owned(self, db, lease):
        row = db.execute('SELECT * FROM review_leases WHERE library_id=?', (lease['library_id'],)).fetchone()
        return (not self._stopping.is_set() and row and row['owner'] == lease['owner']
                and row['expires'] > time.time() and row['epoch'] == lease['epoch']
                and self._epoch(db, lease['library_id']) == lease['epoch'])

    def _check_owned(self, lease):
        with self.db() as db:
            if not self._owned(db, lease):
                raise OrganizerConflict('回顾租约或授权已变化，未保存迟到结果')

    @contextmanager
    def _commit_guard(self, lease, *, proposal_id=None, status=None, node_id=None):
        """Enter only after host binding/graph locks, never before those locks."""
        with self._commit_lock:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not self._owned(db, lease):
                    raise OrganizerConflict('回顾租约已失效，未写入图谱')
                if proposal_id and not db.execute('SELECT 1 FROM review_proposals WHERE library_id=? AND id=?',
                                                 (lease['library_id'], proposal_id)).fetchone():
                    raise OrganizerConflict('回顾提案已清除，未写入图谱')
                yield
                # The host has now persisted. The SQL write lock fenced all
                # claim/epoch changes, while stop waits on _commit_lock. Lease
                # wall-clock expiry cannot retroactively reject that commit.
                row = db.execute('SELECT owner,epoch FROM review_leases WHERE library_id=?', (lease['library_id'],)).fetchone()
                if not row or row['owner'] != lease['owner'] or row['epoch'] != lease['epoch']:
                    raise RuntimeError('review lease changed inside fenced commit')
                if proposal_id:
                    db.execute('UPDATE review_proposals SET status=?,node_id=? WHERE library_id=? AND id=?',
                               (status, node_id, lease['library_id'], proposal_id))

    @contextmanager
    def _heartbeat(self, lease):
        done = threading.Event()
        def beat():
            while not done.wait(self.HEARTBEAT_SECONDS):
                try:
                    with self.db() as db:
                        if not self._owned(db, lease):
                            return
                        db.execute('UPDATE review_leases SET expires=?,heartbeat=? WHERE library_id=? AND owner=?',
                                   (time.time() + self.LEASE_SECONDS, time.time(), lease['library_id'], lease['owner']))
                except sqlite3.Error:
                    return
        thread = threading.Thread(target=beat, name='love-house-review-heartbeat', daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join(timeout=1)

    def _release(self, lease):
        with self.db() as db:
            db.execute('DELETE FROM review_leases WHERE library_id=? AND owner=?', (lease['library_id'], lease['owner']))

    def status(self, library_id, *, cursor=None, limit=25):
        library_id = self._library(library_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError('回顾每页数量须为1~100的整数')
        brain, auth = self._snapshot(library_id)
        all_rows, pending = self._inventory(library_id, brain, auth)
        current = {row['id']: row['hash'] for row in all_rows}
        with self.db() as db:
            db.execute('BEGIN')
            available = []
            for row in db.execute('''SELECT id,source_hashes,generation,status,node_id,created FROM review_proposals
                    WHERE library_id=? ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 ELSE 2 END,created DESC,id''', (library_id,)):
                hashes = json.loads(row['source_hashes'])
                if row['generation'] != auth['generation'] or any(current.get(nid) != digest for nid, digest in hashes.items()):
                    continue
                available.append(dict(row))
            revision = sha256(_json([library_id, auth['generation'], available]).encode()).hexdigest()
            offset = 0
            if cursor is not None:
                try:
                    if not isinstance(cursor, str) or len(cursor) > 1024:
                        raise ValueError()
                    decoded = json.loads(base64.urlsafe_b64decode(cursor.encode('ascii') + b'=' * (-len(cursor) % 4)))
                    if (set(decoded) != {'library_id', 'revision', 'offset'} or decoded['library_id'] != library_id
                            or decoded['revision'] != revision or type(decoded['offset']) is not int
                            or not 0 <= decoded['offset'] <= len(available)):
                        raise ValueError()
                    offset = decoded['offset']
                except (ValueError, TypeError, KeyError, UnicodeError):
                    raise ValidationError('回顾分页已变化，请重新加载第一页') from None
            proposals = []
            for summary in available[offset:offset + limit]:
                row = db.execute('SELECT * FROM review_proposals WHERE id=? AND library_id=?', (summary['id'], library_id)).fetchone()
                item = json.loads(row['proposal_json'])
                item.update(id=row['id'], status=row['status'], node_id=row['node_id'], can_accept=False, legacy=True)
                proposals.append(item)
            retry = db.execute('SELECT * FROM review_retry WHERE library_id=?', (library_id,)).fetchone()
            lease = db.execute('SELECT * FROM review_leases WHERE library_id=?', (library_id,)).fetchone()
        next_offset = offset + len(proposals)
        next_cursor = (base64.urlsafe_b64encode(_json({'library_id': library_id, 'revision': revision,
                       'offset': next_offset}).encode()).decode().rstrip('=') if next_offset < len(available) else None)
        pending_ids={row['id'] for row in pending}
        directory_entries=[row for row in all_rows if row['id'] not in pending_ids][:25]
        return {'schema': SCHEMA, 'library_id': library_id, 'profile': get_review_profile(brain),
                'mode': 'organization', 'model_called': False, 'new_proposals_enabled': False,
                'counts': {'eligible': len(all_rows), 'pending': len(pending), 'processed': len(all_rows) - len(pending),
                           'directory_ready': len(all_rows) - len(pending), 'directory_pending': len(pending), 'proposals': len(available),
                           'pending_proposals': sum(row['status'] == 'pending' for row in available)},
                'running': bool(lease and lease['expires'] > time.time()), 'proposals': proposals,
                'directory_entries': directory_entries, 'directory_coverage': 'currently_authorized_primary_sources',
                'directory_complete_library': False, 'summary_status': 'managed_by_organizer',
                'total': len(available), 'offset': offset, 'next_cursor': next_cursor, 'revision': revision,
                'last_error': {'code': retry['error_code'], 'message': _message(retry['error_code'])} if retry and retry['error_code'] else None,
                'next_run': retry['next_run'] if retry else None, 'effectiveness': 'unverified', 'automatic_activation': False}

    def preview(self, library_id):
        library_id = self._library(library_id)
        result = self.status(library_id)
        brain, auth = self._snapshot(library_id)
        _, pending = self._inventory(library_id, brain, auth)
        result.update(read_only=True, model_called=False,
                      sources=[{'id': row['id'], 'hash': row['hash'], 'connection_id': row['connection_id'],
                                'session_id': row['session_id'], 'chars': row['chars'], 'processed_chars': 0}
                               for row in pending[:get_review_profile(brain)['batch_size']]],
                      source_count=len(pending), authorization_generation=auth['generation'])
        return result

    def directory(self, library_id, *, cursor=None, limit=25, brain=None, authorization=None):
        """Read at most one directory page, rechecking only its current sources.

        The host can pass its locked live Brain/authority to avoid graph copies.
        A directory is a navigation index; memory_read owns full-text delivery.
        """
        library_id=self._library(library_id)
        if type(limit) is not int or not 1<=limit<=100:
            raise ValidationError('目录每页数量须为1~100的整数')
        if (brain is None)!=(authorization is None):
            raise ValidationError('目录读取须同时提供当前图谱和授权')
        if brain is None:
            brain,auth=self._snapshot(library_id)
        else:
            from ..companion.review import authorization as validate_authorization
            auth=validate_authorization(authorization)
        result={'schema':'love-house-source-directory/v1','library_id':library_id,'entries':[],
            'read_only':True,'model_called':False,'memory_use_recorded':False,
            'coverage':'currently_authorized_primary_sources','complete_library':False,
            'read_tool':'memory_read','fallback_tool':'memory_list','next_cursor':None,
            'status':'pending','indexed_records':0,'stale_on_page':0}
        controls=brain.meta.get('memory_source_controls')
        if (brain.meta.get('library_id') not in (None,library_id) or not isinstance(controls,dict)
                or controls.get('schema')!='love-house-source-controls/v1'
                or not isinstance(controls.get('blocked_by'),dict)):
            return {**result,'reason':'source_controls_not_ready'}
        with self.db() as db:
            summary=db.execute('SELECT COUNT(*) AS total,MAX(updated) AS changed FROM source_directory WHERE library_id=? AND generation=?',
                               (library_id,auth['generation'])).fetchone()
            revision=sha256(_json([library_id,auth['generation'],summary['total'],summary['changed'],self._epoch(db,library_id),controls.get('generation')]).encode()).hexdigest()
            after=''
            if cursor is not None:
                try:
                    if not isinstance(cursor,str) or not cursor or len(cursor)>2048:raise ValueError()
                    decoded=json.loads(base64.urlsafe_b64decode(cursor.encode('ascii')+b'='*(-len(cursor)%4)))
                    if (set(decoded)!={'library_id','revision','after'} or decoded['library_id']!=library_id
                            or decoded['revision']!=revision or not isinstance(decoded['after'],str)
                            or len(decoded['after'])>300):raise ValueError()
                    after=decoded['after']
                except (ValueError,TypeError,KeyError,UnicodeError):
                    raise ValidationError('目录分页已变化，请重新读取第一页') from None
            rows=db.execute('SELECT source_id,source_hash,entry_json FROM source_directory WHERE library_id=? AND generation=? AND source_id>? ORDER BY source_id LIMIT ?',
                (library_id,auth['generation'],after,limit+1)).fetchall()
        entries=[]
        for row in rows[:limit]:
            current=source_record(brain,brain.get(row['source_id']),library_id,auth,_validated_auth=True)
            if not current or current['hash']!=row['source_hash']:
                result['stale_on_page']+=1
                continue
            entry=json.loads(row['entry_json'])
            # A neighbor is offered only while it remains in this same permitted
            # conversation. Changed/deleted neighbors are not a back door.
            for field in ('previous_id','next_id'):
                nid=entry.get(field)
                neighbor=source_record(brain,brain.get(nid),library_id,auth,_validated_auth=True) if nid else None
                if not neighbor or (neighbor['connection_id'],neighbor['session_id'])!=(current['connection_id'],current['session_id']):
                    entry[field]=None
            entries.append(entry)
        if len(rows)>limit:
            result['next_cursor']=base64.urlsafe_b64encode(_json({'library_id':library_id,'revision':revision,
                'after':rows[limit-1]['source_id']}).encode()).decode().rstrip('=')
        return {**result,'entries':entries,'indexed_records':summary['total'],'revision':revision,
            'status':'ready' if entries else 'pending','reason':None if entries else 'directory_not_ready',
            'available_on_page':len(entries)}

    def invalidate_directory(self, library_id):
        """Invalidate derived navigation only; legacy review history stays intact."""
        library_id=self._library(library_id)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO review_epochs VALUES(?,1) ON CONFLICT(library_id) DO UPDATE SET value=value+1',(library_id,))
            db.execute('DELETE FROM review_leases WHERE library_id=?',(library_id,))
            db.execute('DELETE FROM source_directory WHERE library_id=?',(library_id,))
        return {'library_id':library_id,'directory_invalidated':True,'legacy_history_preserved':True}

    def run_once(self, library_id, *, manual=True, idle_for=None):
        """Maintain one finite cohort locally, without provider calls or new memories."""
        library_id = self._library(library_id)
        if type(manual) is not bool:
            raise ValidationError('manual须为布尔值')
        if self._stopping.is_set():
            return {'status': 'paused', 'library_id': library_id}
        brain, auth = self._snapshot(library_id)
        settings = get_review_profile(brain)
        if not manual and not settings['enabled']:
            return {'status': 'paused', 'library_id': library_id}
        all_rows, pending = self._inventory(library_id, brain, auth)
        if not pending:
            return {'status': 'waiting', 'library_id': library_id, 'remaining': 0, 'model_called': False}
        if self.finalize is None:
            raise ValidationError('目录尚未接入宿主原子提交保护，未改动记忆')
        if not manual:
            idle_for = time.time() - max((row['recorded_at'] for row in all_rows), default=time.time()) if idle_for is None else idle_for
            if type(idle_for) not in (int, float) or idle_for < settings['idle_seconds']:
                return {'status': 'waiting_idle', 'library_id': library_id}
        with self.db() as db:
            retry = db.execute('SELECT * FROM review_retry WHERE library_id=?', (library_id,)).fetchone()
        if not manual and retry and retry['next_run'] > time.time():
            return {'status': 'retry', 'library_id': library_id, 'next_run': retry['next_run']}
        lease = self._claim(library_id)
        if not lease:
            return {'status': 'busy', 'library_id': library_id}
        processed = 0
        try:
            with self._heartbeat(lease):
                hashes = {row['id']:row['hash'] for row in all_rows}
                # Collect once; release host graph/binding locks between short
                # local transactions so an active conversation can take over.
                for start in range(0, len(pending), 256):
                    if self._stop_requested.is_set() or not manual and self.idle_check and not self.idle_check(library_id, settings['idle_seconds']):
                        break
                    chunk = pending[start:start+256]
                    dependencies = {nid for row in chunk for nid in (row['id'],row['previous_id'],row['next_id']) if nid}
                    expected = {nid:hashes[nid] for nid in dependencies}
                    def commit():
                        with self._commit_lock:
                            with self.db() as db:
                                db.execute('BEGIN IMMEDIATE')
                                if not self._owned(db, lease):
                                    raise OrganizerConflict()
                                for offset in range(0,len(chunk),settings['batch_size']):
                                    group=chunk[offset:offset+settings['batch_size']]
                                    db.executemany('INSERT INTO source_directory VALUES(?,?,?,?,?,?,?) ON CONFLICT(library_id,source_id) DO UPDATE SET source_hash=excluded.source_hash,generation=excluded.generation,context_hash=excluded.context_hash,entry_json=excluded.entry_json,updated=excluded.updated',
                                        [(library_id,row['id'],row['hash'],auth['generation'],row['context_hash'],_json(row),time.time()) for row in group])
                                db.execute('UPDATE review_retry SET attempts=0,next_run=0,error_code=NULL WHERE library_id=?',(library_id,))
                        return len(chunk)
                    processed += self.finalize(library_id, expected, auth['generation'], commit)
                return {'status': 'done' if processed == len(pending) else 'paused', 'library_id': library_id,
                    'processed_sources': processed, 'remaining': len(pending)-processed,
                    'directory_ready': len(all_rows)-len(pending)+processed, 'proposals_created': 0,
                    'model_called': False, 'model_calls': 0, 'graph_changed': False}
        except OrganizerError as error:
            self._failure(library_id, lease, error.code)
            return {'status': 'stale' if error.code == 'stale_input' else 'retry', 'library_id': library_id,
                    'error': {'code': error.code, 'message': _message(error.code)}, 'progress_advanced': bool(processed),
                    'processed_sources':processed,'remaining':len(pending)-processed, 'model_called': False}
        except Exception:
            self._failure(library_id, lease, 'directory_storage_error')
            return {'status': 'retry', 'library_id': library_id,
                    'error': {'code': 'directory_storage_error', 'message': _message('directory_storage_error')},
                    'progress_advanced': bool(processed), 'processed_sources':processed,
                    'remaining':len(pending)-processed, 'model_called': False}
        finally:
            self._release(lease)

    def _failure(self, library_id, lease, code):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._owned(db, lease):
                return
            prior = db.execute('SELECT * FROM review_retry WHERE library_id=?', (library_id,)).fetchone()
            attempts = (prior['attempts'] if prior else 0)+1
            db.execute('INSERT INTO review_retry VALUES(?,?,?,?,?) ON CONFLICT(library_id) DO UPDATE SET attempts=excluded.attempts,next_run=excluded.next_run,error_code=excluded.error_code',
                (library_id, attempts, time.time()+min(300,5*2**min(6,attempts-1)),0,code))

    def run_pending(self, library_id, *, manual=True, idle_for=None):
        # run_once drains a finite snapshot rather than re-snapshotting every six
        # records. Late arrivals belong to the next cohort.
        return {**self.run_once(library_id, manual=manual, idle_for=idle_for), 'rounds': 1}

    def decide(self, library_id, proposal_id, action):
        library_id = self._library(library_id)
        if action not in ('reject', 'rollback') or not isinstance(proposal_id, str) or len(proposal_id) > 200:
            raise ValidationError('旧版回顾记录只供查看、拒绝或撤回；不再新增采纳')
        lease = self._claim(library_id)
        if not lease:
            return {'status': 'busy', 'library_id': library_id}
        try:
            with self._heartbeat(lease):
                with self.db() as db:
                    row = db.execute('SELECT * FROM review_proposals WHERE library_id=? AND id=?', (library_id, proposal_id)).fetchone()
                if not row:
                    raise ValidationError('回顾提案不存在或已清除')
                if action == 'reject':
                    if row['status'] != 'pending':
                        raise ValidationError('仅待审提案可拒绝')
                    result = {'changed': True}
                    status = 'rejected'
                    with self._commit_guard(lease, proposal_id=proposal_id, status=status, node_id=row['node_id']):
                        pass
                else:
                    if row['status'] not in ('accepted', 'rolled_back'):
                        raise ValidationError('只有已采纳回顾可撤回')
                    proposal = json.loads(row['proposal_json'])
                    self._check_owned(lease)
                    # No SQLite transaction spans the host's binding/graph lock.
                    plan = {'schema': SCHEMA, 'library_id': library_id, 'proposal_id': proposal_id, 'action': action,
                            'proposal': proposal, 'source_hashes': json.loads(row['source_hashes']),
                            'authorization_generation': row['generation']}
                    status = 'rolled_back'
                    node_id = 'review_' + sha256(proposal_id.encode()).hexdigest()[:24]
                    result = self.apply(library_id, deepcopy(plan), commit_guard=lambda: self._commit_guard(
                        lease, proposal_id=proposal_id, status=status, node_id=node_id))
                with self.db() as db:
                    current = db.execute('SELECT status FROM review_proposals WHERE library_id=? AND id=?', (library_id, proposal_id)).fetchone()
                return {'status': status, 'library_id': library_id, 'proposal_id': proposal_id,
                        'result': result, 'history_current': bool(current and current['status'] == status)}
        finally:
            self._release(lease)

    def invalidate(self, library_id, *, forgotten_ids=()):
        """Call after a binding change or library forget, outside host locks.

        Copies are cleared conservatively for the whole library. Explicit
        tombstones outlive re-enumeration; ordinary invalidation allows review
        of newly authorized material under its new generation.
        """
        library_id = self._library(library_id)
        ids = list(forgotten_ids)
        if any(not isinstance(nid, str) or not nid or len(nid) > 300 for nid in ids):
            raise ValidationError('回顾遗忘ID格式不正确')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO review_epochs VALUES(?,1) ON CONFLICT(library_id) DO UPDATE SET value=value+1', (library_id,))
            for table in ('review_leases', 'review_sources', 'review_proposals', 'review_retry', 'source_directory'):
                db.execute('DELETE FROM ' + table + ' WHERE library_id=?', (library_id,))
            db.executemany('INSERT OR IGNORE INTO review_tombstones VALUES(?,?)', [(library_id, nid) for nid in ids])
        with self.db() as db:
            checkpointed = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
        return {'library_id': library_id, 'cleared': True, 'checkpointed': checkpointed, 'forgotten': len(set(ids))}

    def forget(self, library_id, raw_ids, node_ids=None):
        return self.invalidate(library_id, forgotten_ids=[*raw_ids, *(node_ids or [])])

    def cancel(self, library_id):
        """Stop in-flight work while preserving review/rollback history."""
        library_id = self._library(library_id)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO review_epochs VALUES(?,1) ON CONFLICT(library_id) DO UPDATE SET value=value+1', (library_id,))
            db.execute('DELETE FROM review_leases WHERE library_id=?', (library_id,))
            db.execute('DELETE FROM review_retry WHERE library_id=?', (library_id,))
        return {'library_id': library_id, 'cancelled': True, 'proposals_preserved': True}

    def stop(self):
        self._stop_requested.set()
        with self._commit_lock:
            self._stopping.set()
