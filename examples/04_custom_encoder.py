"""04 · 换掉编码器：不改图结构，只换"文本怎么变成可比的东西"。

默认编码器是字符二元组（零依赖、中文友好、不理解同义词）。
这个例子演示两种接法，都不需要改 nkb 的任何一行代码：

    A. 传函数          Brain(encode=my_encoder)
    B. 注册成名字      register_encoder("hit", fn) → Brain(encode="hit")

用一个玩具级"同义词归一 + 词袋"编码器做演示 —— 它的目的不是效果好，
而是让你看清接口只有一个：str -> set[str]。

跑： python3 examples/04_custom_encoder.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nkb import Brain
from nkb.retrieval.encoders import available, register_encoder

# ── 一个玩具编码器：先做同义词归一，再取二元组 ──
SYNONYMS = {
    "向量库": "向量检索",
    "向量数据库": "向量检索",
    "召回": "检索",
    "想起": "检索",
    "忘掉": "遗忘",
    "忘记": "遗忘",
}


def toy_encoder(text: str) -> set[str]:
    for src, dst in SYNONYMS.items():
        text = text.replace(src, dst)
    out = set()
    for chunk in text.replace("，", " ").replace("。", " ").split():
        if len(chunk) == 1:
            out.add(chunk)
        for i in range(len(chunk) - 1):
            out.add(chunk[i:i + 2])
    return out


def build(encode):
    b = Brain.new(encode=encode,
                  name=f"编码器对比：{encode if isinstance(encode, str) else '函数'}")
    b.add("向量检索", "只看相似度，不给关联路径。", kind="fact", tags=["检索"])
    b.add("激活扩散", "沿图扩散，能多跳联想。", kind="fact", tags=["检索"])
    b.add("遗忘曲线", "按半衰期衰减，久不用就淡。", kind="fact", tags=["遗忘"])
    b.link(list(b.nodes)[0], list(b.nodes)[1], 0.7)
    b.link(list(b.nodes)[1], list(b.nodes)[2], 0.5)
    return b


QUERIES = [
    "向量检索和召回有什么不同",   # 字面就能对上
    "忘掉旧东西会怎样",           # 字面完全对不上，只有同义词能救
]

for q in QUERIES:
    print("=" * 60)
    print(f"查询：{q}")
    print("=" * 60)
    for label, spec in [("bigram（默认）", None), ("toy（同义词归一）", toy_encoder)]:
        b = build(spec)
        r = b.recall(q, k=3)
        print(f"\n  {label}")
        if not r["hits"]:
            print("    没有命中 —— 编码器不认识查询里的词，就一条都召不回来")
        for h in r["hits"]:
            print(f'    [{h["score"]:.2f}] {h["label"]}  {h["depth"]} 跳  '
                  f'{" → ".join(h["path_labels"])}')
    print()

# ── 接法 B：注册成名字，之后到处都能用字符串引用 ──
register_encoder("toy", toy_encoder, overwrite=True)
print("\n已注册的编码器：", available())

b = Brain.new(encode="toy", name="按名字取编码器")
b.add("向量检索", "只看相似度。", tags=["检索"])
print("按名字构造 Brain 成功：", b.encoder.__name__)

print("""
接真 embedding 时只有一处要注意：
默认打分用集合交并（dice / containment），所以 encode 必须返回 set。
拿到的向量先量化，比如 {f"b{int(v*64)}" for v in vec}，或者
自己实现一个 SeedScorer 直接用余弦 —— 见 nkb/retrieval/scoring.py。
""")
