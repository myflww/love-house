"""激活扩散：纯函数，不碰存储、不碰 Brain。

把它单独放一个文件，是因为这是整个项目唯一"有算法"的地方，
应该能脱离一切上下文被读懂、被单测。

    adj = adjacency(brain.edges)
    r = spread_activation(adj, seeds, steps=3, damping=0.6)
    r.act      # {node_id: 0~1}
    r.depth    # {node_id: 第几跳}
    r.parent   # {node_id: 从谁传过来}
    r.trail    # [{"from","to","flow","step"}]

三条不变量：
    1. 用 max 不用 sum —— 多路到达取最强那条，避免"度数高的节点"被加总冲爆。
    2. 每跳归一化 —— 分数才是"相对强度"，不是"跳得越远越大"。
    3. 保留系数 —— 不加这个，走两跳种子自己就消失了，可解释性会断。
"""
from __future__ import annotations

from dataclasses import dataclass, field


def adjacency(edges: dict[str, dict]) -> dict[str, list[tuple[str, float]]]:
    """{"a|b": {"w":0.5}} -> {"a":[("b",0.5)], "b":[("a",0.5)]}"""
    adj: dict[str, list] = {}
    for key, e in edges.items():
        a, b = key.split("|", 1)
        w = e["w"]
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))
    return adj


@dataclass(slots=True)
class SpreadResult:
    act: dict[str, float] = field(default_factory=dict)
    depth: dict[str, int] = field(default_factory=dict)
    parent: dict[str, str | None] = field(default_factory=dict)
    trail: list[dict] = field(default_factory=list)

    def path(self, nid: str, limit: int = 12) -> list[str]:
        chain, cur, guard = [], nid, 0
        while cur is not None and guard < limit:
            chain.append(cur)
            cur = self.parent.get(cur)
            guard += 1
        return list(reversed(chain))


def spread_activation(adj: dict[str, list[tuple[str, float]]],
                      seeds: dict[str, float],
                      steps: int = 3,
                      damping: float = 0.6,
                      retain: float = 0.86) -> SpreadResult:
    if not seeds:
        return SpreadResult()

    mx = max(seeds.values()) or 1.0
    act = {i: v / mx for i, v in seeds.items()}
    res = SpreadResult(act=dict(act),
                       depth={i: 0 for i in act},
                       parent={i: None for i in act})

    for step in range(steps):
        add: dict[str, float] = {}
        src: dict[str, str] = {}
        best: dict[str, float] = {}
        for a, av in act.items():
            for b, w in adj.get(a, ()):
                c = av * w * damping
                if c > add.get(b, 0.0):
                    add[b] = c
                    src[b] = a
                    best[b] = c
        if not add:
            break

        nxt = dict(add)
        for a, av in act.items():
            nxt[a] = max(nxt.get(a, 0.0), av * retain)
        m = max(nxt.values()) or 1.0

        for b in add:
            if b not in res.depth:
                res.depth[b] = step + 1
                res.parent[b] = src[b]
        for b, c in best.items():
            if res.depth.get(b, 99) == step + 1 and res.parent.get(b) == src[b]:
                res.trail.append({"from": src[b], "to": b,
                                  "flow": round(c / m, 4), "step": step + 1})

        act = {i: v / m for i, v in nxt.items()}

    res.act = act
    return res
