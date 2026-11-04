"""Private, bounded metadata for genuine memory use, applied on the next save.

No query, message, title, credential or model output is accepted by this API.
One row per library/node/kind retains the latest use and a compare-and-ack
pending marker. Reading context only queues metadata; it never mutates a Brain.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
import os
from pathlib import Path
import json
import re
import secrets
import sqlite3
import threading
import time
from weakref import WeakValueDictionary

from ..errors import StorageError, ValidationError

DAY = 86400
KINDS = frozenset({"recall", "mention", "cited", "confirmed"})
_LIBRARY_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_BATCH = 1000
_LOCKS_GUARD = threading.Lock()
_DATABASE_LOCKS = WeakValueDictionary()


def _database_lock(path):
    # Separate UsageJournal objects still access one SQLite file. Resolve path
    # aliases and Windows case before selecting the lock; retain no permanent
    # registry entry after the last journal for this database is released.
    identity = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        lock = _DATABASE_LOCKS.get(identity)
        if lock is None:
            lock = threading.RLock()
            _DATABASE_LOCKS[identity] = lock
        return lock


def _library(value):
    if not isinstance(value, str) or not _LIBRARY_ID.fullmatch(value):
        raise ValidationError("记忆使用记录缺少合法的固定存档身份")
    return value


def _kind(value):
    if not isinstance(value, str) or value not in KINDS:
        raise ValidationError("记忆使用类型只能是 recall、mention、cited 或 confirmed")
    return value


def _node_ids(value):
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_BATCH:
        raise ValidationError("每批记忆使用记录最多 1000 个节点标识")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 200
           or "|" in item for item in value):
        raise ValidationError("记忆节点标识格式不正确")
    try:
        for item in value:
            item.encode("utf-8")
    except UnicodeError:
        raise ValidationError("记忆节点标识包含无法保存的字符") from None
    return list(dict.fromkeys(value))


def _stamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253402300799:
        raise ValidationError("记忆使用时间须为有效的 UTC 时间戳")
    return float(value)


class UsageJournal:
    """Durable, scoped usage metadata with rolling-24h and UTC-day de-duplication.

    A use arriving more than a day after an un-applied use replaces that pending
    marker. The caller applies the newest use, not a backlog of artificial
    reinforcements. An old acknowledgement cannot clear a newer pending use.
    """

    def __init__(self, root, *, clock=None):
        self.path = Path(root) / "memory-usage.sqlite3"
        self._db_lock = _database_lock(self.path)
        self.clock = clock or time.time
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            old=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_usage'").fetchone()
            if old is not None and "'cited'" not in old[0]:
                db.execute('ALTER TABLE memory_usage RENAME TO memory_usage_v1')
                db.execute('DROP INDEX IF EXISTS memory_usage_pending')
                db.execute("""CREATE TABLE memory_usage (
                    library_id TEXT NOT NULL,node_id TEXT NOT NULL,kind TEXT NOT NULL
                    CHECK(kind IN ('recall','mention','cited','confirmed')),
                    last_at REAL NOT NULL,last_day INTEGER NOT NULL,pending_at REAL,
                    pending_day INTEGER,applied_at REAL,PRIMARY KEY(library_id,node_id,kind))""")
                db.execute('INSERT INTO memory_usage SELECT * FROM memory_usage_v1')
                db.execute('DROP TABLE memory_usage_v1')
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memory_usage (
                    library_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('recall','mention','cited','confirmed')),
                    last_at REAL NOT NULL,
                    last_day INTEGER NOT NULL,
                    pending_at REAL,
                    pending_day INTEGER,
                    applied_at REAL,
                    PRIMARY KEY(library_id,node_id,kind)
                );
                CREATE INDEX IF NOT EXISTS memory_usage_pending
                    ON memory_usage(library_id,pending_at) WHERE pending_at IS NOT NULL;
                CREATE TABLE IF NOT EXISTS memory_deliveries (
                    id TEXT PRIMARY KEY,library_id TEXT NOT NULL,connection_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,node_ids TEXT NOT NULL,issued_at REAL NOT NULL,expires_at REAL NOT NULL,
                    binding_revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS memory_delivery_expiry ON memory_deliveries(expires_at);
                CREATE TABLE IF NOT EXISTS memory_feedback (
                    delivery_id TEXT NOT NULL,node_id TEXT NOT NULL,kind TEXT NOT NULL,
                    PRIMARY KEY(delivery_id,node_id,kind)
                );
            """)
            if 'binding_revision' not in {row[1] for row in db.execute('PRAGMA table_info(memory_deliveries)')}:
                db.execute('ALTER TABLE memory_deliveries ADD COLUMN binding_revision INTEGER NOT NULL DEFAULT 0')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        # Serialize local initialization, transactions and handle closure across
        # journal instances. Otherwise their WAL/schema setup and writes compete
        # for the short SQLite busy budget on Windows. Different files retain
        # independent locks; an external writer still has the bounded timeout.
        with self._db_lock:
            db = None
            try:
                db = sqlite3.connect(self.path, timeout=0.05)
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA secure_delete=ON")
                with db:
                    yield db
            except sqlite3.Error:
                # Never include content, paths, opaque IDs or SQLite details.
                raise StorageError("暂时无法保存记忆使用记录；已有记忆与原文不受影响") from None
            finally:
                if db is not None:
                    db.close()

    def enqueue(self, library_id, ids, kind, at=None):
        library_id, ids, kind = _library(library_id), _node_ids(ids), _kind(kind)
        at = _stamp(self.clock() if at is None else at)
        day = int(at // DAY)
        if not ids:
            return {"queued": 0, "ignored": 0}
        with self.db() as db:
            before = db.total_changes
            db.executemany("""
                INSERT INTO memory_usage(library_id,node_id,kind,last_at,last_day,pending_at,pending_day)
                    VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(library_id,node_id,kind) DO UPDATE SET
                    last_at=excluded.last_at,last_day=excluded.last_day,
                    pending_at=excluded.pending_at,pending_day=excluded.pending_day
                WHERE excluded.last_day > memory_usage.last_day
                    AND excluded.last_at - memory_usage.last_at >= ?
            """, [(library_id, nid, kind, at, day, at, day, DAY) for nid in ids])
            queued = db.total_changes - before
        return {"queued": queued, "ignored": len(ids) - queued}

    def pending(self, library_id, limit=256):
        library_id = _library(library_id)
        if type(limit) is not int or not 1 <= limit <= _MAX_BATCH:
            raise ValidationError("待巩固记录数量须在 1~1000 之间")
        with self.db() as db:
            rows = db.execute("""
                SELECT library_id,node_id,kind,pending_day AS day,pending_at AS at
                FROM memory_usage WHERE library_id=? AND pending_at IS NOT NULL
                ORDER BY pending_at,node_id,kind LIMIT ?
            """, (library_id, limit)).fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try:
                _library(item['library_id']);_node_ids([item['node_id']]);_kind(item['kind'])
                stamp=_stamp(item['at'])
                if type(item['day']) is not int or item['day']!=int(stamp//DAY):
                    raise ValidationError('使用记录日期不一致')
            except (ValidationError,KeyError,TypeError):
                # This expendable side table can be unavailable without making
                # the original dialogue transaction depend on corrupt metadata.
                raise StorageError('使用元信息暂不可读；原始记录可继续保存') from None
            result.append(item)
        return result

    def applied(self, rows):
        """Acknowledge exactly these pending versions, only AFTER graph commit.

        If graph commit succeeded but this acknowledgement fails, the pending
        marker survives. Core use application must therefore be day-idempotent.
        """
        if not isinstance(rows, (list, tuple)) or len(rows) > _MAX_BATCH:
            raise ValidationError("每批最多确认 1000 条记忆使用记录")
        prepared = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"library_id", "node_id", "kind", "day", "at"}:
                raise ValidationError("待巩固记录必须包含完整的固定身份与版本")
            lib, nid, kind = _library(row["library_id"]), _node_ids([row["node_id"]])[0], _kind(row["kind"])
            at = _stamp(row["at"])
            if type(row["day"]) is not int or row["day"] != int(at // DAY):
                raise ValidationError("待巩固记录日期与时间不一致")
            prepared.append((lib, nid, kind, at, row["day"]))
        with self.db() as db:
            before = db.total_changes
            db.executemany("""
                UPDATE memory_usage SET applied_at=pending_at,pending_at=NULL,pending_day=NULL
                WHERE library_id=? AND node_id=? AND kind=? AND pending_at=? AND pending_day=?
            """, prepared)
            return db.total_changes - before

    def forget(self, library_id, node_ids=None):
        """Purge use metadata for explicit forgetting, or an entire removed identity."""
        library_id = _library(library_id)
        ids = None if node_ids is None else _node_ids(node_ids)
        with self.db() as db:
            before = db.total_changes
            if ids is None:
                db.execute("DELETE FROM memory_usage WHERE library_id=?", (library_id,))
            else:
                db.executemany("DELETE FROM memory_usage WHERE library_id=? AND node_id=?",
                               [(library_id, nid) for nid in ids])
            removed=db.total_changes-before
            # A forgotten ID may never be accepted later through a stale ticket.
            deliveries=db.execute('SELECT id,node_ids FROM memory_deliveries WHERE library_id=?',(library_id,)).fetchall()
            for delivery in deliveries:
                if ids is None or set(json.loads(delivery['node_ids']))&set(ids):
                    db.execute('DELETE FROM memory_feedback WHERE delivery_id=?',(delivery['id'],))
                    db.execute('DELETE FROM memory_deliveries WHERE id=?',(delivery['id'],))
            return removed

    def issue_delivery(self, library_id, connection_id, session_id, node_ids, *, binding_revision=0, at=None):
        """A short-lived metadata receipt is not a grant of access or model-use proof."""
        library_id,ids=_library(library_id),_node_ids(node_ids)
        for value in (connection_id,session_id):
            if not isinstance(value,str) or not value.strip() or len(value)>200:
                raise ValidationError('记忆回执需要已授权的连接和窗口')
        stamp=_stamp(self.clock() if at is None else at)
        if type(binding_revision) is not int or binding_revision<0:raise ValidationError('连接绑定版本无效')
        delivery={'id':'delivery_'+secrets.token_urlsafe(24),'library_id':library_id,
                  'connection_id':connection_id,'session_id':session_id,'node_ids':ids,
                  'issued_at':stamp,'expires_at':stamp+DAY,'binding_revision':binding_revision}
        with self.db() as db:
            db.execute('DELETE FROM memory_feedback WHERE delivery_id IN (SELECT id FROM memory_deliveries WHERE expires_at<=?)',(stamp,))
            db.execute('DELETE FROM memory_deliveries WHERE expires_at<=?',(stamp,))
            db.execute('INSERT INTO memory_deliveries VALUES(?,?,?,?,?,?,?,?)',
                       (delivery['id'],library_id,connection_id,session_id,json.dumps(ids),stamp,stamp+DAY,binding_revision))
        return delivery

    def delivery(self, identifier, library_id, connection_id, session_id, *, binding_revision=None, at=None):
        library_id=_library(library_id)
        if not isinstance(identifier,str) or not 1<=len(identifier)<=100:
            raise ValidationError('记忆回执无效或已过期')
        stamp=_stamp(self.clock() if at is None else at)
        with self.db() as db:
            row=db.execute('SELECT * FROM memory_deliveries WHERE id=? AND library_id=? AND connection_id=? AND session_id=? AND expires_at>?',
                           (identifier,library_id,connection_id,session_id,stamp)).fetchone()
        if row is None or binding_revision is not None and row['binding_revision']!=binding_revision:
            raise ValidationError('记忆回执无效、已过期或不属于当前窗口绑定')
        result=dict(row);result['node_ids']=_node_ids(json.loads(result['node_ids']))
        return result

    def latest_delivery(self, library_id, connection_id, *, binding_revision=None):
        library_id=_library(library_id)
        with self.db() as db:
            row=db.execute('SELECT * FROM memory_deliveries WHERE library_id=? AND connection_id=? AND expires_at>? ORDER BY issued_at DESC,id DESC LIMIT 1',
                           (library_id,connection_id,_stamp(self.clock()))).fetchone()
        if row is None or binding_revision is not None and row['binding_revision']!=binding_revision:return None
        result=dict(row);result['node_ids']=_node_ids(json.loads(result['node_ids']))
        return result

    def feedback(self, identifier, library_id, connection_id, session_id, ids, kind, *,
                 verified_cited_ids=(), management=False, binding_revision=None, at=None):
        """Only the host may supply verified IDs or explicit management authority.

        These keyword arguments must never be populated from a request body.
        Scope/authentication and citation verification are separate host checks.
        """
        ids=_node_ids(ids)
        if kind not in ('cited','confirmed') or kind=='confirmed' and management is not True:
            raise ValidationError('用户确认仅可由本机管理操作提交')
        stamp=_stamp(self.clock() if at is None else at)
        receipt=self.delivery(identifier,library_id,connection_id,session_id,binding_revision=binding_revision,at=stamp)
        if not ids or not set(ids)<=set(receipt['node_ids']):
            raise ValidationError('只能反馈本窗口这次实际提供的记忆')
        if kind=='cited' and not set(ids)<=set(verified_cited_ids):
            raise ValidationError('缺少已归档回复中的可核引用')
        # Keep the feedback marker and the durable pending use in one transaction.
        with self.db() as db:
            current=db.execute('SELECT binding_revision FROM memory_deliveries WHERE id=? AND library_id=? AND connection_id=? AND session_id=? AND expires_at>?',
                              (identifier,library_id,connection_id,session_id,stamp)).fetchone()
            if current is None or binding_revision is not None and current['binding_revision']!=binding_revision:
                raise ValidationError('记忆回执已失效')
            added=[]
            for nid in ids:
                cursor=db.execute('INSERT OR IGNORE INTO memory_feedback VALUES(?,?,?)',(identifier,nid,kind))
                if cursor.rowcount:added.append(nid)
            day=int(stamp//DAY)
            for nid in added:
                db.execute('''INSERT INTO memory_usage(library_id,node_id,kind,last_at,last_day,pending_at,pending_day)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(library_id,node_id,kind) DO UPDATE SET
                    last_at=excluded.last_at,last_day=excluded.last_day,pending_at=excluded.pending_at,pending_day=excluded.pending_day
                    WHERE excluded.last_day>memory_usage.last_day AND excluded.last_at-memory_usage.last_at>=?''',
                    (library_id,nid,kind,stamp,day,stamp,day,DAY))
        return {'accepted':True,'kind':kind,'recorded_ids':added,'duplicate_ids':[nid for nid in ids if nid not in added],
                'evidence':'archived_reply_reference' if kind=='cited' else 'explicit_user_feedback',
                'model_adoption_verified':False}

    def discard(self, library_id, node_ids):
        """Drop metadata only for IDs the caller proved deleted/unavailable.

        Do not call merely because a record is fading or absent from one result.
        No Brain or archive is read or changed by this method.
        """
        return self.forget(library_id, node_ids)

    def counts(self, library_id):
        library_id = _library(library_id)
        with self.db() as db:
            rows = db.execute("""
                SELECT kind,COUNT(*) AS count FROM memory_usage
                WHERE library_id=? AND pending_at IS NOT NULL GROUP BY kind
            """, (library_id,)).fetchall()
        result = {"recall": 0, "mention": 0}
        result.update({row["kind"]: row["count"] for row in rows})
        return {"pending": sum(result.values()), "by_kind": result}
