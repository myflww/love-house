"""点火策略：查询 → 每个节点的初始激活。

默认实现 `OverlapScorer` 只用字面重合，不训练、不联网。
想接语义相似度，实现同样的 `__call__` 签名然后传给 `Brain(scorer=...)`。

分数公式（`docs/架构.md` 有推导）：

    base  = max( dice(Q,V), 0.7 * |Q∩V| / |Q| )
    tag   = 命中标签数
    score = (base^1.2 + 0.5*min(1,tag)) * (0.55 + 0.45*salience)

两种重合度取大：dice 对长文本稳，containment 对短问句敏。
"""
from __future__ import annotations

from typing import Protocol

from .encoders import Encoder, bigram


def dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


class SeedScorer(Protocol):
    name: str

    def __call__(self, nodes: dict, vecs: dict[str, set], query: str,
                 floor: float, encoder: Encoder) -> dict[str, float]: ...


class OverlapScorer:
    """字面重合 + 标签命中的加权和，再乘显著性。"""

    name = "overlap"

    def __call__(self, nodes: dict, vecs: dict[str, set], query: str,
                 floor: float = 0.06, encoder: Encoder = bigram) -> dict[str, float]:
        qv = encoder(query)
        if not qv:
            return {}
        qlen = max(1, len(qv))
        qlow = query.lower()
        scores: dict[str, float] = {}
        for nid, n in nodes.items():
            nv = vecs.get(nid) or set()
            inter = len(qv & nv)
            base = max(dice(qv, nv), 0.7 * inter / qlen)
            tag_hit = sum(1 for t in n.get("tags", ()) if t and t.lower() in qlow)
            if base < floor and not tag_hit:
                continue
            # 情绪冲击同等命中时优先：有感觉的事更该被想起
            boost = 1.0 + 0.35 * abs(n.get("impact", 0.0) or 0.0)
            scores[nid] = (base ** 1.2 + 0.5 * min(1, tag_hit)) * (
                0.55 + 0.45 * n["salience"]) * boost
        return scores
