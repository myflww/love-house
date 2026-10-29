"""01 · 最短的完整例子：建库、连边、检索、学习、遗忘。

跑： python3 examples/01_quickstart.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nkb import Brain
from nkb.render import to_markdown

# ── 1. 建 ──
b = Brain.new("demo-quickstart.json", name="手冲咖啡")

咖啡 = b.add("手冲咖啡", "热水穿过咖啡粉层的萃取方式。", kind="concept",
             tags=["咖啡"], salience=0.9)
研磨 = b.add("研磨度", "粉越细，接触面积越大，萃取越快，也越容易过萃发苦。",
             kind="fact", tags=["咖啡", "参数", "研磨"], salience=0.8)
水温 = b.add("水温", "浅烘用 92~94℃，深烘用 86~88℃。", kind="fact",
             tags=["咖啡", "参数", "温度"], salience=0.75)
# 标签是人工语义钩子。默认检索是字面重合，口语化短问句很难命中，
# 靠标签把"苦"这种口语词挂到节点上，是最省事的解法。
苦 = b.add("苦味来源", "主要来自过萃和深烘，少量来自咖啡因。", kind="fact",
           tags=["风味", "苦", "过萃"], salience=0.6)
上次翻车 = b.add("上次冲得太苦", "磨太细 + 水温 95℃ + 闷蒸 45 秒，三个变量一起偏了。",
                 kind="episode", tags=["经验", "苦", "翻车"], salience=0.7)

b.link(咖啡, 研磨, 0.7)
b.link(咖啡, 水温, 0.7)
b.link(研磨, 苦, 0.6)
b.link(水温, 苦, 0.5)
b.link(上次翻车, 研磨, 0.55)
b.link(上次翻车, 水温, 0.5)

print("=" * 56)
print("库：", b.stats())

# ── 2. 检索（看路径，不只是看结果） ──
r = b.recall("冲出来有点苦，是哪里不对")
print("\n问题：冲出来有点苦，是哪里不对")
for h in r["hits"]:
    print(f'  [{h["score"]:.2f}] {h["label"]} · {h["depth"]} 跳')
    print(f'         路径：{" → ".join(h["path_labels"])}')

# ── 3. 注入模型的那段文本 ──
print("\n" + "=" * 56)
print(to_markdown(r))

# ── 4. 学习：这次一起想到的，下次更容易一起想到 ──
ekey = "|".join(sorted((研磨, 苦)))
before = b.edges[ekey]["w"]
info = b.reinforce([h["id"] for h in r["hits"][:4]])
after = b.edges[ekey]["w"]
print("\n强化：", info, f"研磨⇄苦 边权 {before:.3f} → {after:.3f}")

# ── 5. 遗忘：把时间拨到 300 天后 ──
import time
dropped = b.forget(now=time.time() + 300 * 86400)
print("300 天后：", dropped)
print("剩下的节点：", [n["label"] for n in b.nodes.values()])

b.save()
print("\n已存到 demo-quickstart.json —— 用 nkb serve -b 这个文件 可以看可视化")
