"""生命节律：反思（巩固）与 tick（醒来一次要做的事）。

为什么单独一个模块：
    存储和检索回答"记得什么"，这里回答"过了一夜之后，什么变了"。
    人不只是往脑子里塞东西，还会在空闲时把碎的东西压成一句判断。
    这一步不做，记忆永远是一堆平级的碎片，没有"看法"。

两个函数都是**纯本地、无 LLM 依赖**的。想让它说人话，传 `rewrite=` 进来。
"""
from __future__ import annotations

from .brain import Brain
from ..utils import now as _now


def reflect(brain: Brain, *, min_cluster: int = 3, max_new: int = 2,
            now: float | None = None, rewrite=None) -> dict:
    """把"同一件事反复出现"的碎片压成一条高层认知。

    聚类规则故意简单：按标签。标签是人挑的语义钩子，比自动聚类可解释。
    每个标签最多生成一条反思节点，重复调用不会重复生成。

    rewrite: 可选 `(members: list[dict]) -> str`，用 LLM 写一句人话总结。
             不传就用成员标题拼一句——难看，但每次都一样，可复现。
    """
    ts = now if now is not None else _now()

    buckets: dict[str, list[dict]] = {}
    for n in brain.nodes.values():
        state = brain._node_state(n, ts)
        if n["kind"] == "reflection" or not state["recoverable"] or state["state"] == "dormant":
            continue
        for t in n.get("tags", ()):
            if not t or t == "反思":
                continue
            buckets.setdefault(t, []).append({**n, "salience": state["effective_salience"]})

    done = {n["meta"].get("tag") for n in brain.nodes.values()
            if n["kind"] == "reflection"}

    created, skipped, skip_reasons = [], [], []
    for tag, members in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        if len(members) < min_cluster:
            continue
        if tag in done:
            skipped.append(tag)
            continue
        if len(created) >= max_new:
            break
        if len(brain.nodes) >= brain.config.max_nodes:
            # 反思是一项巩固任务，不能为了归纳而驱逐自己的来源成员。
            skipped.append(tag)
            skip_reasons.append({"tag": tag, "reason": "capacity_limit",
                                 "detail": "容量不足以新增反思节点，保留全部原始成员"})
            continue

        members = sorted(members, key=lambda n: -n["salience"])[:6]
        if rewrite is not None:
            text = rewrite(members)
        else:
            text = "；".join(m["label"] for m in members) + "。"

        sal = min(1.0, sum(m["salience"] for m in members) / len(members) * 1.15)
        imp = sum(m.get("impact", 0.0) for m in members) / len(members)
        nid = brain.add(
            f"关于「{tag}」", text, kind="reflection",
            tags=["反思", tag], salience=round(sal, 3), impact=round(imp, 3),
            meta={"tag": tag,
                  "members": [m["id"] for m in members],
                  "generated_at": ts},
        )
        for m in members:
            brain.link(nid, m["id"], 0.5)
        created.append({"id": nid, "tag": tag, "members": len(members)})

    return {"created": created, "skipped": skipped, "skip_reasons": skip_reasons, "at": ts}


def tick(brain: Brain, *, now: float | None = None, reflect_new: bool = True,
         max_reflect: int = 2) -> dict:
    """醒一次做的事。挂 cron / 定时任务，一天跑一次就够。

    顺序有讲究：先忘，再想，最后看有没有欠着的事。
    先忘是为了让反思别把快过期的碎片也归纳进去。
    """
    ts = now if now is not None else _now()
    forgot = brain.forget(now=ts)
    reflected = (reflect(brain, max_new=max_reflect, now=ts)
                 if reflect_new else {"created": [], "skipped": []})
    due = brain.due(now=ts)
    return {
        "at": ts,
        "forgot": forgot,
        "reflected": reflected,
        "due": due,
        "summary": (f"清掉 {forgot['dropped']} 个、变淡 {forgot['thinned']} 条边，"
                    f"新归纳 {len(reflected['created'])} 条，"
                    f"待办 {len(due)} 件"),
    }
