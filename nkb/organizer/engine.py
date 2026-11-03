"""Durable queue. Snapshot/apply callbacks own library locks; model I/O owns neither."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from ..core.brain import Brain
from ..errors import ValidationError
from .config import get_profile
from .model import (OrganizerConflict, OrganizerError, call_model, failure_message,
                    resolve_model, transport as default_transport)
from .state import build_input, context_input_bytes, validate_plan, raw_node, disabled, archive_roles, RAW_SOURCES, _roles, _persona_roles, persona_result_view, relation_result_view


class Organizer:
    def __init__(self, data_dir, *, snapshot, apply, credential, transport=None, read_archive=None):
        self.path = Path(data_dir) / "organizer.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.snapshot, self.apply, self.credential = snapshot, apply, credential
        self.transport = transport or default_transport
        self.read_archive = read_archive
        self._run_lock = threading.Lock()
        self._stopping = threading.Event()
        self._thread = None
        self._active_job = None
        self._last_auto_library = None
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS items(library_id TEXT,raw_id TEXT,status TEXT,progress TEXT,
                  job_id TEXT,created REAL,PRIMARY KEY(library_id,raw_id));
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,library_id TEXT,raw_ids TEXT,status TEXT,
                  attempts INTEGER,next_run REAL,lease_until REAL,created REAL,updated REAL,
                  input_json TEXT,guards_json TEXT,plan_json TEXT,result_json TEXT,error_code TEXT,error TEXT);
                CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status,next_run);
                CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,library_id TEXT,at REAL,chars INTEGER);
                CREATE TABLE IF NOT EXISTS tombstones(library_id TEXT,kind TEXT,item_id TEXT,at REAL,
                  PRIMARY KEY(library_id,kind,item_id));
                CREATE TABLE IF NOT EXISTS epochs(library_id TEXT PRIMARY KEY,value INTEGER);
                CREATE TABLE IF NOT EXISTS drain_items(library_id TEXT,raw_id TEXT,created REAL,
                  PRIMARY KEY(library_id,raw_id));
            ''')
            if 'purpose' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
                db.execute("ALTER TABLE jobs ADD COLUMN purpose TEXT NOT NULL DEFAULT 'memory'")
            self._recover_jobs(db, time.time())
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db: yield db
        finally: db.close()

    @staticmethod
    def _library(value):
        if not isinstance(value, str) or not value or len(value) > 200:
            raise ValidationError("整理任务缺少稳定记忆库ID")
        return value

    def enqueue(self, library_id, raw_ids):
        library_id = self._library(library_id)
        if not isinstance(raw_ids, list) or len(raw_ids) > 1000 or any(not isinstance(i, str) or not i or len(i) > 300 for i in raw_ids):
            raise ValidationError("raw_ids须为最多1000个有界原文/receipt ID")
        added = 0
        with self.db() as db:
            for rid in dict.fromkeys(raw_ids):
                if db.execute("SELECT 1 FROM tombstones WHERE library_id=? AND item_id=?",(library_id,rid)).fetchone():
                    continue
                added += db.execute("INSERT OR IGNORE INTO items VALUES(?,?,'pending','{}',NULL,?)",
                                    (library_id, rid, time.time())).rowcount
        return {"queued": added, "duplicate": added == 0, "library_id": library_id}

    @staticmethod
    def _epoch(db, library_id):
        row = db.execute("SELECT value FROM epochs WHERE library_id=?",(library_id,)).fetchone()
        return row[0] if row else 0

    def _valid_job(self, db, job):
        row = db.execute("SELECT status FROM jobs WHERE id=?",(job["id"],)).fetchone()
        return (not self._stopping.is_set() and row is not None and row[0] == "running"
                and self._epoch(db,job["library_id"]) == job["_epoch"])

    def _deleted(self, library_id, ids, brain):
        return bool(self._deleted_ids(library_id, ids, brain))

    def _deleted_ids(self, library_id, ids, brain):
        with self.db() as db:
            deleted = {r[0] for r in db.execute("SELECT item_id FROM tombstones WHERE library_id=?",(library_id,))}
        invalid = set()
        for rid in ids:
            node = raw_node(brain, rid)
            if node is None or disabled(node) or rid in deleted or node['id'] in deleted:
                invalid.add(rid)
        return invalid

    def _snapshot(self, library_id):
        data = self.snapshot(library_id)
        if isinstance(data, Brain): data = data.to_dict()
        if not isinstance(data, dict): raise OrganizerError("无法读取本库快照", "snapshot_failed")
        return Brain(deepcopy(data))

    def _budget(self, db, library_id):
        row = db.execute("SELECT COUNT(*) AS count,COALESCE(SUM(chars),0) AS chars FROM calls WHERE library_id=? AND at>?",
                         (library_id, time.time() - 86400)).fetchone()
        return dict(row)

    @staticmethod
    def _retry_delay(attempts):
        # Attempts are diagnostic history, not a lifetime retry limit. Bound
        # the exponent too: years of failures must not create huge integers.
        return min(300, 5 * 2 ** min(6, max(0, attempts - 1)))

    @staticmethod
    def _recover_jobs(db, stamp):
        """Resume memory failures, leaving explicit persona/privacy boundaries intact."""
        db.execute("UPDATE jobs SET status='failed',error_code='interrupted',error='快速人格任务中断，请明确重试' WHERE purpose='persona' AND status='running' AND lease_until<?", (stamp,))
        db.execute("UPDATE jobs SET status='retry',next_run=?,error_code='interrupted',error='进程中断，等待安全重试' WHERE purpose='memory' AND status='running' AND lease_until<?", (stamp, stamp))
        # Recover the old max_attempts terminal state only while this job still
        # owns unfinished memory items. Source deletion has a separate verified
        # repair path; rejected/cancelled/completed jobs never enter this path.
        db.execute("""UPDATE jobs SET status='retry',next_run=MIN(COALESCE(next_run,0),?),lease_until=0
                      WHERE purpose='memory' AND status='failed'
                      AND COALESCE(error_code,'') NOT IN ('source_deleted','privacy_deleted','cancelled')
                      AND EXISTS (SELECT 1 FROM items i WHERE i.job_id=jobs.id AND i.library_id=jobs.library_id
                                  AND i.status IN ('failed','retry','running'))""", (stamp,))
        db.execute("UPDATE items SET status='retry' WHERE status IN ('running','failed') AND job_id IN (SELECT id FROM jobs WHERE purpose='memory' AND status='retry')")

    def _settle_aliases(self, library_id, brain):
        from ..companion.dedup import is_duplicate
        def alias(rid):
            node=raw_node(brain,rid)
            return node is not None and is_duplicate(node,brain)
        with self.db() as db:
            for row in db.execute("SELECT raw_id FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL",(library_id,)).fetchall():
                if alias(row['raw_id']):db.execute("UPDATE items SET status='done_alias' WHERE library_id=? AND raw_id=?",(library_id,row['raw_id']))
            for job in db.execute("SELECT id,raw_ids FROM jobs WHERE library_id=? AND status IN ('retry','failed')",(library_id,)).fetchall():
                ids=json.loads(job['raw_ids'])
                if ids and all(alias(rid) for rid in ids):
                    db.execute("UPDATE jobs SET status='aliased',updated=?,input_json=NULL,guards_json=NULL,plan_json=NULL,result_json=?,error_code=NULL,error=NULL WHERE id=?",(time.time(),json.dumps({'model_called':False,'confirmed_aliases':len(ids)}),job['id']))
                    db.execute("UPDATE items SET status='done_alias',job_id=NULL WHERE job_id=?",(job['id'],))

    def _trigger(self, db, library_id, profile):
        pending=db.execute("SELECT COUNT(*) FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL",(library_id,)).fetchone()[0]
        cohort=db.execute("SELECT COUNT(*) FROM drain_items d JOIN items i ON i.library_id=d.library_id AND i.raw_id=d.raw_id WHERE d.library_id=? AND i.status='pending' AND i.job_id IS NULL",(library_id,)).fetchone()[0]
        remaining=db.execute("SELECT COUNT(*) FROM drain_items d JOIN items i ON i.library_id=d.library_id AND i.raw_id=d.raw_id WHERE d.library_id=? AND i.status IN ('pending','running','retry')",(library_id,)).fetchone()[0]
        partial=db.execute("SELECT COUNT(*) FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL AND progress!='{}'",(library_id,)).fetchone()[0]
        retry=db.execute("SELECT 1 FROM jobs WHERE library_id=? AND status='retry' AND next_run<=? LIMIT 1",(library_id,time.time())).fetchone() is not None
        strict=profile['cadence']=='batch' and profile['auto_trigger_count']>0
        threshold=profile['auto_trigger_count'] if strict else (1 if profile['cadence']=='session' else profile['batch_size'])
        eligible=bool(profile['enabled'] and (retry or partial or cohort or (pending>=threshold if strict else pending)))
        return {'mode':'strict' if strict else 'session' if profile['cadence']=='session' else 'legacy',
                'threshold':threshold,'pending':pending,'cohort_pending':cohort,'partial_pending':partial,'eligible':eligible,'draining':bool(remaining or partial),
                'remaining':max(remaining,partial),'below_threshold':max(0,threshold-pending) if strict and not remaining and not partial else 0}

    def _claim(self, library_id, profile, flush, job_id=None):
        stamp = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not job_id:
                self._recover_jobs(db, stamp)
            old = db.execute("SELECT * FROM jobs WHERE library_id=? AND status='retry' AND next_run<=?"+
                (" AND id=?" if job_id else "")+" ORDER BY CASE WHEN purpose='persona' THEN 0 ELSE 1 END,created LIMIT 1",
                (library_id,stamp,job_id) if job_id else (library_id,stamp)).fetchone()
            if old:
                job = dict(old)
                db.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease_until=?,updated=? WHERE id=?", (stamp+120,stamp,job["id"]))
                db.execute("UPDATE items SET status='running' WHERE job_id=?",(job["id"],))
                job["attempts"] += 1
                job["_epoch"] = self._epoch(db,library_id)
                return job
            if job_id:return None
            desired = 1 if profile["cadence"] == "session" else profile["batch_size"]
            size = min(desired, max(1, profile["max_input_chars"] // 2500)) if profile["max_input_chars"] else desired
            context_bytes=context_input_bytes(profile)
            if context_bytes is not None:size=min(size,max(1,context_bytes//2500))
            strict=profile['cadence']=='batch' and profile['auto_trigger_count']>0
            # Membership is a durable snapshot of the raw backlog which triggered
            # this cycle. New arrivals do not endlessly extend that cycle.
            db.execute("DELETE FROM drain_items WHERE library_id=? AND NOT EXISTS (SELECT 1 FROM items i WHERE i.library_id=drain_items.library_id AND i.raw_id=drain_items.raw_id AND i.status='pending' AND i.job_id IS NULL)",(library_id,))
            trigger=self._trigger(db,library_id,profile)
            if strict:
                if flush:
                    db.execute("INSERT OR IGNORE INTO drain_items SELECT library_id,raw_id,? FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL",(stamp,library_id))
                elif not trigger['cohort_pending'] and trigger['partial_pending']:
                    # A long raw record can remain in progress after a retry or
                    # restart; never make its unfinished tail wait for N new turns.
                    db.execute("INSERT OR IGNORE INTO drain_items SELECT library_id,raw_id,? FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL AND progress!='{}'",(stamp,library_id))
                elif not trigger['cohort_pending'] and trigger['pending']>=profile['auto_trigger_count']:
                    db.execute("INSERT OR IGNORE INTO drain_items SELECT library_id,raw_id,? FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL",(stamp,library_id))
                rows=db.execute("SELECT i.* FROM items i JOIN drain_items d ON d.library_id=i.library_id AND d.raw_id=i.raw_id WHERE i.library_id=? AND i.status='pending' AND i.job_id IS NULL ORDER BY i.created LIMIT ?",(library_id,size)).fetchall()
            else:
                rows=db.execute("SELECT * FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL ORDER BY created LIMIT ?",(library_id,size)).fetchall()
            if not rows:return None
            if not strict and not flush and profile["cadence"] == "batch" and trigger['pending'] < desired and stamp - rows[0]["created"] < 30:
                return None
            jid = "organizer_" + uuid.uuid4().hex
            ids = [r["raw_id"] for r in rows]
            db.execute("INSERT INTO jobs(id,library_id,raw_ids,status,attempts,next_run,lease_until,created,updated,input_json,guards_json,plan_json,result_json,error_code,error) VALUES(?,?,?,'running',1,0,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL)",
                       (jid,library_id,json.dumps(ids),stamp+120,stamp,stamp))
            for rid in ids: db.execute("UPDATE items SET status='running',job_id=? WHERE library_id=? AND raw_id=?", (jid,library_id,rid))
            result = dict(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
            result["_epoch"] = self._epoch(db,library_id)
            return result

    def persona_selection(self, library_id, *, max_records=60):
        """Bounded representative assistant evidence, without touching ordinary items."""
        library_id=self._library(library_id)
        if type(max_records) is not int or not 2<=max_records<=120:
            raise ValidationError('人格抽样上限须为2~120条')
        from ..companion.dedup import canonical_id,is_duplicate
        brain=self._snapshot(library_id);profile=get_profile(brain);eligible=[];seen=set()
        with self.db() as db:
            tombs={row[0] for row in db.execute('SELECT item_id FROM tombstones WHERE library_id=?',(library_id,))}
        stamp=time.time()
        for node in brain.nodes.values():
            meta=node.get('meta',{});kind=meta.get('source')
            if (kind not in ('conversation_turn','agent_output','history_import') or disabled(node) or is_duplicate(node,brain)
                    or node.get('superseded_by') or node.get('valid_to') is not None and node['valid_to']<=stamp
                    or meta.get('library_id') not in (None,library_id)
                    or not brain._node_state(node,stamp).get('recoverable')):continue
            text=_persona_roles(node).get('assistant')
            if not isinstance(text,str) or not text.strip():continue
            proof=meta.get('evidence')
            rid=(proof.get('archive_receipt_id') if isinstance(proof,dict) else None) or node['id']
            cid=canonical_id(brain,node)
            if rid in tombs or node['id'] in tombs or cid in seen:continue
            seen.add(cid);eligible.append(rid)
        available=profile['max_input_chars']
        cap=min(max_records,len(eligible),8) if not available else min(max_records,len(eligible),8,max(2,available//2500)) if available>=3000 else 0
        selected=[]
        while cap>=2:
            selected=[eligible[round(i*(len(eligible)-1)/(cap-1))] for i in range(cap)]
            rows=[];archives={}
            try:
                for rid in selected:
                    node=raw_node(brain,rid);archive=self.read_archive(library_id,rid) if self.read_archive else None
                    if archive is not None:archives[rid]=archive
                    roles=archive_roles(archive) if archive else _roles(node)
                    rows.append({'raw_id':rid,'progress':json.dumps({role:len(value) for role,value in roles.items() if role!='assistant'})})
                payload,_=build_input(brain,library_id,rows,{**profile,'max_input_chars':available},archives,purpose='persona')
                if all(record.get('roles',{}).get('assistant') for record in payload['raw']):break
            except (ValidationError,TypeError,ValueError,AttributeError):pass
            cap-=1;selected=[]
        return {'eligible_records':len(eligible),'selected_records':len(selected),'selected_ids':selected,
                'coverage':'complete' if len(selected)==len(eligible) else 'sampled',
                'source_scope':'graph_backed_assistant_records','total_nodes':len(brain.nodes),
                'max_model_requests':1,'budget_available':not available or available>=3000,
                'will_call_model':False,'read_only':True}

    def enqueue_persona(self,library_id,raw_ids):
        library_id=self._library(library_id)
        if not isinstance(raw_ids,list) or not 2<=len(raw_ids)<=8 or len(set(raw_ids))!=len(raw_ids):
            raise ValidationError('快速人格需要2~8条独立助手来源')
        stamp=time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute("SELECT id,raw_ids FROM jobs WHERE library_id=? AND purpose='persona' AND (status='retry' OR (status='running' AND lease_until>?)) ORDER BY created LIMIT 1",(library_id,stamp)).fetchone()
            if active:return {'job_id':active['id'],'queued':False,'reused':True,'selected_records':len(json.loads(active['raw_ids']))}
            if any(db.execute('SELECT 1 FROM tombstones WHERE library_id=? AND item_id=?',(library_id,rid)).fetchone() for rid in raw_ids):
                raise OrganizerError('选定来源已遗忘，请重新预览','source_deleted')
            jid='organizer_'+uuid.uuid4().hex
            db.execute("INSERT INTO jobs(id,library_id,raw_ids,status,attempts,next_run,lease_until,created,updated,purpose) VALUES(?,?,?,'retry',0,0,0,?,?,'persona')",(jid,library_id,json.dumps(raw_ids),stamp,stamp))
        return {'job_id':jid,'queued':True,'reused':False,'selected_records':len(raw_ids)}

    def run_once(self, library_id=None, *, flush=True, job_id=None):
        if not self._run_lock.acquire(False): return {"status": "busy"}
        job = None
        deleted_ids = set()
        try:
            if self._stopping.is_set(): return {"status":"stopped"}
            if job_id and library_id is None:raise ValidationError('快速人格任务必须指定当前存档')
            if library_id is not None and flush and not job_id:self.repair_source_jobs(library_id)
            with self.db() as db:
                if not job_id:
                    self._recover_jobs(db, time.time())
            if not job_id:self._recover_source_jobs(library_id)
            brain = None
            if library_id is None:
                with self.db() as db:
                    rows = db.execute("SELECT library_id FROM jobs WHERE status='retry' AND next_run<=? UNION SELECT library_id FROM items WHERE status='pending' AND job_id IS NULL", (time.time(),)).fetchall()
                if not rows: return {"status": "idle"}
                ids=sorted({row[0] for row in rows})
                if self._last_auto_library in ids:
                    cursor=(ids.index(self._last_auto_library)+1)%len(ids)
                    ids=ids[cursor:]+ids[:cursor]
                threshold_blocked=False
                for candidate_id in ids:
                    try:
                        candidate = self._snapshot(candidate_id)
                        self._settle_aliases(candidate_id,candidate)
                        settings=get_profile(candidate)
                        if not settings["enabled"]:continue
                        with self.db() as db:
                            trigger=self._trigger(db,candidate_id,settings)
                            persona_waiting=db.execute("SELECT 1 FROM jobs WHERE library_id=? AND purpose='persona' AND status='retry' AND next_run<=? LIMIT 1",(candidate_id,time.time())).fetchone()
                        if not flush and not trigger['eligible'] and not persona_waiting:
                            threshold_blocked=True
                            continue
                        library_id,brain=candidate_id,candidate
                        self._last_auto_library=library_id
                        break
                    except Exception:
                        continue
                if library_id is None: return {"status":"waiting_threshold" if threshold_blocked else "paused"}
            library_id = self._library(library_id)
            brain = brain or self._snapshot(library_id)
            if not job_id:self._settle_aliases(library_id,brain)
            profile = get_profile(brain)
            if not profile["enabled"]: return {"status": "paused", "library_id": library_id}
            request_profile = profile
            job = self._claim(library_id, request_profile, flush,job_id) if job_id else self._claim(library_id, request_profile, flush)
            if job is None:
                with self.db() as db: trigger=self._trigger(db,library_id,profile)
                return {"status":"waiting_threshold" if trigger['mode']=='strict' and not trigger['eligible'] else "waiting", "library_id":library_id, "trigger":trigger}
            self._active_job = job["id"]
            ids = json.loads(job["raw_ids"])
            # Capture may commit and enqueue AFTER the first snapshot but BEFORE
            # this queue claim. Such a claimed receipt must be checked against a
            # fresh graph, otherwise a brand-new source looks permanently deleted.
            brain=self._snapshot(library_id)
            if get_profile(brain)!=profile:
                raise OrganizerConflict("整理配置已变化，按新配置安全重试")
            persona_only=job.get('purpose')=='persona'
            if persona_only:
                from ..companion.persona import persona_state
                persona=persona_state(brain,library_id=library_id)
                if not persona['enabled'] or not persona['learning_enabled']:
                    raise OrganizerError('当前存档已关闭人格或学习，未发送资料','persona_learning_disabled')
            # Do not replay even a cached result after its source was removed/disabled.
            deleted_ids = self._deleted_ids(library_id,ids,brain)
            if deleted_ids:
                raise OrganizerError("来源已删除或遗忘，未重放整理结果", "source_deleted")
            archives = {}
            if self.read_archive:
                for rid in ids:
                    try:
                        archive = self.read_archive(library_id, rid)
                    except ValidationError:
                        deleted_ids.add(rid)
                        raise OrganizerError("来源归档已删除或不属于当前库", "source_deleted") from None
                    if isinstance(archive,dict) and (archive.get("library_id",library_id) != library_id or archive.get("id",rid) != rid):
                        deleted_ids.add(rid)
                        raise OrganizerError("归档不属于当前库和本批原文", "source_deleted")
                    source = raw_node(brain, rid)
                    receipt = (source.get("meta", {}).get("evidence") or {})
                    if archive is None and isinstance(receipt, dict) and receipt.get("archive_receipt_id") == rid:
                        deleted_ids.add(rid)
                        raise OrganizerError("原始归档已删除，未重放整理结果", "source_deleted")
                    if archive is not None: archives[rid] = archive
            plan = json.loads(job["plan_json"]) if job.get("plan_json") else None
            if persona_only and plan is not None and (plan.get('purpose')!='persona' or plan.get('operations')):
                raise OrganizerError('缓存人格计划不属于本任务用途','invalid_persona_plan')
            if plan is None:
                try: saved_guards = json.loads(job.get('guards_json') or '{}')
                except (TypeError,ValueError): saved_guards = {}
                if not isinstance(saved_guards,dict): saved_guards = {}
                compact = saved_guards.get('retry_limits') if isinstance(saved_guards,dict) else None
                compact_chars = compact.get('max_input_chars') if isinstance(compact,dict) else None
                if type(compact_chars) is not int or compact_chars < 3000:
                    compact_chars = None
                if not persona_only and (compact_chars is not None or job.get('error_code') in ('truncated_output','context_length_exceeded')):
                    # Repeating the same large request cannot repair a response
                    # which hit the provider's output limit. Retry a smaller
                    # slice with one operation. Retain that limit across other
                    # failures and restarts until this slice succeeds.
                    configured_chars = profile['max_input_chars']
                    previous_chars = saved_guards.get('input_char_budget')
                    if type(previous_chars) is not int or previous_chars < 1:
                        previous_chars = len(job.get('input_json') or '')
                    if not previous_chars:
                        previous_chars = 4096 + sum(4096 + sum(len(text) for text in
                            (archive_roles(archives[rid]) if rid in archives else _roles(raw_node(brain,rid))).values()
                            if isinstance(text,str)) for rid in ids)
                    compact_chars = compact_chars or configured_chars or previous_chars
                    if configured_chars: compact_chars = min(configured_chars,compact_chars)
                    if job.get('error_code') in ('truncated_output','context_length_exceeded'):
                        compact_chars = max(3000, compact_chars // 2)
                    request_profile = {**profile, 'max_ops': 1,
                        'max_input_chars': compact_chars}
                    saved_guards['retry_limits'] = {'max_input_chars':compact_chars,'max_ops':1}
                    with self.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        if not self._valid_job(db,job): return {'status':'cancelled','job_id':job['id']}
                        # Metadata from many sources may itself exceed a compact
                        # request. Return the remaining sources to this cycle;
                        # their progress is unchanged and they will each finish.
                        if len(ids) > 1:
                            for rid in ids[1:]:
                                db.execute("UPDATE items SET status='pending',job_id=NULL WHERE library_id=? AND raw_id=? AND job_id=?",(library_id,rid,job['id']))
                                db.execute('INSERT OR IGNORE INTO drain_items VALUES(?,?,?)',(library_id,rid,time.time()))
                            ids = ids[:1]
                        db.execute('UPDATE jobs SET raw_ids=?,input_json=NULL,guards_json=? WHERE id=?',
                                   (json.dumps(ids),json.dumps(saved_guards),job['id']))
                if persona_only:
                    rows=[]
                    for rid in ids:
                        source=raw_node(brain,rid)
                        roles=archive_roles(archives[rid]) if rid in archives else _roles(source)
                        rows.append({'raw_id':rid,'progress':json.dumps({role:len(text) for role,text in roles.items() if role!='assistant'})})
                else:
                    with self.db() as db:
                        rows = [dict(db.execute("SELECT * FROM items WHERE library_id=? AND raw_id=?", (library_id,rid)).fetchone()) for rid in ids]
                payload, guards = build_input(brain, library_id, rows, request_profile, archives,purpose='persona' if persona_only else 'memory')
                if not persona_only and compact_chars is not None:
                    guards['retry_limits'] = {'max_input_chars':compact_chars,'max_ops':1}
                if persona_only:
                    payload['purpose']='persona'
                    payload['related']=[]
                    guards['existing_fingerprints']={}
                if not payload['raw']:
                    plan=validate_plan({'version':1,'operations':[]},payload,guards,job['id'],request_profile)
                    plan['model_called']=False
                else:
                    chars = len(json.dumps(payload, ensure_ascii=False))
                    credential = self.credential(library_id, deepcopy(profile))
                    # Missing/invalid credentials or model names never reserve a
                    # billable request. These failures happen before transport.
                    resolve_model(profile, credential)
                    if persona_only:
                        from ..companion.persona import persona_state
                        latest=persona_state(self._snapshot(library_id),library_id=library_id)
                        if not latest['enabled'] or not latest['learning_enabled'] or latest['revision']!=payload['memory_policy']['persona_revision']:
                            raise OrganizerConflict('人格开关或版本已变化，未预留快速整理请求')
                    with self.db() as db:
                        db.execute("BEGIN IMMEDIATE")
                        if not self._valid_job(db,job): return {"status":"cancelled","job_id":job["id"]}
                        db.execute("INSERT INTO calls VALUES(?,?,?,?)", (uuid.uuid4().hex, library_id, time.time(), chars))
                        db.execute("UPDATE jobs SET input_json=?,guards_json=? WHERE id=?", (json.dumps(payload,ensure_ascii=False),json.dumps(guards),job["id"]))
                    if self._stopping.is_set(): return {"status":"cancelled","job_id":job["id"]}
                    def guarded_transport(request, *, timeout):
                        with self.db() as db:
                            if not self._valid_job(db,job):
                                raise OrganizerError("任务已取消，不再发送材料", "cancelled")
                        if persona_only:
                            from ..companion.persona import persona_state
                            latest=persona_state(self._snapshot(library_id),library_id=library_id)
                            if not latest['enabled'] or not latest['learning_enabled'] or latest['revision']!=payload['memory_policy']['persona_revision']:
                                raise OrganizerConflict('人格开关或版本已变化，未发送快速整理资料')
                        return self.transport(request, timeout=timeout)
                    output = call_model(request_profile, credential, payload, guarded_transport)
                    plan = validate_plan(output, payload, guards, job["id"], request_profile)
                    runtime = credential if isinstance(credential, dict) else profile
                    plan["provider"] = {"provider_id":profile["provider_id"], "model":runtime.get("model",profile["model"]),
                                        "base_url":runtime.get("base_url",profile["base_url"])}
                # Validation uses the actual per-request limits. The apply
                # guard must still compare the unchanged library settings,
                # rather than mistaking this smaller request for a user edit.
                plan['profile'] = deepcopy(profile)
                with self.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if not self._valid_job(db,job): return {"status":"cancelled","job_id":job["id"]}
                    db.execute("UPDATE jobs SET plan_json=? WHERE id=?", (json.dumps(plan,ensure_ascii=False),job["id"]))
            with self.db() as db:
                if not self._valid_job(db,job): return {"status":"cancelled","job_id":job["id"]}
            result = self.apply(library_id, deepcopy(plan))
            if not isinstance(result,dict):
                raise OrganizerError("整理结果未获得持久化提交确认", "apply_unconfirmed")
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                if not self._valid_job(db,job): return {"status":"cancelled","job_id":job["id"]}
                for rid in ([] if persona_only else ids):
                    done = rid in plan["complete_ids"]
                    db.execute("UPDATE items SET status=?,progress=?,job_id=NULL WHERE library_id=? AND raw_id=?",
                               ("done_alias" if rid in plan.get('alias_ids',[]) else "done" if done else "pending",json.dumps(plan["progress"][rid]),library_id,rid))
                db.execute("UPDATE jobs SET status='done',updated=?,input_json=NULL,guards_json=NULL,result_json=?,error_code=NULL,error=NULL WHERE id=?",
                           (time.time(),json.dumps(result,ensure_ascii=False),job["id"]))
            return {"status": "done", "job_id": job["id"], "library_id": library_id, "result": result}
        except Exception as exc:
            code = getattr(exc, "code", "organizer_failed")
            persona_result=persona_result_view(getattr(exc,'persona_result',None))
            # Never echo exception/server text: it may contain provider credentials or private full input.
            message = {"source_deleted":"来源已删除，未重新整理", "stale_input":"来源或配置已变化，待重新生成计划",
                       "missing_raw":"原始记录暂不可用", "missing_archive":"需要完整归档，不能把摘录当全文",
                       "missing_credential":"整理模型尚未配置凭证，原文仍保留", "missing_model":"整理模型名称尚未配置，原文仍保留",
                       "budget_limited":"达到近24小时整理预算，原文和任务仍保留",
                       "invalid_evidence":"模型证据校验失败，原文仍保留"}.get(code,failure_message(code))
            if job:
                terminal = job.get('purpose')=='persona' or code == "source_deleted"
                with self.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if not self._valid_job(db,job): return {"status":"cancelled","job_id":job["id"]}
                    db.execute("UPDATE jobs SET status=?,updated=?,next_run=?,error_code=?,error=?,result_json=?,plan_json=CASE WHEN ? THEN NULL ELSE plan_json END WHERE id=?",
                               ("failed" if terminal else "retry",time.time(),time.time()+self._retry_delay(job["attempts"]),code,message,
                                json.dumps({'persona':persona_result}) if persona_result else None,isinstance(exc,OrganizerConflict),job["id"]))
                    db.execute("UPDATE items SET status=? WHERE job_id=?",("failed" if terminal else "retry",job["id"]))
                    if code == 'source_deleted' and job.get('purpose') == 'memory' and deleted_ids:
                        # A removed source must not strand the other records in
                        # its batch. Throw away the combined plan and preserve
                        # each surviving record's cursor for a new safe batch.
                        db.execute("UPDATE jobs SET raw_ids=?,input_json=NULL,guards_json=?,plan_json=NULL,result_json=NULL WHERE id=?",
                                   (json.dumps([rid for rid in ids if rid in deleted_ids]),json.dumps({'source_recovery_checked':True}),job['id']))
                        for rid in ids:
                            if rid in deleted_ids: continue
                            changed = db.execute("UPDATE items SET status='pending',job_id=NULL WHERE library_id=? AND raw_id=? AND job_id=?",
                                                 (library_id,rid,job['id'])).rowcount
                            if changed:
                                db.execute("INSERT OR IGNORE INTO drain_items VALUES(?,?,?)",(library_id,rid,time.time()))
                return {"status":"failed" if terminal else "retry","job_id":job["id"],"code":code,"error":message,
                        **({'persona_result':persona_result} if persona_result else {})}
            return {"status":"error","code":code,"error":message,**({'persona_result':persona_result} if persona_result else {})}
        finally:
            self._active_job = None
            self._run_lock.release()


    def status(self, library_id):
        self._library(library_id)
        profile=get_profile(self._snapshot(library_id))
        with self.db() as db:
            trigger=self._trigger(db,library_id,profile)
            counts = {r["status"]:r["count"] for r in db.execute("SELECT status,COUNT(*) AS count FROM items WHERE library_id=? GROUP BY status",(library_id,))}
            jobs = [dict(r) for r in db.execute("SELECT id,raw_ids,status,attempts,next_run,created,updated,error_code,error,purpose,result_json FROM jobs WHERE library_id=? ORDER BY created DESC LIMIT 30",(library_id,))]
            for job in jobs:
                job["raw_ids"] = json.loads(job["raw_ids"])
                try:result=json.loads(job.pop('result_json') or '{}')
                except (TypeError,ValueError):result={}
                persona_result=persona_result_view(result.get('persona')) if isinstance(result,dict) else None
                if persona_result is not None:job['persona_result']=persona_result
                relation_result=relation_result_view(result.get('relations')) if isinstance(result,dict) else None
                if relation_result is not None:job['relation_result']=relation_result
            used = self._budget(db,library_id)
        return {"library_id":library_id,"counts":counts,"jobs":jobs,"usage_24h":used,"trigger":trigger}

    def preview(self, library_id):
        library_id = self._library(library_id)
        brain = self._snapshot(library_id)
        profile = get_profile(brain)
        with self.db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM items WHERE library_id=? AND status='pending' AND job_id IS NULL ORDER BY created LIMIT ?",(library_id,profile["batch_size"]))]
            count = db.execute("SELECT COUNT(*) FROM items WHERE library_id=? AND status!='done'",(library_id,)).fetchone()[0]
            trigger=self._trigger(db,library_id,profile)
        if not rows: return {"status":"idle","pending_count":count,"raw_count":0,"will_call_model":False,"trigger":trigger}
        ids = [r["raw_id"] for r in rows]
        if self._deleted(library_id,ids,brain):
            return {"status":"deleted_source","pending_count":count,"raw_count":0,"will_call_model":False,"trigger":trigger}
        archives = {rid:self.read_archive(library_id,rid) for rid in ids} if self.read_archive else {}
        payload,preview_guards = build_input(brain,library_id,rows,profile,archives)
        return {"status":("waiting_threshold" if trigger['mode']=='strict' and not trigger['eligible'] else "ready") if profile["enabled"] else "paused","pending_count":count,"raw_count":len(payload['raw']),"aliased_count":len(preview_guards.get('alias_ids',[])),
                "related_count":len(payload["related"]),"input_chars":len(json.dumps(payload,ensure_ascii=False)),
                "raw_ids":ids,"will_call_model":False,"profile":profile,"trigger":trigger}

    def forget(self, library_id, raw_ids, node_ids=None):
        """Privacy boundary: cancel/reset this library's queue, scrub all stored plan/input/result bodies.

        Other raw data is untouched and may be enqueued afresh. Exact deleted IDs stay tombstoned.
        An in-flight response cannot save a plan/result or apply after observing the epoch change.
        """
        library_id = self._library(library_id)
        node_ids = [] if node_ids is None else node_ids
        for ids in (raw_ids,node_ids):
            if not isinstance(ids,list) or any(not isinstance(i,str) or not i or len(i)>300 for i in ids):
                raise ValidationError("遗忘ID列表不合法")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for kind,ids in (("raw",raw_ids),("node",node_ids)):
                for item in dict.fromkeys(ids):
                    db.execute("INSERT OR IGNORE INTO tombstones VALUES(?,?,?,?)",(library_id,kind,item,time.time()))
            db.execute("INSERT INTO epochs VALUES(?,1) ON CONFLICT(library_id) DO UPDATE SET value=value+1",(library_id,))
            db.execute("UPDATE jobs SET input_json=NULL,guards_json=NULL,plan_json=NULL,result_json=NULL,status=CASE WHEN status IN ('running','retry','failed') THEN 'cancelled' ELSE status END,error_code='privacy_deleted',error='本库任务因遗忘请求取消或清除内容' WHERE library_id=?",(library_id,))
            db.execute("DELETE FROM items WHERE library_id=?",(library_id,))
            db.execute("DELETE FROM drain_items WHERE library_id=?",(library_id,))
        checkpointed = False
        try:
            with self.db() as db:
                db.execute("PRAGMA busy_timeout=2000")
                row = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                checkpointed = row[0] == 0
        except sqlite3.Error:
            pass
        return {"library_id":library_id,"forgotten":len(set(raw_ids)),"cancelled_library_queue":True,
                "tombstoned_nodes":len(set(node_ids)),"checkpointed":checkpointed}



    def retry(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
            if row is None or row["status"] not in ("failed","retry"):
                raise ValidationError("该整理任务不可重试")
            db.execute("UPDATE jobs SET status='retry',attempts=0,next_run=0,error_code=NULL,error=NULL WHERE id=?",(job_id,))
            db.execute("UPDATE items SET status='retry' WHERE job_id=?",(job_id,))
        return {"job_id":job_id,"status":"retry"}

    def reject(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
            if row is None or row["status"] not in ("failed","retry"):
                raise ValidationError("该任务不能拒绝或正在执行")
            db.execute("UPDATE jobs SET status='rejected',input_json=NULL,plan_json=NULL WHERE id=?",(job_id,))
            db.execute("UPDATE items SET status='rejected' WHERE job_id=?",(job_id,))
        return {"job_id":job_id,"status":"rejected"}

    def start(self, poll_seconds=2):
        if self._thread and self._thread.is_alive(): return
        self._stopping.clear()
        def work():
            while not self._stopping.wait(poll_seconds): self.run_once(flush=False)
        self._thread = threading.Thread(target=work,daemon=True,name="memory-organizer")
        self._thread.start()

    def stop(self):
        self._stopping.set()
        if self._active_job:
            with self.db() as db:
                db.execute("UPDATE jobs SET status=CASE WHEN purpose='persona' THEN 'failed' ELSE 'retry' END,next_run=?,lease_until=0,error_code='interrupted',error='整理已停止，快速人格任务需明确重试' WHERE id=? AND status='running'",(time.time()+60,self._active_job))
                db.execute("UPDATE items SET status='retry' WHERE job_id=?",(self._active_job,))
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(timeout=2)

    def _recover_source_jobs(self, library_id=None):
        """Inspect each historical source-deletion failure once after upgrade."""
        if not self.read_archive:return
        with self.db() as db:
            libraries=[row[0] for row in db.execute("""SELECT DISTINCT library_id FROM jobs
                WHERE purpose='memory' AND status='failed' AND error_code='source_deleted' AND plan_json IS NULL
                AND COALESCE(guards_json,'') NOT LIKE '%"source_recovery_checked": true%'
                AND EXISTS (SELECT 1 FROM items i WHERE i.library_id=jobs.library_id AND i.job_id=jobs.id AND i.status='failed')"""
                + (" AND library_id=?" if library_id is not None else ''), (library_id,) if library_id is not None else ())]
        for lid in libraries:
            try:self.repair_source_jobs(lid,automatic=True)
            except Exception:
                # Snapshot/temporary storage failures can be inspected later;
                # they are not evidence that a source was deleted or repaired.
                continue

    def repair_source_jobs(self, library_id, *, automatic=False):
        """Recover proven historical false deletions without reviving lost sources.

        Retain attempts and the call ledger. A missing archive, privacy tombstone,
        disabled source, cached plan or another library is never recovered here.
        Mixed batches return only independently verified surviving items to this
        drain cycle. Automatic inspection is recorded once; an explicit action
        may check again after the user repairs an archive.
        """
        library_id=self._library(library_id)
        if not self.read_archive:return 0
        with self.db() as db:
            epoch=self._epoch(db,library_id)
            jobs=[dict(row) for row in db.execute("SELECT id,raw_ids,guards_json FROM jobs WHERE library_id=? "
                "AND status='failed' AND purpose='memory' AND error_code='source_deleted' AND plan_json IS NULL "
                "AND EXISTS (SELECT 1 FROM items i WHERE i.library_id=jobs.library_id AND i.job_id=jobs.id AND i.status='failed')",(library_id,))]
        if not jobs:return 0
        brain=self._snapshot(library_id);repaired=0
        if automatic and not get_profile(brain)['enabled']:return 0
        for job in jobs:
            try:history=json.loads(job.get('guards_json') or '{}')
            except (TypeError,ValueError):history={}
            if automatic and isinstance(history,dict) and history.get('source_recovery_checked'):continue
            ids=json.loads(job['raw_ids'])
            if not ids:continue
            invalid=self._deleted_ids(library_id,ids,brain)
            verified=[]
            for rid in ids:
                if rid in invalid:continue
                source=raw_node(brain,rid);proof=source.get('meta',{}).get('evidence')
                if (source.get('meta',{}).get('source') not in RAW_SOURCES
                        or source.get('meta',{}).get('library_id') not in (None,library_id)
                        or not isinstance(proof,dict) or proof.get('archive_receipt_id')!=rid):
                    continue
                try:archive=self.read_archive(library_id,rid)
                except ValidationError:archive=None
                if (not isinstance(archive,dict) or archive.get('library_id')!=library_id
                        or archive.get('id')!=rid):
                    continue
                try:roles=archive_roles(archive)
                except (AttributeError,TypeError):roles={}
                if not roles or not any(isinstance(text,str) and text for text in roles.values()):
                    continue
                verified.append(rid)
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                if self._epoch(db,library_id)!=epoch:break
                current=db.execute("SELECT 1 FROM jobs WHERE id=? AND library_id=? AND purpose='memory' AND status='failed' AND error_code='source_deleted' AND plan_json IS NULL",(job['id'],library_id)).fetchone()
                owned={row[0] for row in db.execute("SELECT raw_id FROM items WHERE library_id=? AND job_id=? AND status='failed'",(library_id,job['id']))}
                if current is None or owned!=set(ids):continue
                if len(verified)==len(ids):
                    db.execute("UPDATE jobs SET status='retry',next_run=0,error_code=NULL,error=NULL,updated=? WHERE id=?",(time.time(),job['id']))
                    db.execute("UPDATE items SET status='retry' WHERE library_id=? AND job_id=?",(library_id,job['id']))
                    repaired+=1
                else:
                    # Only IDs and the one-time inspection marker remain in a
                    # terminal failure; no old source prose or plan is retained.
                    db.execute("UPDATE jobs SET raw_ids=?,input_json=NULL,guards_json=?,plan_json=NULL,result_json=NULL,updated=? WHERE id=?",
                        (json.dumps([rid for rid in ids if rid not in verified]),json.dumps({'source_recovery_checked':True}),time.time(),job['id']))
                    for rid in verified:
                        db.execute("UPDATE items SET status='pending',job_id=NULL WHERE library_id=? AND raw_id=? AND job_id=?",(library_id,rid,job['id']))
                        db.execute('INSERT OR IGNORE INTO drain_items VALUES(?,?,?)',(library_id,rid,time.time()))
                    if verified:repaired+=1
        return repaired

    def resume_configuration_jobs(self, library_id):
        """Recover this library's config-blocked tasks after an actual repair.

        Caller must confirm a usable changed configuration. Do not revive quota,
        transport, invalid evidence, rejected/forgotten or completed tasks. Keep
        call-budget history and successful cached plans intact.
        """
        library_id = self._library(library_id)
        codes = ("missing_credential", "missing_model", "invalid_credential",
                 "provider_authentication", "provider_access_denied", "provider_not_found",
                 "unsupported_effort", "invalid_output_limit", "invalid_context_limit")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM jobs WHERE library_id=? AND purpose='memory' AND status IN ('failed','retry') "
                              "AND error_code IN ("+','.join('?' for _ in codes)+") AND plan_json IS NULL", (library_id,*codes)).fetchall()
            for row in rows:
                db.execute("UPDATE jobs SET status='retry',next_run=0,error_code=NULL,error=NULL,updated=? WHERE id=?",
                           (time.time(),row['id']))
                db.execute("UPDATE items SET status='retry' WHERE library_id=? AND job_id=?",(library_id,row['id']))
        return len(rows)
