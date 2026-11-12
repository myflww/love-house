"""Import explicitly selected note contents, never read arbitrary local paths."""
from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from ..errors import ValidationError
from .markdown import TEXT_EXT, split_markdown

MAX_FILES = 20
MAX_NOTE_CHARS = 100000
MAX_IMPORT_NODES = 500
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)(?:[^\]]*)\]\]")


def _parts(files, mode, kind):
    if mode not in ("heading", "whole"):
        raise ValidationError("mode 只能是 heading 或 whole")
    if not isinstance(kind, str) or kind not in ("doc", "fact", "concept", "preference"):
        raise ValidationError("导入类型只能是 doc/fact/concept/preference")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValidationError(f"每批请选择 1~{MAX_FILES} 个笔记文件")
    parts = []
    for file in files:
        if not isinstance(file, dict):
            raise ValidationError("每个文件必须包含 name 与 text")
        name, text = file.get("name"), file.get("text")
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise ValidationError("文件名称必须是 1~500 字的字符串")
        path = PurePosixPath(name.replace("\\", "/"))
        if path.suffix.lower() not in TEXT_EXT:
            raise ValidationError("只支持 Markdown、TXT 和 RST 笔记")
        if not isinstance(text, str) or len(text) > MAX_NOTE_CHARS:
            raise ValidationError(f"每个文件正文不能超过 {MAX_NOTE_CHARS} 字")
        pairs = [(path.stem, text)] if mode == "whole" else split_markdown(text)
        # A heading-only note is still meaningful knowledge; do not silently drop it.
        if not pairs and text.strip():
            pairs = [(path.stem, text)]
        for label, body in pairs:
            if not label.strip() and not body.strip():
                continue
            digest = hashlib.sha256((kind + "\0" + label + "\0" + body).encode()).hexdigest()
            parts.append({"source": f"{name}#{label}", "file": name,
                          "label": label, "text": body, "kind": kind,
                          "fingerprint": digest})
        if len(parts) > MAX_IMPORT_NODES:
            raise ValidationError(f"每批最多导入 {MAX_IMPORT_NODES} 个节点；请分批或按整篇导入")
    return parts


def plan_notes(brain, files, *, mode="heading", kind="doc"):
    """Pure preview; unchanged original imports stay duplicates even after manual edits."""
    parts = _parts(files, mode, kind)
    known = {n.get("meta", {}).get("import_fingerprint") for n in brain.nodes.values()}
    for part in parts:
        key = part["fingerprint"]
        part["status"] = "duplicate" if key in known else "new"
        known.add(key)
    added = sum(p["status"] == "new" for p in parts)
    remaining = (None if brain.config.max_nodes is None
                 else max(0, brain.config.max_nodes - len(brain.nodes)))
    if remaining is not None and added > remaining:
        raise ValidationError(f"本批需要 {added} 个空位，当前剩余 {remaining}；请减少文件或调整容量")
    return {"items": [{k: p[k] for k in ("source", "label", "status")} for p in parts],
            "added": added, "skipped": len(parts) - added, "total": len(parts),
            "read_only": True}


def import_notes(brain, files, *, mode="heading", kind="doc"):
    """Apply a validated batch. The HTTP adapter wraps this and persist in one transaction."""
    plan = plan_notes(brain, files, mode=mode, kind=kind)
    parts = _parts(files, mode, kind)
    ids = []
    for part, item in zip(parts, plan["items"]):
        if item["status"] == "duplicate":
            continue
        nid = brain.add(part["label"], part["text"], kind=kind,
                        tags=[PurePosixPath(part["file"]).stem, "笔记导入"], salience=.65,
                        meta={"source": part["source"], "file": part["file"],
                              "import_fingerprint": part["fingerprint"]})
        ids.append(nid)
    # Only create explicit links from unambiguous [[note]] references. Unrelated
    # files must not become factual associations merely to make a fuller picture.
    names = {}
    for nid, node in brain.nodes.items():
        keys = {node["label"]}
        name = node.get("meta", {}).get("file")
        if name:
            keys.add(str(PurePosixPath(name).with_suffix("")))
            keys.add(PurePosixPath(name).stem)
        for key in keys:
            names.setdefault(key, set()).add(nid)
    linked = 0
    for nid in ids:
        targets = set()
        for match in WIKI_LINK.findall(brain.nodes[nid]["text"]):
            key = match.strip().removesuffix(".md")
            candidates = names.get(key, set())
            if len(candidates) == 1:
                targets.update(candidates)
        for target in sorted(targets - {nid}):
            brain.link(nid, target, .65)
            linked += 1
    return {"ids": ids, "added": len(ids), "skipped": plan["skipped"], "linked": linked}
