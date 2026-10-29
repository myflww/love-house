"""02 · 把一个 markdown 目录导进知识库。

跑： python3 examples/02_ingest_docs.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from nkb import Brain
from nkb.ingest import ingest_dir
from nkb.viz import build

b = Brain.new(HERE / "docs-demo.json", name="导入示例")

# 按 Markdown 标题切块，每块一个节点，标签取自目录名
info = ingest_dir(b, HERE / "seed", kind="doc", mode="heading")
b.save()

print("=" * 56)
print("规模：", b.stats())

print("\n导入的节点：")
for n in b.nodes.values():
    src = n["meta"].get("source", "")
    print(f'  · {n["label"]:<24} {src}')
    nb = b.neighbors(n["id"])
    if nb:
        print(f'    邻居：{"、".join(b.nodes[i]["label"] for i, _ in nb[:3])}')

print("\n" + "=" * 56)
r = b.recall("为什么需要遗忘")
print("检索「为什么需要遗忘」：")
for h in r["hits"]:
    print(f'  [{h["score"]:.2f}] {h["label"]} · {h["depth"]} 跳')
    print(f'         {" → ".join(h["path_labels"])}')

# 顺手导出一份可视化，直接打开看
out = build(b, HERE / "docs-demo.html")
print(f"\n可视化已导出：{out}")
