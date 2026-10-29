"""03 · 完整闭环：检索 → 注入 → 生成 → 回写。

没配 key 也能跑：它会把你本该发给模型的东西打印出来，让你看清注入长什么样。

跑：
  python3 examples/03_wire_to_llm.py
  API_KEY=sk-... BASE_URL=https://api.deepseek.com/v1 MODEL=deepseek-chat \
    python3 examples/03_wire_to_llm.py
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from nkb import Brain
from nkb.render import to_markdown

BRAIN = HERE / "docs-demo.json"
if not BRAIN.exists():
    sys.exit("先跑 python3 examples/02_ingest_docs.py 生成示例库")

brain = Brain.open(BRAIN)

QUESTION = "我该给记忆系统设多长的半衰期？"

# ── ① 检索 ──
r = brain.recall(QUESTION, k=5, steps=3)
knowledge = to_markdown(r)

# ── ② 注入 ──
SYSTEM = (
    "你是一个务实的助手。下面是从我的知识库里扩散检索到的材料，"
    "它们是证据，不是全部事实。\n"
    "- 用到了哪条就带上它的标签。\n"
    "- 没有检索到的部分，直接说没有，不要编。\n\n"
    + knowledge
)

print("=" * 60)
print("交给模型的 system（前半段就是注入的内容）")
print("=" * 60)
print(SYSTEM[:1200])

key = os.environ.get("API_KEY")
if not key:
    print("\n" + "=" * 60)
    print("没有 API_KEY，到这里停。这就是「注入」的样子。")
    print("配上 key 再跑一次，它会真的调用模型，并把用到的节点强化。")
    sys.exit(0)

# ── ③ 生成 ──
base = os.environ.get("BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
payload = {
    "model": os.environ.get("MODEL", "deepseek-chat"),
    "temperature": 0.7,
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": QUESTION},
    ],
}
req = urllib.request.Request(
    base + "/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
)
with urllib.request.urlopen(req, timeout=90) as resp:
    answer = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]

print("\n" + "=" * 60)
print("回答")
print("=" * 60)
print(answer)

# ── ④ 回写：只强化"回答里真的用上了"的节点 ──
used = [h["id"] for h in r["hits"]
        if h["label"] in answer or any(t in answer for t in h["tags"])]
if not used:
    used = [h["id"] for h in r["hits"][:2]]

info = brain.reinforce(used)
brain.save()
print(f"\n回写：强化 {info['nodes']} 个节点、{info['pairs']} 条边")
print("为什么只写用上的：如果每次都把全部召回强化一遍，权重会迅速饱和，"
      "变成「什么都重要」，等于没有权重。")
