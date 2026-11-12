"""One rollback snapshot for a synchronous, nested operation on one Brain.

The caller still owns the graph's operation lock.  This guard only coordinates
rollback: an ingestion helper can be called alone or inside an HTTP transaction
without copying the same complete graph twice.  It is intentionally not an
incremental journal; anchor and duplicate updates can touch existing records.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from ..errors import ValidationError

_FIELDS = ("nodes", "edges", "meta", "_vec", "name", "config", "half_life")
_ACTIVE = ContextVar("love_house_brain_rollback_guards", default=())


class _Guard:
    def __init__(self, brain):
        self.brain = brain
        # A single deepcopy also preserves aliases such as config.half_life.
        self.before = deepcopy({key: getattr(brain, key) for key in _FIELDS})
        self.failed = False

    def check(self):
        if self.failed:
            raise ValidationError("本次事务中有操作失败，全部改动已取消，请重试")

    def persist(self):
        # A callback cannot catch an inner failure and accidentally persist its
        # partially applied mutation as a successful outer operation.
        self.check()
        return self.brain.persist()

    def restore(self):
        for key, value in self.before.items():
            setattr(self.brain, key, value)


@contextmanager
def rollback_guard(brain):
    """Reuse the outer snapshot, or own one when called independently.

    Nested exceptions make the whole operation rollback-only, even if an outer
    callback catches them.  Persistence must use the yielded guard's persist().
    No state is serialized, and unrelated Brain objects never share snapshots.
    """
    active = _ACTIVE.get()
    guard = next((item for item in reversed(active) if item.brain is brain), None)
    if guard is not None:
        try:
            yield guard
        except BaseException:
            guard.failed = True
            raise
        return

    guard = _Guard(brain)
    token = _ACTIVE.set((*active, guard))
    try:
        yield guard
        guard.check()
    except BaseException:
        guard.restore()
        raise
    finally:
        _ACTIVE.reset(token)
