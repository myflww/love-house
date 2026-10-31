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
from .state import build_input, validate_plan, raw_node, disabled, archive_roles, RAW_SOURCES


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
        nodes = [raw_node(brain,rid) for rid in ids]
        if any(n is None or disabled(n) for n in nodes): return True
        with self.db() as db:
            deleted = {r[0] for r in db.execute("SELECT item_id FROM tombstones WHERE library_id=?",(library_id,))}
        return bool(deleted.intersection(ids) or deleted.intersection(n["id"] for n in nodes))

    def _snapshot(self, library_id):
        data = self.snapshot(library_id)
        if isinstance(data, Brain): data = data.to_dict()
        if not isinstance(data, dict): raise OrganizerError("无法读取本库快照", "snapshot_failed")
        return Brain(deepcopy(data))

    def _budget(self, db, library_id):
        row = db.execute("SELECT COUNT(*) AS count,COALESCE(SUM(chars),0) AS chars FROM calls WHERE library_id=? AND at>?",
                         (library_id, time.time() - 86400)).fetchone()
        return dict(row)

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

    def _claim(self, library_id, profile, flush):
        stamp = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE jobs SET status='retry',next_run=?,error_code='interrupted',error='进程中断，等待安全重试' WHERE status='running' AND lease_until<?", (stamp, stamp))
            db.execute("UPDATE items SET status='retry' WHERE status='running' AND job_id IN (SELECT id FROM jobs WHERE status='retry')")
            old = db.execute("SELECT * FROM jobs WHERE library_id=? AND status='retry' AND next_run<=? ORDER BY created LIMIT 1", (library_id, stamp)).fetchone()
            if old:
                job = dict(old)
                db.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease_until=?,updated=? WHERE id=?", (stamp+120,stamp,job["id"]))
                db.execute("UPDATE items SET status='running' WHERE job_id=?",(job["id"],))
                job["attempts"] += 1
                job["_epoch"] = self._epoch(db,library_id)
                return job
            desired = 1 if profile["cadence"] == "session" else profile["batch_size"]
            size = min(desired, max(1, profile["max_input_chars"] // 2500))
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
            db.execute("INSERT INTO jobs VALUES(?,?,?,'running',1,0,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL)",
                       (jid,library_id,json.dumps(ids),stamp+120,stamp,stamp))
            for rid in ids: db.execute("UPDATE items SET status='running',job_id=? WHERE library_id=? AND raw_id=?", (jid,library_id,rid))
            result = dict(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
            result["_epoch"] = self._epoch(db,library_id)
            return result

    def run_once(self, library_id=None, *, flush=True):
        if not self._run_lock.acquire(False): return {"status": "busy"}
        job = None
        try:
            if self._stopping.is_set(): return {"status":"stopped"}
            # Only an explicit per-library run repairs old false deletion
            # failures. The background worker never repeatedly revives them.
            if library_id is not None and flush:self.repair_source_jobs(library_id)
            with self.db() as db:
                db.execute("UPDATE jobs SET status='retry',next_run=?,error_code='interrupted',error='进程中断，等待安全重试' WHERE status='running' AND lease_until<?",(time.time(),time.time()))
                db.execute("UPDATE items SET status='retry' WHERE status='running' AND job_id IN (SELECT id FROM jobs WHERE status='retry')")
            brain = None
            if library_id is None:
                with self.db() as db:
                    rows = db.execute("SELECT library_id FROM jobs WHERE status='retry' AND next_run<=? UNION SELECT library_id FROM items WHERE status='pending' AND job_id IS NULL", (time.time(),)).fetchall()
                if not rows: return {"status": "idle"}
                ids=sorted({row[0] for row in rows})
                if self._last_auto_library in ids:
                    cursor=(ids.index(self._last_auto_library)+1)%len(ids)
                    ids=ids[cursor:]+ids[:cursor]
                budget_blocked=False
                threshold_blocked=False
                for candidate_id in ids:
                    try:
                        candidate = self._snapshot(candidate_id)
                        self._settle_aliases(candidate_id,candidate)
                        settings=get_profile(candidate)
                        if not settings["enabled"]:continue
                        with self.db() as db:
                            usage=self._budget(db,candidate_id)
                            cached=db.execute("SELECT 1 FROM jobs WHERE library_id=? AND status='retry' AND next_run<=? AND plan_json IS NOT NULL LIMIT 1",(candidate_id,time.time())).fetchone()
                        with self.db() as db: trigger=self._trigger(db,candidate_id,settings)
                        if not flush and not trigger['eligible']:
                            threshold_blocked=True
                            continue
                        if not cached and (usage["count"]>=settings["daily_call_limit"] or settings["daily_char_limit"]-usage["chars"]<3000):
                            budget_blocked=True
                            continue
                        library_id,brain=candidate_id,candidate
                        self._last_auto_library=library_id
                        break
                    except Exception:
                        continue
                if library_id is None: return {"status":"budget_limited" if budget_blocked else "waiting_threshold" if threshold_blocked else "paused"}
            library_id = self._library(library_id)
            brain = brain or self._snapshot(library_id)
            self._settle_aliases(library_id,brain)
            profile = get_profile(brain)
            if not profile["enabled"]: return {"status": "paused", "library_id": library_id}
            with self.db() as db:
                used = self._budget(db, library_id)
                cached_ready = db.execute("SELECT 1 FROM jobs WHERE library_id=? AND status='retry' AND next_run<=? AND plan_json IS NOT NULL LIMIT 1",(library_id,time.time())).fetchone()
            remaining = profile["daily_char_limit"] - used["chars"]
            if not cached_ready and (used["count"] >= profile["daily_call_limit"] or remaining < 3000):
                return {"status": "budget_limited", "library_id": library_id, "used": used}
            request_profile = {**profile, "max_input_chars": min(profile["max_input_chars"],remaining)}
            job = self._claim(library_id, request_profile, flush)
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
            # Do not replay even a cached result after its source was removed/disabled.
            if self._deleted(library_id,ids,brain):
                raise OrganizerError("来源已删除或遗忘，未重放整理结果", "source_deleted")
            archives = {}
            if self.read_archive:
                for rid in ids:
                    try:
                        archive = self.read_archive(library_id, rid)
                    except ValidationError:
                        raise OrganizerError("来源归档已删除或不属于当前库", "source_deleted") from None
                    if isinstance(archive,dict) and (archive.get("library_id",library_id) != library_id or archive.get("id",rid) != rid):
                        raise OrganizerError("归档不属于当前库和本批原文", "source_deleted")
                    source = raw_node(brain, rid)
                    receipt = (source.get("meta", {}).get("evidence") or {})
                    if archive is None and isinstance(receipt, dict) and receipt.get("archive_receipt_id") == rid:
                        raise OrganizerError("原始归档已删除，未重放整理结果", "source_deleted")
                    if archive is not None: archives[rid] = archive
            plan = json.loads(job["plan_json"]) if job.get("plan_json") else None
            if plan is None:
                with self.db() as db:
                    rows = [dict(db.execute("SELECT * FROM items WHERE library_id=? AND raw_id=?", (library_id,rid)).fetchone()) for rid in ids]
                payload, guards = build_input(brain, library_id, rows, request_profile, archives)
                if not payload['raw']:
                    plan=validate_plan({'version':1,'operations':[]},payload,guards,job['id'],profile)
                    plan['model_called']=False
                else:
                    chars = len(json.dumps(payload, ensure_ascii=False))
                    credential = self.credential(library_id, deepcopy(profile))
                    # Missing/invalid credentials or model names never reserve a
                    # billable request. These failures happen before transport.
                    resolve_model(profile, credential)
                    with self.db() as db:
                        db.execute("BEGIN IMMEDIATE")
                        if not self._valid_job(db,job): return {"status":"cancelled","job_id":job["id"]}
                        used = self._budget(db, library_id)
                        if used["count"] >= profile["daily_call_limit"] or used["chars"] + chars > profile["daily_char_limit"]:
                            raise OrganizerError("本批达到近24小时整理预算，等待重试", "budget_limited")
                        db.execute("INSERT INTO calls VALUES(?,?,?,?)", (uuid.uuid4().hex, library_id, time.time(), chars))
                        db.execute("UPDATE jobs SET input_json=?,guards_json=? WHERE id=?", (json.dumps(payload,ensure_ascii=False),json.dumps(guards),job["id"]))
                    if self._stopping.is_set(): return {"status":"cancelled","job_id":job["id"]}
                    def guarded_transport(request, *, timeout):
                        with self.db() as db:
                            if not self._valid_job(db,job):
                                raise OrganizerError("任务已取消，不再发送材料", "cancelled")
                        return self.transport(request, timeout=timeout)
                    output = call_model(profile, credential, payload, guarded_transport)
                    plan = validate_plan(output, payload, guards, job["id"], profile)
                    runtime = credential if isinstance(credential, dict) else profile
                    plan["provider"] = {"provider_id":profile["provider_id"], "model":runtime.get("model",profile["model"]),
                                        "base_url":runtime.get("base_url",profile["base_url"])}
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
                for rid in ids:
                    done = rid in plan["complete_ids"]
                    db.execute("UPDATE items SET status=?,progress=?,job_id=NULL WHERE library_id=? AND raw_id=?",
                               ("done_alias" if rid in plan.get('alias_ids',[]) else "done" if done else "pending",json.dumps(plan["progress"][rid]),library_id,rid))
                db.execute("UPDATE jobs SET status='done',updated=?,input_json=NULL,guards_json=NULL,result_json=?,error_code=NULL,error=NULL WHERE id=?",
                           (time.time(),json.dumps(result,ensure_ascii=False),job["id"]))
            return {"status": "done", "job_id": job["id"], "library_id": library_id, "result": result}
        except Exception as exc:
            code = getattr(exc, "code", "organizer_failed")
            # Never echo exception/server text: it may contain provider credentials or private full input.
            message = {"source_deleted":"来源已删除，未重新整理", "stale_input":"来源或配置已变化，待重新生成计划",
                       "missing_raw":"原始记录暂不可用", "missing_archive":"需要完整归档，不能把摘录当全文",
                       "missing_credential":"整理模型尚未配置凭证，原文仍保留", "missing_model":"整理模型名称尚未配置，原文仍保留",
                       "budget_limited":"达到近24小时整理预算，原文和任务仍保留",
                       "invalid_evidence":"模型证据校验失败，原文仍保留"}.get(code,failure_message(code))
            if job:
                terminal = code == "source_deleted" or job["attempts"] >= profile["max_attempts"]
                with self.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if not self._valid_job(db,job): return {"status":"cancelled","job_id":job["id"]}
                    db.execute("UPDATE jobs SET status=?,updated=?,next_run=?,error_code=?,error=?,plan_json=CASE WHEN ? THEN NULL ELSE plan_json END WHERE id=?",
                               ("failed" if terminal else "retry",time.time(),time.time()+min(300,5*2**(job["attempts"]-1)),code,message,
                                isinstance(exc,OrganizerConflict),job["id"]))
                    db.execute("UPDATE items SET status=? WHERE job_id=?",("failed" if terminal else "retry",job["id"]))
                return {"status":"failed" if terminal else "retry","job_id":job["id"],"code":code,"error":message}
            return {"status":"error","code":code,"error":message}
        finally:
            self._active_job = None
            self._run_lock.release()

    def status(self, library_id):
        self._library(library_id)
        profile=get_profile(self._snapshot(library_id))
        with self.db() as db:
            trigger=self._trigger(db,library_id,profile)
            counts = {r["status"]:r["count"] for r in db.execute("SELECT status,COUNT(*) AS count FROM items WHERE library_id=? GROUP BY status",(library_id,))}
            jobs = [dict(r) for r in db.execute("SELECT id,raw_ids,status,attempts,next_run,created,updated,error_code,error FROM jobs WHERE library_id=? ORDER BY created DESC LIMIT 30",(library_id,))]
            for job in jobs: job["raw_ids"] = json.loads(job["raw_ids"])
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

    def repair_source_jobs(self, library_id):
        """Explicit retry of rc2 false deletions, with current provenance proof.

        Retain attempts and the call ledger. A missing archive, privacy tombstone,
        disabled source, cached plan or another library is never recovered here.
        """
        library_id=self._library(library_id)
        if not self.read_archive:return 0
        with self.db() as db:
            epoch=self._epoch(db,library_id)
            jobs=[dict(row) for row in db.execute("SELECT id,raw_ids FROM jobs WHERE library_id=? "
                "AND status='failed' AND error_code='source_deleted' AND plan_json IS NULL",(library_id,))]
        if not jobs:return 0
        brain=self._snapshot(library_id);repaired=0
        for job in jobs:
            ids=json.loads(job['raw_ids'])
            if not ids or self._deleted(library_id,ids,brain):continue
            verified=True
            for rid in ids:
                source=raw_node(brain,rid);proof=source.get('meta',{}).get('evidence')
                if (source.get('meta',{}).get('source') not in RAW_SOURCES
                        or not isinstance(proof,dict) or proof.get('archive_receipt_id')!=rid):
                    verified=False;break
                try:archive=self.read_archive(library_id,rid)
                except ValidationError:archive=None
                if (not isinstance(archive,dict) or archive.get('library_id')!=library_id
                        or archive.get('id')!=rid):
                    verified=False;break
                try:roles=archive_roles(archive)
                except (AttributeError,TypeError):roles={}
                if not roles or not any(isinstance(text,str) and text for text in roles.values()):
                    verified=False;break
            if not verified:continue
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                if self._epoch(db,library_id)!=epoch:break
                changed=db.execute("UPDATE jobs SET status='retry',next_run=0,error_code=NULL,error=NULL,updated=? "
                    "WHERE id=? AND library_id=? AND status='failed' AND error_code='source_deleted' AND plan_json IS NULL",
                    (time.time(),job['id'],library_id)).rowcount
                if changed:
                    db.execute("UPDATE items SET status='retry' WHERE library_id=? AND job_id=?",(library_id,job['id']))
                    repaired+=1
        return repaired

    def resume_configuration_jobs(self, library_id):
        """Recover this library's config-blocked tasks after an actual repair.

        Caller must confirm a usable changed configuration. Do not revive quota,
        transport, invalid evidence, rejected/forgotten or completed tasks. Keep
        call-budget history and successful cached plans intact.
        """
        library_id = self._library(library_id)
        codes = ("missing_credential", "missing_model", "invalid_credential",
                 "provider_authentication", "provider_access_denied", "provider_not_found")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM jobs WHERE library_id=? AND status IN ('failed','retry') "
                              "AND error_code IN (?,?,?,?,?,?) AND plan_json IS NULL", (library_id,*codes)).fetchall()
            for row in rows:
                db.execute("UPDATE jobs SET status='retry',attempts=0,next_run=0,error_code=NULL,error=NULL,updated=? WHERE id=?",
                           (time.time(),row['id']))
                db.execute("UPDATE items SET status='retry' WHERE library_id=? AND job_id=?",(library_id,row['id']))
        return len(rows)

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
                db.execute("UPDATE jobs SET status='retry',next_run=?,lease_until=0,error_code='interrupted',error='整理已停止，等待安全重试' WHERE id=? AND status='running'",(time.time()+60,self._active_job))
                db.execute("UPDATE items SET status='retry' WHERE job_id=?",(self._active_job,))
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(timeout=2)
