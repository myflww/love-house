"""评测：只测检索，不测模型。

为什么不做"端到端准确率"：那要一个 LLM 当裁判，费用高、结论飘，
而且测的是模型的答题能力，不是这个库记不记得住。
这里测两件能离线复现的事：

    leave_one_out   拿每个节点的标题当查询，看它能不能把自己召回来
    probes          自定义探针：必须命中某条 / 必须承认不知道

跑：
    nkb bench                      留一法
    nkb bench --probes probes.json  自定义探针
"""
from __future__ import annotations

import json
from pathlib import Path

from .core.brain import Brain


def leave_one_out(brain: Brain, k: int = 5, sample: int | None = None) -> dict:
    """留一法：用节点自己的标题去查，看它排第几。

    这个指标衡量的是"索引有没有把已知的东西弄丢"，跟模型无关。
    反思节点会被排除（它们的标题是"关于X"，本来就不该靠字面命中）。
    """
    targets = [n for n in brain.nodes.values()
               if n["kind"] != "reflection" and n.get("valid_to") is None]
    if sample:
        targets = targets[:sample]

    rows, hit, rr = [], 0, 0.0
    for n in targets:
        r = brain.recall(n["label"], k=max(k, 10))
        labels = [h["label"] for h in r["hits"]]
        try:
            rank = labels.index(n["label"]) + 1
        except ValueError:
            rank = None
        if rank and rank <= k:
            hit += 1
            rr += 1.0 / rank
        rows.append({"label": n["label"], "kind": n["kind"],
                     "rank": rank, "top": labels[:3]})

    total = len(rows) or 1
    missed = [r for r in rows if not r["rank"] or r["rank"] > k]
    return {
        "mode": "leave_one_out",
        "cases": len(rows),
        "hit_rate": round(hit / total, 3),
        "mrr": round(rr / total, 3),
        "missed": missed[:10],
        "rows": rows,
    }


def run_probes(brain: Brain, probes: list[dict], k: int = 5) -> dict:
    """自定义探针。

    每条：{"query": "...", "expect": ["标题"], "abstain": false}
      expect   命中其中任意一个算对
      abstain  为 true 时，必须**没有**命中才算对（考"承认不知道"）
    """
    rows = []
    for p in probes:
        q = p["query"]
        r = brain.recall(q, k=k)
        labels = [h["label"] for h in r["hits"]]
        if p.get("abstain"):
            ok = len(labels) == 0
            why = "正确地说不知道" if ok else f"编了：{labels[:2]}"
        else:
            ok = any(e in labels for e in p.get("expect", []))
            why = "命中" if ok else f"没命中，得到 {labels[:2]}"
        rows.append({"query": q, "ok": ok, "why": why, "got": labels[:k]})
    total = len(rows) or 1
    return {"mode": "probes", "cases": len(rows),
            "hit_rate": round(sum(1 for r in rows if r["ok"]) / total, 3),
            "rows": rows}


def load_probes(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text("utf-8"))


def format_report(result: dict, verbose: bool = False) -> str:
    lines = []
    if result["mode"] == "leave_one_out":
        lines.append(f"留一法：{result['cases']} 条，命中率 {result['hit_rate']:.0%}，"
                     f"MRR {result['mrr']:.2f}")
        if result["missed"]:
            lines.append(f"没召回的 {len(result['missed'])} 条：")
            for m in result["missed"]:
                got = "、".join(m["top"]) or "空"
                lines.append(f"  · {m['label']:<20} 得到：{got}")
        if verbose:
            for r in result["rows"]:
                lines.append(f"  {r['rank'] or '—':>3}  {r['label']}")
    else:
        lines.append(f"探针：{result['cases']} 条，通过率 {result['hit_rate']:.0%}")
        for r in result["rows"]:
            mark = "✓" if r["ok"] else "✗"
            lines.append(f"  {mark} {r['query']}  —  {r['why']}")
    return "\n".join(lines)
