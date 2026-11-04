"""Desktop-owned, opt-in review scheduling and current connection authority."""
from __future__ import annotations

import hashlib
import json
import threading
import time

from ..companion.review import (apply_review_plan, get_review_profile,
                                revalidate_sources, save_review_profile)
from ..errors import ValidationError
from ..organizer.idle_review import IdleReviewer


class IdleReviewService:
    def __init__(self, host, *, transport=None):
        self.host = host
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._active = set()
        self._enabled = set()
        self._activity = {}
        self._boot = time.time()
        self.engine = IdleReviewer(host.root, snapshot=self.snapshot, apply=self.apply,
            finalize=self.finalize, credential=host.organizer_credential, transport=transport)
        self.worker = threading.Thread(target=self._watch, name='love-house-idle-review', daemon=True)
        self.worker.start()

    def authorization(self, library_id):
        """Called under binding_lock. Excludes secrets, online state and counters."""
        with self.host.connections.db() as db:
            rows = db.execute('''SELECT id,session_scope_policy,bound_session_id,binding_revision
                FROM connections WHERE library_id=? AND enabled=1 AND revoked=0 ORDER BY id''',
                (library_id,)).fetchall()
            sources = db.execute('''SELECT id,connection_id,runtime_agent_id,platforms
                FROM agent_sources WHERE library_id=? ORDER BY id''', (library_id,)).fetchall()
        scopes = {r['id']: {'policy': r['session_scope_policy'], 'window_id': r['bound_session_id'],
                           'binding_revision': r['binding_revision']} for r in rows}
        value = {'library_id': library_id, 'scopes': scopes,
                 'sources': [dict(row) for row in sources if row['connection_id'] in scopes]}
        generation = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        return {'generation': generation, 'connection_ids': list(scopes),
                'connection_scopes': scopes, 'source_scopes': {
                    r['connection_id']: {'source_id': r['id'], 'runtime_agent_id': r['runtime_agent_id']}
                    for r in sources if r['connection_id'] in scopes}, 'allow_local': True}

    def snapshot(self, library_id):
        with self.host.connections.binding_lock:
            return {'brain': self.host.snapshot(library_id),
                    'authorization': self.authorization(library_id)}

    def contextual_snapshot(self, library_id):
        value = self.snapshot(library_id)
        value['brain'].setdefault('meta', {})['idle_review_current_authorization_generation'] = value['authorization']['generation']
        return value['brain']

    def apply(self, library_id, plan, *, commit_guard):
        with self.host.connections.binding_lock:
            auth = self.authorization(library_id)
            def commit(brain):
                return apply_review_plan(brain, plan, auth)
            return self.host.transact(library_id, commit, commit_guard=commit_guard)

    def finalize(self, library_id, expected, generation, commit):
        with self.host.connections.binding_lock:
            self.host.port_for(library_id)
            auth = self.authorization(library_id)
            def checked(brain):
                revalidate_sources(brain, library_id, auth, expected, generation)
                return commit()
            return self.host._servers[library_id].RequestHandlerClass.memory_read(checked)

    def touch(self, library_id):
        with self._lock:
            self._activity[library_id] = time.time()

    def settings(self, library_id, data):
        if not isinstance(data, dict) or set(data) - {'enabled', 'idle_seconds', 'batch_size'}:
            raise ValidationError('空闲回顾只接受开启状态、空闲时间和每批来源数')
        profile = self.host.transact(library_id, lambda b: save_review_profile(b, **data))
        with self._lock:
            if profile['enabled']:
                self._enabled.add(library_id)
            else:
                self._enabled.discard(library_id)
        self.touch(library_id)
        if not profile['enabled']:
            self.engine.cancel(library_id)
        return self.engine.status(library_id)

    def run(self, library_id):
        if self.host.library(library_id)['is_demo']:
            raise ValidationError('示例库不能调用回顾模型')
        return self._launch(library_id, manual=True)

    def _launch(self, library_id, *, manual=False, idle_for=0):
        with self._lock:
            if library_id in self._active:
                return {'queued': False, 'status': 'busy', 'library_id': library_id}
            self._active.add(library_id)
        def work():
            try:
                if manual:
                    self.engine.run_pending(library_id, manual=True)
                else:
                    with self._lock:
                        current_idle=time.time()-self._activity.get(library_id,self._boot)
                    self.engine.run_once(library_id, manual=False, idle_for=current_idle)
            except Exception:
                pass  # Engine records provider failures; missing/closed libraries are skipped.
            finally:
                with self._lock:
                    self._active.discard(library_id)
        threading.Thread(target=work, name='love-house-review-batch', daemon=True).start()
        return {'queued': True, 'status': 'queued', 'library_id': library_id}

    def _watch(self):
        # Discover persisted opt-ins once. A new installation never calls a model.
        for item in self.host.manager.list_libraries():
            if self._stop.is_set():
                return
            if item.get('is_demo') or not item.get('available'):
                continue
            try:
                if get_review_profile(self.host.manager.open_library(item['id']))['enabled']:
                    with self._lock:
                        self._enabled.add(item['id'])
            except Exception:
                continue
        while not self._stop.wait(15):
            with self._lock:
                eligible = [(lib, time.time() - self._activity.get(lib, self._boot)) for lib in self._enabled]
            for lib, idle in eligible:
                try:
                    profile = get_review_profile(self.host.manager.open_library(lib))
                    if profile['enabled'] and idle >= profile['idle_seconds']:
                        self._launch(lib, idle_for=idle)
                except Exception:
                    continue

    def stop(self):
        self._stop.set()
        self.engine.stop()
        self.worker.join(timeout=2)
