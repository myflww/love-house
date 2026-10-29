"""公开数据结构的类型定义。

运行时存的是普通 dict（要能直接进 JSON），这里只给类型，
让 IDE 和 mypy 能检查。字段名就是 `brain.json` 里的键名。
"""
from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class NodeDict(TypedDict, total=False):
    id: str
    kind: str
    label: str
    text: str
    tags: list[str]
    salience: float
    created: float
    reinforced: float
    decay_at: float
    recalls: int
    impact: float
    event_at: float
    event_recorded: bool
    session_id: str | None
    important: bool
    anchor_info: dict[str, Any]
    valid_from: float
    valid_to: float | None
    superseded_by: str | None
    meta: dict[str, Any]


class EdgeDict(TypedDict, total=False):
    w: float
    n: int
    last: float
    decay_at: float
    valid_from: float
    valid_to: float | None
    anchor_relations: list[dict[str, Any]]


class HitDict(TypedDict, total=False):
    id: str
    label: str
    kind: str
    tags: list[str]
    score: float
    depth: int
    path: list[str]
    path_labels: list[str]
    salience: float
    effective_salience: float
    state: str
    is_anchor: bool
    anchor_info: dict[str, Any] | None
    context_snippets: list[dict[str, Any]]
    protection_reason: str | None
    recalls: int
    age_days: float
    text: str


class TrailStep(TypedDict, total=False):
    from_: str      # 序列化时是 "from"
    to: str
    flow: float
    step: int


class RecallResultDict(TypedDict, total=False):
    query: str
    hits: list[HitDict]
    seeds: list[dict]
    trail: list[dict]
    steps: int
    visited: int
    note: str


class NodeStateDict(TypedDict, total=False):
    state: str                     # active / fading / dormant / forgotten
    effective_salience: float
    recoverable: bool
    recovery_days_left: float | None
    expired: bool
    superseded: bool
    forgotten_by_age: bool
    protected: bool
    protection_reason: str | None
    important: bool
    is_anchor: bool
    anchor_info: dict[str, Any] | None


@runtime_checkable
class Encoder(Protocol):
    """文本 -> 可比集合。默认实现是字符二元组。

    想接向量：返回量化后的集合即可；或者自己覆写 `SeedScorer`。
    """

    def __call__(self, text: str) -> set[str]: ...


@runtime_checkable
class Renderer(Protocol):
    """召回结果 -> 一段能塞进上下文的文本。"""

    name: str

    def __call__(self, result: dict, max_chars: int = 1800) -> str: ...
