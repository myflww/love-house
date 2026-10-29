"""把现成的文档导进知识库。

切法只有两种，够用且可预期：
  heading  按 Markdown 标题切（没有标题就按空行切段落）
  whole    整个文件一个节点

刻意不做自动摘要、不做 LLM 抽取。理由：那是黑箱，导入后你没法解释
"这条知识为什么在这儿"。标题就是最好的人工结构，用它。
"""
from __future__ import annotations

import re
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
TEXT_EXT = {".md", ".markdown", ".txt", ".rst"}


def split_markdown(text: str) -> list[tuple[str, str]]:
    """按标题切成 (标题, 正文)。第一个标题之前的内容归到「概述」。"""
    marks = list(HEADING.finditer(text))
    if not marks:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return [(f"段落 {i + 1}", p) for i, p in enumerate(paras)]

    out = []
    head = text[:marks[0].start()].strip()
    if head:
        out.append(("概述", head))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        title = m.group(2).strip()
        if body or title:
            out.append((title, body))
    return out


def ingest_dir(brain, root: str | Path, kind: str = "doc",
               mode: str = "heading", tags_from_path: bool = True,
               link: bool = True, verbose: bool = True) -> dict:
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"目录不存在: {root}")

    added, skipped = 0, 0
    for f in sorted(root.rglob("*")):
        if f.suffix.lower() not in TEXT_EXT or not f.is_file():
            continue
        raw = f.read_text("utf-8", errors="replace")
        rel = str(f.relative_to(root))
        parts = []
        if tags_from_path:
            parts = [p for p in Path(rel).with_suffix("").parts[:-1]]
        pairs = ([(f.stem, raw)] if mode == "whole" else split_markdown(raw))

        for title, body in pairs:
            if not body and mode != "whole":
                continue
            src = f"{rel}#{title}"
            if any(n["meta"].get("source") == src for n in brain.nodes.values()):
                skipped += 1
                continue
            nid = brain.add(
                label=title,
                text=body,
                kind=kind,
                tags=parts + [Path(rel).stem],
                salience=0.65,
                meta={"source": src, "file": rel},
            )
            if link:
                brain.auto_link(nid, top=2)
            added += 1

    if verbose:
        print(f"导入完成：新增 {added} 条，跳过 {skipped} 条（已存在）")
    return {"added": added, "skipped": skipped, "path": str(root)}


def ingest_text(brain, text: str, source: str = "manual", kind: str = "doc",
                link: bool = True) -> dict:
    added = 0
    for title, body in split_markdown(text):
        if not body:
            continue
        nid = brain.add(title, body, kind=kind, tags=["导入"],
                        meta={"source": f"{source}#{title}"})
        if link:
            brain.auto_link(nid, top=2)
        added += 1
    return {"added": added}
