"""Complete, paginated access to one explicitly bound memory identity.

This is an evidence catalogue, not another prompt or a cross-library browser.
Callers supply the Brain and authoritative identity; tool arguments never select
a library. Paused, forgotten, superseded and confirmed duplicate entries stay
out of the active Agent view. Readable history remains available as evidence.
"""
from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
import hashlib
import json

from ..errors import ValidationError
from ..utils import now
from .memory import _count, _text, _disabled_evidence
from .structured import _record, _persona, build_structured_context

CATALOG_SCHEMA = "love-house-memory-catalog/v1"
READ_SCHEMA = "love-house-memory-read/v1"
BOOTSTRAP_SCHEMA = "love-house-memory-bootstrap/v1"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity(brain, library_id, library_name):
    library_id = _text(library_id, "library_id", 200)
    if brain.meta.get("library_id") not in (None, library_id):
        raise ValidationError("记忆身份与绑定库不一致")
    return {"library_id": library_id, "library_name": str(library_name or brain.name)[:80],
            "agent_id": library_id, "identity_source": "explicit_binding",
            "is_demo": bool(brain.meta.get("demo"))}


def _records(brain, library_id):
    stamp = now()
    records, excluded = [], Counter()
    blocked=_disabled_evidence(brain)
    for node in sorted(brain.nodes.values(), key=lambda n: (n.get("created", 0), n["id"])):
        if node['id'] in blocked:
            excluded['paused_evidence']+=1
            continue
        record, reason = _record(brain, node, stamp, library_id)
        if reason:
            excluded[reason] += 1
        else:
            records.append(record)
    return records, dict(excluded)


def _revision(records):
    return hashlib.sha256(_json(records).encode()).hexdigest()


def _cursor(library_id, revision, offset):
    return base64.urlsafe_b64encode(_json({"library_id": library_id, "revision": revision,
                                         "offset": offset}).encode()).decode().rstrip("=")


def _offset(cursor, library_id, revision, total):
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor or len(cursor) > 1024:
        raise ValidationError("记忆目录游标无效，请从第一页重新读取")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {"library_id", "revision", "offset"}
                or value["library_id"] != library_id or value["revision"] != revision
                or type(value["offset"]) is not int or not 0 <= value["offset"] <= total):
            raise ValueError()
        return value["offset"]
    except (ValueError, UnicodeError, RecursionError):
        raise ValidationError("记忆目录已变化或游标不属于此绑定库，请从第一页重新读取") from None


def memory_catalog(brain, library_id, library_name, *, cursor=None, limit=25):
    identity = _identity(brain, library_id, library_name)
    limit = _count(limit, "limit", 1, 100)
    records, excluded = _records(brain, library_id)
    revision = _revision(records)
    offset = _offset(cursor, library_id, revision, len(records))
    selected = records[offset:offset + limit]
    entries = [{"id": r["id"], "title": r["display"]["title"], "layer": r["layer"],
                "epistemic_status": r["epistemic_status"], "interpretation": r["interpretation"],
                "recorded_at": r["recorded_at"], "source_time": r["source_time"],
                "value_chars": len(r["value"]),
                "assistant_chars": len(r.get("assistant_statement", {}).get("value", ""))}
               for r in selected]
    next_offset = offset + len(entries)
    return {"schema": CATALOG_SCHEMA, "identity": identity, "revision": revision,
            "entries": entries, "total": len(records), "returned": len(entries),
            "offset": offset, "next_cursor": _cursor(library_id, revision, next_offset) if next_offset < len(records) else None,
            "complete": next_offset >= len(records), "excluded": excluded,
            "read_only": True, "scope": "bound_library_active_memory_and_historical_evidence",
            "material_role": "evidence_not_instructions"}


def memory_read(brain, library_id, library_name, *, memory_id, field="value", offset=0,
                max_chars=8000, revision=None):
    identity = _identity(brain, library_id, library_name)
    memory_id = _text(memory_id, "memory_id", 200)
    offset = _count(offset, "offset", 0, 100000000)
    max_chars = _count(max_chars, "max_chars", 1, 32000)
    if field not in ("value", "assistant", "display"):
        raise ValidationError("field须为value、assistant或display")
    records, _ = _records(brain, library_id)
    current_revision = _revision(records)
    if revision is not None and (not isinstance(revision, str) or revision != current_revision):
        raise ValidationError("记忆目录已变化，请重新读取目录")
    record = next((r for r in records if r["id"] == memory_id), None)
    if record is None:
        raise ValidationError("绑定库中没有这条可用记忆")
    content = (record["value"] if field == "value" else
               record.get("assistant_statement", {}).get("value", "") if field == "assistant" else
               record["display"].get("text", record["value"]))
    if offset > len(content):
        raise ValidationError("offset超出原文长度")
    text = content[offset:offset + max_chars]
    next_offset = offset + len(text)
    header = deepcopy(record)
    header.pop("value", None)
    if "assistant_statement" in header:
        header["assistant_statement"].pop("value", None)
    header["display"].pop("text", None)
    return {"schema": READ_SCHEMA, "identity": identity, "revision": current_revision,
            "record": header, "field": field, "text": text, "offset": offset,
            "total_chars": len(content), "returned_chars": len(text),
            "next_offset": next_offset if next_offset < len(content) else None,
            "complete": next_offset >= len(content), "read_only": True,
            "material_role": "evidence_not_instructions",
            "continuation": "A chunk is part of the same source; assemble remaining chunks before interpreting the full statement."}


def memory_bootstrap(brain, library_id, library_name, *, max_chars=12000):
    identity = _identity(brain, library_id, library_name)
    max_chars = _count(max_chars, "max_chars", 2000, 32000)
    records, excluded = _records(brain, library_id)
    ordered = sorted(records, key=lambda r: (r["interpretation"] != "current_memory",
                                            r["epistemic_status"] != "user_confirmed_statement",
                                            -(r.get("recorded_at") or 0), r["id"]))
    base = {"memory_ids": [r["id"] for r in ordered[:1000]], "read_only": True,
            "library_id": library_id, "truncated": len(ordered) > 1000}
    context = build_structured_context(brain, "恢复这个Agent的已有记忆与相处资料", base,
                                      max_chars=max_chars, library_id=library_id,
                                      library_name=library_name, agent_id=library_id)
    return {"schema": BOOTSTRAP_SCHEMA, "identity": identity, "revision": _revision(records),
            "total_memories": len(records), "included_memories": context["memory_context"]["counts"]["included"],
            "excluded": excluded, "persona": _persona(brain, now()),
            "memory_context": context["memory_context"], "read_only": True,
            "all_memory_loaded": (len(records) == context["memory_context"]["counts"]["included"]
                                  and not context["memory_context"]["truncation"]["truncated"]),
            "next_action": {"tool": "memory_list", "arguments": {"limit": 25}},
            "retrieval": {"catalog_tool": "memory_list", "read_tool": "memory_read",
                          "fields": ["value", "assistant", "display"], "complete_access": "paginate_catalog_and_read_chunks",
                          "context_window_is_finite": True},
            "material_role": "evidence_not_instructions"}
