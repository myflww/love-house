"""Brain —— 门面类。把所有零件装成一件能用的东西。

它自己不实现算法：
    存储   -> storage.StorageBackend（默认 JsonFileStorage，原子写）
    编码   -> retrieval.encoders.Encoder（默认 bigram）
    点火   -> retrieval.scoring.SeedScorer（默认 OverlapScorer）
    扩散   -> retrieval.spread.spread_activation（纯函数）
    配置   -> config.Config（默认值 < 库文件 < 显式传入 < 环境变量）

每一层都能单独换、单独测。Brain 只负责把它们串起来并守住不变量：
边的键永远是 "小id|大id"，权重永远落在 (0, 1)，被删的节点不会留下悬空边。
"""
from __future__ import annotations

import uuid
import math
from bisect import bisect_left, bisect_right
from copy import deepcopy
from pathlib import Path

from ..config import DEFAULT_HALF_LIFE, Config  # noqa: F401  (对外沿用)
from ..errors import NotFound, ValidationError
from ..retrieval.encoders import Encoder, get_encoder
from ..retrieval.scoring import OverlapScorer, SeedScorer, dice  # noqa: F401
from ..retrieval.spread import adjacency, spread_activation
from ..storage.base import StorageBackend
from ..storage.jsonfile import JsonFileStorage
from ..utils import DAY, fmt_age, now as _now  # noqa: F401

SCHEMA_VERSION = 1


class Brain:
    """一张会自己变化的知识图。"""

    def __init__(self, data: dict | None = None, path: str | Path | None = None,
                 encode: Encoder | str | None = None,
                 storage: StorageBackend | None = None,
                 config: Config | None = None,
                 scorer: SeedScorer | None = None):
        data = deepcopy(data or {})
        if data.get("version", SCHEMA_VERSION) > SCHEMA_VERSION:
            raise ValidationError(
                f"知识库版本 {data['version']} 比当前库 {SCHEMA_VERSION} 新，请升级 neural-kb")

        self.path = Path(path) if path else None
        self.storage = storage or (JsonFileStorage(self.path) if self.path else None)
        self.encoder = get_encoder(encode)
        self.scorer = scorer or OverlapScorer()

        self.name = data.get("name", "untitled")
        self.nodes: dict[str, dict] = data.get("nodes", {})
        self.edges: dict[str, dict] = data.get("edges", {})
        self.meta: dict = data.get("meta", {"created": _now()})

        saved = dict(data.get("config") or {})
        saved.setdefault("half_life", data.get("half_life"))
        base = Config.from_dict(saved)
        if config is not None:
            merged = base.to_dict()
            for k, v in config.to_dict().items():
                merged[k] = ({**base.half_life, **(config.half_life or {})}
                             if k == "half_life" else v)
            base = Config.from_dict(merged)
        self.config = base.with_env()
        # Personal adaptive libraries have no semantic node-count budget. A
        # legacy saved limit or environment override must not restore eviction
        # when a read snapshot is reconstructed or a batch import is staged.
        if self._adaptive_retention_enabled():
            self.config.max_nodes = None
        self.half_life = self.config.half_life   # 兼容旧属性名；环境变量优先级最高
        self._migrate()

        self._vec: dict[str, set] = {nid: self._vec_for(n) for nid, n in self.nodes.items()}

    # ────────────────────────── 生命周期 ──────────────────────────
    @classmethod
    def new(cls, path=None, name="untitled", **kw) -> "Brain":
        return cls({"name": name}, path=path, **kw)

    @classmethod
    def open(cls, path, **kw) -> "Brain":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"找不到知识库文件: {p}")
        storage = kw.pop("storage", None) or JsonFileStorage(p)
        return cls(storage.load(), path=p, storage=storage, **kw)

    def _migrate(self) -> None:
        """无损补齐旧库。decay_at 是显著性/边权已经提交到的时间。"""
        if self.meta.get("schema_version", SCHEMA_VERSION) < SCHEMA_VERSION:
            self.meta["schema_version"] = SCHEMA_VERSION
        for n in self.nodes.values():
            n.setdefault("meta", {})
            n.setdefault("impact", 0.0)
            n.setdefault("reinforced", n.get("created", _now()))
            n.setdefault("decay_at", n["reinforced"])
            n.setdefault("valid_from", n.get("created", n["reinforced"]))
            n.setdefault("valid_to", None)
            n.setdefault("superseded_by", None)
            n.setdefault("important", bool(n["meta"].get("important")) or n["salience"] >= self.config.important_threshold)
            n.setdefault("event_at", n["meta"].get("event_at", n.get("created")))
            n.setdefault("event_recorded", n["kind"] == "episode" or "event_at" in n["meta"])
            n.setdefault("event_explicit", "event_at" in n["meta"] or
                         (bool(n.get("event_recorded")) and n["kind"] != "episode") or
                         n.get("event_at") != n.get("created"))
            n.setdefault("session_id", n["meta"].get("session_id"))
            for snippet in (n.get("anchor_info") or {}).get("context_snippets", []):
                source = self.nodes.get(snippet["id"])
                # 旧摘录没有创建时间时，已遗忘来源只能从本次加载以后安全展示。
                snippet.setdefault("created", source.get("created", _now()) if source else _now())
                snippet.setdefault("captured_at", snippet["created"])
        for e in self.edges.values():
            e.setdefault("n", 1)
            e.setdefault("decay_at", e.get("last", _now()))
            e.setdefault("valid_from", e.get("last"))
            e.setdefault("valid_to", None)

    def save(self, path=None):
        p = Path(path) if path else self.path
        if p is None:
            raise ValidationError("没有指定保存路径")
        if self.storage is None or Path(getattr(self.storage, "path", p)) != p:
            self.storage = JsonFileStorage(p)
        self.meta["updated"] = _now()
        self.storage.save(self.to_dict())
        self.path = p
        return p

    def persist(self):
        """有路径就存，没有就跳过。工具层用它，避免临时库崩在 save 上。"""
        return self.save() if self.path else None

    def to_dict(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "name": self.name,
            "half_life": self.half_life,
            "config": self.config.to_dict(),
            "meta": self.meta,
            "nodes": self.nodes,
            "edges": self.edges,
        }

    # ────────────────────────── 写 ──────────────────────────
    def add(self, label: str, text: str = "", kind: str = "concept",
            tags: list[str] | None = None, salience: float = 0.6,
            id: str | None = None, meta: dict | None = None,
            impact: float = 0.0, event_at: float | None = None,
            session_id: str | None = None) -> str:
        if not isinstance(label, str):
            raise ValidationError("label 必须是字符串")
        label = label.strip()
        if not label:
            raise ValidationError("label 不能为空")
        salience = self._number(salience, "salience", 0.0, 1.0)
        impact = self._number(impact, "impact", -1.0, 1.0)
        if meta is not None and not isinstance(meta, dict):
            raise ValidationError("meta 必须是字典")
        details = deepcopy(meta or {})
        if "important" in details and not isinstance(details["important"], bool):
            raise ValidationError("meta.important 必须是布尔值")
        event_explicit = event_at is not None or "event_at" in details
        event_recorded = event_explicit or kind == "episode"
        event_at = event_at if event_at is not None else details.get("event_at")
        session_id = session_id if session_id is not None else details.get("session_id")
        if event_at is not None:
            event_at = self._number(event_at, "event_at")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise ValidationError("session_id 必须是非空字符串或 None")
        if session_id is not None:
            session_id = session_id.strip()
        nid = id or f"n_{uuid.uuid4().hex[:10]}"
        if not isinstance(nid, str) or "|" in nid or not nid.strip():
            raise ValidationError("id 必须是非空字符串且不能包含 |")
        if nid in self.nodes:
            raise ValidationError(f"节点已存在: {nid}")
        if not isinstance(kind, str) or not kind.strip():
            raise ValidationError("kind 必须是非空字符串")
        if not isinstance(text, str):
            raise ValidationError("text 必须是字符串")
        if tags is not None and (not isinstance(tags, list) or any(not isinstance(t, str) for t in tags)):
            raise ValidationError("tags 必须是字符串列表")
        ts = _now()
        self._make_room(ts)
        self.nodes[nid] = {
            "id": nid, "kind": kind, "label": label, "text": text or "",
            "tags": list(tags or []), "salience": float(salience),
            "created": ts, "reinforced": ts, "decay_at": ts, "recalls": 0,
            "impact": float(impact),
            "valid_from": ts, "valid_to": None, "superseded_by": None,
            "event_at": ts if event_at is None else event_at,
            "event_recorded": event_recorded, "event_explicit": event_explicit, "session_id": session_id,
            "important": bool(details.get("important")) or salience >= self.config.important_threshold,
            "meta": details,
        }
        self._vec[nid] = self._vec_for(self.nodes[nid])
        self._sync_anchors()
        return nid

    def update(self, nid: str, **fields) -> dict:
        """编辑当前记录；编辑不是提起，不更新 reinforced 或 recalls。"""
        n = self._must(nid)
        candidate = deepcopy(n)
        ts = _now()
        adaptive = self._adaptive_retention_enabled()
        # 先按旧规则结算到编辑时刻，不能用新 impact/kind 追溯重算整段历史。
        # Adaptive strength is a read projection from the original base and
        # genuine use traces. Editing prose must not turn that projection into
        # a second decaying base or fabricate another practice event.
        if not adaptive and ts >= n.get("decay_at", n["reinforced"]):
            candidate["salience"] = self._effective_salience(n, ts)
            candidate["decay_at"] = ts
        for k in ("label", "text", "kind"):
            if k in fields:
                if not isinstance(fields[k], str):
                    raise ValidationError(f"{k} 必须是字符串")
                candidate[k] = fields[k]
        candidate["label"] = candidate["label"].strip()
        candidate["kind"] = candidate["kind"].strip()
        if not candidate["label"]:
            raise ValidationError("label 不能为空")
        if "tags" in fields:
            if not isinstance(fields["tags"], list) or any(not isinstance(t, str) for t in fields["tags"]):
                raise ValidationError("tags 必须是字符串列表")
            candidate["tags"] = list(fields["tags"])
        if not isinstance(candidate["kind"], str) or not candidate["kind"].strip():
            raise ValidationError("kind 必须是非空字符串")
        if not isinstance(candidate["text"], str):
            raise ValidationError("text 必须是字符串")
        if "salience" in fields:
            candidate["salience"] = self._number(fields["salience"], "salience", 0.0, 1.0)
            candidate["decay_at"] = max(ts, n.get("decay_at", ts))
            candidate["important"] = candidate["salience"] >= self.config.important_threshold
        if "impact" in fields:
            candidate["impact"] = self._number(fields["impact"], "impact", -1.0, 1.0)
        metadata = fields.get("meta", {})
        if not isinstance(metadata, dict):
            raise ValidationError("meta 必须是字典")
        if "meta" in fields:
            if "important" in metadata and not isinstance(metadata["important"], bool):
                raise ValidationError("meta.important 必须是布尔值")
            candidate["meta"].update(deepcopy(metadata))
            if "important" in metadata:
                candidate["important"] = metadata["important"]
        if adaptive and "salience" in fields:
            # Apply an explicit new base after the UI's metadata merge, which
            # may include the old complete metadata object. Real practice and
            # counters remain intact; only its now-stale base cache is cleared.
            usage = candidate["meta"].get("memory_usage")
            if isinstance(usage, dict):
                usage.pop("base_salience", None)
                usage.pop("base_at", None)
        for key in ("event_at", "session_id"):
            supplied = key in fields or key in metadata
            value = fields.get(key, metadata.get(key, candidate.get(key)))
            if key == "event_at":
                candidate[key] = self._number(value, key)
                if supplied:
                    candidate["event_explicit"] = True
            elif value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValidationError("session_id 必须是非空字符串或 None")
            else:
                candidate[key] = value.strip() if isinstance(value, str) else value
            if supplied:
                if candidate[key] is None:
                    candidate["meta"].pop(key, None)
                elif key in candidate["meta"]:
                    candidate["meta"][key] = candidate[key]
        candidate["event_recorded"] = candidate["kind"] == "episode" or bool(candidate.get("event_explicit"))
        # 编码也属于校验阶段，失败时保留原节点与全部关系。
        vector = self._vec_for(candidate)
        candidate["updated"] = max(ts, candidate["created"])
        n.clear()
        n.update(candidate)
        self._vec[nid] = vector
        self._sync_anchors()
        return n

    def remove(self, nid: str, *, _sync: bool = True) -> bool:
        if nid not in self.nodes:
            return False
        source = self.nodes[nid]
        invalid_at = source.get("valid_to")
        if invalid_at is None and source.get("superseded_by"):
            invalid_at = _now()
        if invalid_at is not None:
            # 保存明确失效证据，避免来源随后删除使旧归纳重新成为有效事实。
            for reflection in self.nodes.values():
                members = reflection.get("meta", {}).get("members", [])
                if reflection["kind"] == "reflection" and isinstance(members, list) and nid in members:
                    archived = reflection["meta"].get("invalidated_members")
                    if not isinstance(archived, dict):
                        archived = reflection["meta"]["invalidated_members"] = {}
                    archived[nid] = invalid_at
        del self.nodes[nid]
        self._vec.pop(nid, None)
        for key in [k for k in self.edges if nid in k.split("|", 1)]:
            del self.edges[key]
        if _sync:
            # 显式删除也清掉独立保存的该来源摘录；时间遗忘/容量回收保留有限摘录。
            for n in self.nodes.values():
                info = n.get("anchor_info")
                if info:
                    info["context_snippets"] = [s for s in info.get("context_snippets", []) if s["id"] != nid]
            self._sync_anchors()
        return True

    def link(self, a: str, b: str, w: float = 0.35) -> float:
        if a == b:
            raise ValidationError("不能自连")
        self._must(a)
        self._must(b)
        w = self._number(w, "w", 0.0, 1.0)
        if w == 0:
            raise ValidationError("w 必须大于 0")
        top = self.config.edge_max
        ts = _now()
        key = self._key(a, b)
        e = self.edges.get(key)
        if e and (e.get("valid_to") is None or e["valid_to"] > ts):
            e["w"] = round(min(top, self._edge_weight(e, ts) + w * 0.5), 4)
            e["last"] = e["decay_at"] = ts
            e["n"] += 1
        else:
            self.edges[key] = {"w": round(min(top, max(0.0, w)), 4),
                               "n": 1, "last": ts, "decay_at": ts,
                               "valid_from": ts, "valid_to": None}
        self.edges[key].pop("automatic_anchor", None)  # 显式连边取得该关系的所有权
        return self.edges[key]["w"]

    def unlink(self, a: str, b: str) -> bool:
        return self.edges.pop(self._key(a, b), None) is not None

    def auto_link(self, nid: str, top: int | None = None, floor: float = 0.0):
        """按字面重合把新节点接到最近的既有节点。孤岛节点永远不会被扩散带到。"""
        node = self._must(nid)
        top = self.config.auto_link_top if top is None else top
        v = self._vec[nid]
        ts = _now()
        if not self._node_state(node, ts)["recoverable"]:
            return []
        scored = [(dice(v, self._vec[o["id"]]), o["id"])
                  for o in self.nodes.values() if o["id"] != nid
                  and self._node_state(o, ts)["recoverable"]]
        scored.sort(reverse=True)
        out = []
        for d, oid in scored[:top]:
            if d <= floor:
                continue
            w = self.link(nid, oid, min(0.6, 0.22 + d))
            out.append((oid, w))
        return out

    # ────────────────────────── 时效：事实会过期 ──────────────────────────
    def invalidate(self, a: str, b: str, at: float | None = None) -> bool:
        """标记一条连接"从那以后不再成立"。不删除，只是让它退出检索。"""
        key = self._key(a, b)
        e = self.edges.get(key)
        if not e:
            return False
        e["valid_to"] = self._number(at, "at") if at is not None else _now()
        return True

    def supersede(self, old: str, new: str, at: float | None = None) -> str:
        """旧事实被新事实取代。旧节点保留（历史可查），但默认不再被召回。"""
        o = self._must(old)
        n = self._must(new)
        chain = set()
        current = new
        while current is not None and current not in chain:
            if current == old:
                raise ValidationError("事实替代不能自指或形成循环")
            chain.add(current)
            current = self.nodes.get(current, {}).get("superseded_by")
        ts = self._number(at, "at") if at is not None else _now()
        o["valid_to"] = ts
        o["superseded_by"] = new
        n["valid_from"] = ts
        self.link(old, new, 0.5)
        self.edges[self._key(old, new)]["valid_from"] = ts
        return new

    def history(self, nid: str) -> list[dict]:
        """一条知识的完整生命：什么时候生效、什么时候失效、被谁取代。"""
        n = self._must(nid)
        chain, cur, guard = [], nid, 0
        while cur and guard < 20:
            node = self.nodes.get(cur)
            if not node:
                break
            chain.append({"id": cur, "label": node["label"],
                          "valid_from": node.get("valid_from"),
                          "valid_to": node.get("valid_to"),
                          "superseded_by": node.get("superseded_by")})
            cur = node.get("superseded_by")
            guard += 1
        return chain

    # ────────────────────────── 前瞻记忆：承诺与到期 ──────────────────────────
    def commit(self, what: str, due: float | None = None, **kw) -> str:
        nid = self.add(what, kw.pop("text", ""), kind="commitment",
                       tags=kw.pop("tags", ["承诺"]), salience=0.85,
                       impact=kw.pop("impact", 0.4),
                       meta={"due": due, "status": "open", **kw.pop("meta", {})})
        self.auto_link(nid, top=2)   # 承诺要挂在已有知识上，孤岛永远不会被想起
        return nid

    def due(self, within: float | None = None, now: float | None = None) -> list[dict]:
        """还没了结的承诺。within 给了就只看这段时间内到期的。"""
        ref = _now() if now is None else now
        out = []
        for n in self.nodes.values():
            if n["kind"] != "commitment" or n["meta"].get("status") != "open":
                continue
            d = n["meta"].get("due")
            if d is None:
                continue
            if within is not None and d > ref + within:
                continue
            out.append({"id": n["id"], "label": n["label"], "due": d,
                        "overdue_days": round((ref - d) / DAY, 1)})
        return sorted(out, key=lambda x: x["due"])

    def resolve(self, nid: str, note: str = "") -> dict:
        n = self._must(nid)
        n["meta"]["status"] = "done"
        n["meta"]["done_at"] = _now()
        if note:
            n["meta"]["note"] = note
        ts = _now()
        n["salience"] = min(1.0, self._effective_salience(n, ts) * 0.8 + 0.2)
        n["decay_at"] = ts
        return n

    # ────────────────────────── 学习 / 遗忘 ──────────────────────────
    def reinforce(self, ids: list[str], lr: float | None = None,
                  bump: float | None = None, now: float | None = None) -> dict:
        """显式提起才强化。休眠可唤醒；超窗、失效或被取代的事实不能复活。"""
        cfg = self.config
        lr = self._number(cfg.hebbian_lr if lr is None else lr, "lr", 0.0, 1.0)
        bump = self._number(cfg.salience_bump if bump is None else bump, "bump", 0.0, 1.0)
        ts = _now() if now is None else self._number(now, "now")
        requested = list(dict.fromkeys(ids))
        eligible = {i: self._node_state(self.nodes[i], ts) for i in requested if i in self.nodes}
        ids = [i for i, state in eligible.items() if state["recoverable"]]
        ids = [i for i in ids if ts >= self.nodes[i].get("decay_at", self.nodes[i]["reinforced"])]
        adaptive = self._adaptive_retention_enabled()
        if adaptive:
            from ..companion.retention import record_memory_use
            used = record_memory_use(self, ids[:128], kind="recall", now=ts)
            ids = used["updated_ids"]
        pairs = 0
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if lr == 0:
                    continue
                key = self._key(a, b)
                e = self.edges.get(key)
                if e is None:
                    self.edges[key] = {"w": round(min(cfg.edge_max, lr), 4),
                                       "n": 1, "last": ts, "decay_at": ts,
                                       "valid_from": ts, "valid_to": None}
                elif e.get("valid_to") is not None and e["valid_to"] <= ts:
                    continue  # 联合回忆不等于重新声明一条失效的事实关系
                else:
                    e["w"] = round(min(cfg.edge_max,
                                       self._edge_weight(e, ts) + lr * (1.0 - self._edge_weight(e, ts))), 4)
                    e["n"] += 1
                    e["last"] = e["decay_at"] = ts
                    e.pop("automatic_anchor", None)
                pairs += 1
        for i in ([] if adaptive else ids):
            n = self.nodes[i]
            n["salience"] = min(1.0, self._effective_salience(n, ts) * (1 - bump) + bump)
            n["reinforced"] = n["decay_at"] = ts
            n["recalls"] += 1
        return {"nodes": len(ids), "pairs": pairs, "reinforced_ids": ids,
                "skipped_ids": [i for i in requested if i not in ids]}

    def forget(self, now: float | None = None) -> dict:
        """提交与 preview 相同的分段衰减；相同时间重复执行完全幂等。"""
        ref = _now() if now is None else self._number(now, "now")
        adaptive = self._adaptive_retention_enabled()
        self._sync_anchors(create_edges=False)  # 删除前固化有限真实摘录
        dropped = []
        for nid, n in list(self.nodes.items()):
            state = self._node_state(n, ref)
            # 被取代的事实是可查的历史记录，不因默认检索失效而删除。
            if state["forgotten_by_age"] and n.get("valid_to") is None and not n.get("superseded_by"):
                dropped.append(nid)
            elif not adaptive and ref >= n.get("decay_at", n["reinforced"]):
                n["salience"] = self._effective_salience(n, ref)
                n["decay_at"] = ref
        for nid in dropped:
            self.remove(nid, _sync=False)
        thinned = 0
        for key, e in list(self.edges.items()):
            if not adaptive and ref >= e.get("decay_at", e.get("last", ref)):
                e["w"] = self._edge_weight(e, ref)
                e["decay_at"] = ref
            if e["w"] < 0.02 and not adaptive:
                del self.edges[key]
                thinned += 1
        return {"dropped": len(dropped), "dropped_ids": dropped, "thinned": thinned, "at": ref}

    # ────────────────────────── 读 ──────────────────────────
    def get(self, nid: str) -> dict | None:
        return self.nodes.get(nid)

    def _live_edges(self, as_of: float | None = None,
                    allowed: set[str] | None = None,
                    strict_from: bool = False) -> dict[str, dict]:
        """只保留在 as_of 时刻有效的边。没有 valid_to 的边永不过期（兼容旧数据）。"""
        ref = _now() if as_of is None else as_of
        out = {}
        for key, e in self.edges.items():
            a, b = key.split("|", 1)
            if a not in self.nodes or b not in self.nodes:
                continue
            if allowed is not None and (a not in allowed or b not in allowed):
                continue
            if e.get("valid_to") is not None and e["valid_to"] <= ref:
                continue
            if strict_from and e.get("valid_from") is not None and e["valid_from"] > ref:
                continue
            if strict_from and e.get("last", 0) > ref:
                continue
            weight = self._edge_weight(e, ref)
            if weight >= 0.02:
                out[key] = {**e, "w": weight}
        return out

    def neighbors(self, nid: str, as_of: float | None = None) -> list[tuple[str, float]]:
        out = []
        for key, e in self._live_edges(as_of).items():
            a, b = key.split("|", 1)
            if a == nid:
                out.append((b, e["w"]))
            elif b == nid:
                out.append((a, e["w"]))
        return sorted(out, key=lambda x: -x[1])

    def seed_scores(self, query: str, as_of: float | None = None) -> dict[str, float]:
        ref = _now() if as_of is None else as_of
        projected = {nid: {**n, "salience": self._effective_salience(n, ref)}
                     for nid, n in self.nodes.items() if self._version_known(n, ref)}
        return self.scorer(projected, self._vec, query,
                           self.config.seed_floor, self.encoder)

    def recall(self, query: str, steps: int | None = None, k: int | None = None,
               damping: float | None = None, retain: float | None = None,
               kinds: list[str] | None = None,
               min_score: float | None = None,
               include_expired: bool = False,
               as_of: float | None = None,
               candidate_ids: set[str] | None = None) -> dict:
        # Internal selection can reserve a retrieval lane for organized records
        # without deleting their raw evidence from this Brain. Lifecycle checks
        # still apply; a supplied ID never authorizes an inactive node.
        if candidate_ids is not None:
            if not isinstance(candidate_ids, (set, frozenset, list, tuple)) or any(not isinstance(i, str) for i in candidate_ids):
                raise ValidationError("candidate_ids必须是本图节点ID集合")
            candidate_ids = set(candidate_ids)
        cfg = self.config
        steps = cfg.steps if steps is None else steps
        k = cfg.k if k is None else k
        damping = cfg.damping if damping is None else damping
        retain = cfg.retain if retain is None else retain
        min_score = cfg.min_score if min_score is None else min_score

        ref = _now() if as_of is None else self._number(as_of, "as_of")
        states = {nid: self._node_state(n, ref) for nid, n in self.nodes.items()}
        allowed = {nid for nid, n in self.nodes.items()
                   if (not kinds or n["kind"] in kinds)
                   and (candidate_ids is None or nid in candidate_ids)
                   and states[nid]["history_available"]
                   and n.get("valid_from", n["created"]) <= ref
                   and (not n.get("event_recorded") or n.get("event_at", 0) <= ref)
                   and (include_expired or states[nid]["recoverable"])}
        seeds = {i: v for i, v in self.seed_scores(query, as_of=ref).items() if i in allowed}
        if not seeds:
            return {"query": query, "hits": [], "steps": steps, "seeds": [],
                    "trail": [], "visited": 0,
                    "note": "没有命中任何节点（宁可说没有，也不假装记得）"}

        res = spread_activation(adjacency(self._live_edges(ref, allowed, strict_from=True)), seeds,
                                steps=steps, damping=damping, retain=retain)

        hits = []
        for nid, score in sorted(res.act.items(), key=lambda kv: -kv[1]):
            if len(hits) >= k:
                break
            if score < min_score:
                continue
            n = self.nodes[nid]
            chain = res.path(nid)
            hits.append({
                "id": nid, "label": n["label"], "kind": n["kind"],
                "tags": n["tags"], "score": round(score, 4),
                "depth": res.depth.get(nid, 0), "recalls": n["recalls"],
                "salience": states[nid]["effective_salience"],
                "effective_salience": states[nid]["effective_salience"],
                "state": states[nid]["state"],
                "is_anchor": states[nid]["is_anchor"],
                "anchor_info": deepcopy(states[nid]["anchor_info"]),
                "context_snippets": deepcopy((states[nid]["anchor_info"] or {}).get("context_snippets", [])),
                "protection_reason": states[nid]["protection_reason"],
                "age_days": round((ref - n["created"]) / DAY, 1),
                "path": chain,
                "path_labels": [self.nodes[i]["label"] for i in chain if i in self.nodes],
                "text": n["text"],
            })
        return {
            "query": query,
            "hits": hits,
            "seeds": [{"id": i, "score": round(v, 4)} for i, v in
                      sorted(seeds.items(), key=lambda kv: -kv[1])[:8]],
            "trail": res.trail,
            "steps": steps,
            "visited": len(res.act),
        }

    def stats(self) -> dict:
        ws = [e["w"] for e in self.edges.values()]
        kinds: dict[str, int] = {}
        for n in self.nodes.values():
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        return {
            "name": self.name,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "kinds": kinds,
            "strength": round(sum(ws), 3),
            "mean_w": round(sum(ws) / len(ws), 4) if ws else 0.0,
            "salience_sum": round(sum(n["salience"] for n in self.nodes.values()), 3),
            "recalls": sum(n["recalls"] for n in self.nodes.values()),
        }

    def export(self, as_of: float | None = None) -> dict:
        """只读图谱快照。时间推演、检索、遗忘共用同一套状态公式。"""
        ref = _now() if as_of is None else self._number(as_of, "as_of")
        known = {nid: n for nid, n in self.nodes.items() if n["created"] <= ref}
        states = {nid: self._node_state(n, ref) for nid, n in known.items()}
        degrees = {nid: 0 for nid in known}
        edges = []
        for key, e in self.edges.items():
            a, b = key.split("|", 1)
            if a not in states or b not in states:
                continue
            if not all(states[i]["history_available"] for i in (a, b)):
                continue
            if e.get("valid_from", 0) is not None and e.get("valid_from", 0) > ref:
                continue
            if e.get("last", 0) > ref:
                continue  # 没有旧边权版本，不能把后来新建/强化的边冒充历史
            effective = self._edge_weight(e, ref)
            valid = (e.get("valid_to") is None or e["valid_to"] > ref)
            valid = valid and (e.get("valid_from") is None or e["valid_from"] <= ref)
            active = valid and effective >= 0.02 and all(states[i]["recoverable"] for i in (a, b))
            if active:
                degrees[a] += 1
                degrees[b] += 1
            edges.append({"source": a, "target": b, "w": round(effective, 6),
                          "effective_w": round(effective, 6), "stored_w": e["w"],
                          "n": e.get("n", 1), "last": e.get("last"),
                          "valid_from": e.get("valid_from"), "valid_to": e.get("valid_to"),
                          "state": "active" if active else "expired" if not valid else "dormant",
                          "active": active,
                          "anchor_relations": deepcopy(e.get("anchor_relations", []))})
        nodes = []
        for nid, n in known.items():
            if states[nid]["history_available"]:
                projected = {**deepcopy(n), **states[nid],
                              "half_life": self.half_life.get(n["kind"]),
                              "due": n["meta"].get("due"), "status": n["meta"].get("status"),
                              "degree": degrees[nid]}
                replacement = n.get("superseded_by")
                if replacement is not None and (replacement not in states or not states[replacement]["history_available"]):
                    projected["superseded_by"] = None
                nodes.append(projected)
            else:
                # 本项目没有旧正文版本仓库。保留已知ID占位，绝不输出未来版本内容。
                nodes.append({"id": nid, "created": n["created"], "kind": "unknown",
                              "label": "该时刻的旧版本不可用", "text": "", "tags": [], "meta": {},
                              "salience": 0.0, "recalls": 0, "degree": 0,
                              "half_life": None, "due": None, "status": None,
                              **states[nid]})
        counts = {state: 0 for state in ("active", "fading", "dormant", "forgotten")}
        for state in states.values():
            counts[state["state"]] += 1
        active_weights = [e["effective_w"] for e in edges if e["active"]]
        kinds: dict[str, int] = {}
        for n in nodes:
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        stats = {**self.stats(), "states": counts,
                 "nodes": len(nodes), "edges": len(edges), "kinds": kinds,
                 "recalls": sum(n["recalls"] for n in nodes),
                 "anchors": sum(s["is_anchor"] for s in states.values()),
                 "protected": sum(s["protected"] for s in states.values()),
                 "active_edges": sum(e["active"] for e in edges),
                 "strength": round(sum(active_weights), 3),
                 "mean_w": round(sum(active_weights) / len(active_weights), 4) if active_weights else 0.0,
                 "salience_sum": round(sum(s["effective_salience"] for s in states.values()), 3),
                 "effective_salience_sum": round(sum(s["effective_salience"] for s in states.values()), 3),
                 "retention_mode": "adaptive" if self._adaptive_retention_enabled() else "legacy",
                 "capacity": None if self._adaptive_retention_enabled() else self.config.max_nodes,
                 "capacity_remaining": (None if self._adaptive_retention_enabled() or self.config.max_nodes is None else
                                        max(0, self.config.max_nodes - len(nodes)))}
        return {"name": self.name, "nodes": nodes, "edges": edges,
                "stats": stats, "half_life": deepcopy(self.half_life),
                "config": self.config.to_dict(), "as_of": ref,
                "preview_days": 0.0, "read_only": True,
                "updated": self.meta.get("updated")}

    def preview(self, days: float = 0.0, now: float | None = None) -> dict:
        """非破坏性推演，绝不保存、强化或删除任何节点。days 是从 now 向后推的天数。"""
        days = self._number(days, "days", 0.0)
        base = _now() if now is None else self._number(now, "now")
        result = self.export(as_of=base + days * DAY)
        result["preview_days"] = days
        return result

    def _protection_reason(self, n: dict) -> str | None:
        if abs(n.get("impact", 0.0)) >= self.config.anchor_threshold:
            return "emotional_anchor"
        if n.get("important") or n.get("meta", {}).get("important"):
            return "important"
        if n["kind"] == "commitment" and n.get("meta", {}).get("status") == "open":
            return "open_commitment"
        if self.half_life.get(n["kind"]) is None:
            return "persistent_kind"
        return None

    def _adaptive_retention_enabled(self) -> bool:
        value = self.meta.get("memory_retention")
        return bool(isinstance(value, dict) and value.get("schema") == "love-house-retention/v1"
                    and value.get("mode") == "adaptive")

    def _effective_salience(self, n: dict, ref: float) -> float:
        value = float(n["salience"])
        if self._adaptive_retention_enabled():
            from ..companion.retention import adaptive_strength
            value = adaptive_strength(self, n, ref)
            reason = self._protection_reason(n)
            if reason in ("emotional_anchor", "important", "open_commitment"):
                value = max(0.65, value)
            elif reason == "persistent_kind":
                value = max(float(n["salience"]), value)
            return min(1.0, max(0.0, value))
        hl = self.half_life.get(n["kind"])
        if hl is not None:
            hl *= 1.0 + 1.5 * abs(n.get("impact", 0.0))
            days = max(0.0, (ref - n.get("decay_at", n["reinforced"])) / DAY)
            value *= 0.5 ** (days / hl)
        reason = self._protection_reason(n)
        if reason in ("emotional_anchor", "important"):
            value = max(0.65, value)  # 重要核心长期可见，上下文不继承这个地位
        return min(1.0, max(0.0, value))

    def _node_state(self, n: dict, ref: float) -> dict:
        effective = self._effective_salience(n, ref)
        age = max(0.0, (ref - n["reinforced"]) / DAY)
        valid_to = n.get("valid_to")
        superseded = bool(n.get("superseded_by")) and (valid_to is None or valid_to <= ref)
        expired = (valid_to is not None and valid_to <= ref) or superseded
        invalidated_members = self._invalidated_members(n, ref)
        expired = expired or bool(invalidated_members) or bool(n.get("meta", {}).get("memory_disabled"))
        future = (n.get("created", 0) > ref or n.get("valid_from", n.get("created", 0)) > ref
                  or (n.get("event_recorded") and n.get("event_at", 0) > ref))
        reason = self._protection_reason(n)
        adaptive = self._adaptive_retention_enabled()
        forgotten_by_age = (reason is None and age > self.config.recovery_days
                            and not self.meta.get("long_term_archive") and not adaptive)
        forgotten = expired or forgotten_by_age
        recoverable = not forgotten and not future
        if forgotten:
            state = "forgotten"
        elif future or effective < max(0.18, self.config.drop_below):
            state = "dormant"
        elif effective < 0.45:
            state = "fading"
        else:
            state = "active"
        is_anchor = abs(n.get("impact", 0.0)) >= self.config.anchor_threshold
        anchor_info = deepcopy(n.get("anchor_info")) if is_anchor else None
        if is_anchor and anchor_info is None:
            anchor_info = self._anchor_info(n)
        if anchor_info:
            projected_snippets = []
            for snippet in anchor_info.get("context_snippets", []):
                source = self.nodes.get(snippet["id"])
                created = snippet.get("created", source.get("created") if source else None)
                event_at = source.get("event_at") if source else snippet.get("event_at")
                if (created is None or created > ref or event_at is None or event_at > ref
                        or snippet.get("captured_at", created) > ref):
                    continue
                if source and source.get("meta", {}).get("memory_disabled"):
                    continue
                if source and source.get("session_id") != n.get("session_id"):
                    continue
                snippet["source_present"] = source is not None
                source_valid = source is not None and (source.get("valid_to") is None or source["valid_to"] > ref) and source.get("valid_from", source["created"]) <= ref
                source_recent = source is not None and (self._adaptive_retention_enabled() or self._protection_reason(source) is not None or
                                (ref - source["reinforced"]) / DAY <= self.config.recovery_days)
                snippet["source_available"] = bool(source_valid and source_recent)
                snippet["is_excerpt"] = True
                projected_snippets.append(snippet)
            anchor_info["context_snippets"] = projected_snippets
            for field, relation in (("before_ids", "context_before"), ("after_ids", "context_after"),
                                    ("bridge_ids", "bridge")):
                visible = {s["id"] for s in projected_snippets if s["relation"] == relation}
                anchor_info[field] = [nid for nid in anchor_info.get(field, []) if nid in visible]
            bridge_ids = set(anchor_info.get("bridge_ids", []))
            bridges = []
            for bridge in anchor_info.get("bridges", []):
                other = self.nodes.get(bridge["other_anchor"])
                other_created = other.get("created") if other else bridge.get("other_anchor_created")
                other_event_at = other.get("event_at") if other else bridge.get("other_anchor_event_at")
                if other_created is None or other_event_at is None or other_created > ref or other_event_at > ref:
                    continue
                event_ids = [nid for nid in bridge["event_ids"] if nid in bridge_ids]
                if event_ids:
                    bridges.append({**bridge, "event_ids": event_ids})
            anchor_info["bridges"] = bridges
            known_bridge_ids = {nid for bridge in bridges for nid in bridge["event_ids"]}
            anchor_info["bridge_ids"] = [nid for nid in anchor_info.get("bridge_ids", []) if nid in known_bridge_ids]
            anchor_info["context_snippets"] = [s for s in projected_snippets
                                                if s["relation"] != "bridge" or s["id"] in known_bridge_ids]
        result = {"state": state, "effective_salience": round(effective, 8),
                "retention_mode": "adaptive" if adaptive else "legacy",
                "strength_model": "practice_power_law_approximation/v1" if adaptive else "exponential_half_life",
                "recoverable": recoverable, "expired": expired,
                "superseded": superseded, "forgotten_by_age": forgotten_by_age,
                "recovery_days_left": (None if reason or adaptive or self.meta.get("long_term_archive") else
                                       round(max(0.0, self.config.recovery_days - age), 3)),
                "protected": bool(reason) and not expired,
                "protection_reason": reason if not expired else None,
                "important": bool(n.get("important")),
                "is_anchor": is_anchor, "anchor_info": anchor_info,
                "history_available": self._version_known(n, ref)}
        if invalidated_members:
            result["invalidated_members"] = invalidated_members
            result["invalidation_reason"] = "source_invalidated"
        if not result["history_available"]:
            result.update({"state": "dormant", "effective_salience": 0.0,
                           "recoverable": False, "recovery_days_left": None,
                           "expired": False, "superseded": False, "forgotten_by_age": False,
                           "protected": False, "protection_reason": None,
                           "important": False, "is_anchor": False,
                           "anchor_info": {"before_ids": [], "after_ids": [], "bridge_ids": [],
                                           "bridges": [], "context_snippets": []},
                           "history_note": "该时刻的旧正文未保存；当前版本在所选时间之后写入或修改"})
            result.pop("invalidated_members", None)
            result.pop("invalidation_reason", None)
        return result

    def _invalidated_members(self, n: dict, ref: float) -> list[str]:
        if n["kind"] != "reflection":
            return []
        metadata = n.get("meta", {})
        members = metadata.get("members", [])
        archived = metadata.get("invalidated_members", {})
        if not isinstance(members, list):
            return []
        archived = archived if isinstance(archived, dict) else {}
        invalid = []
        for nid in members:
            if not isinstance(nid, str):
                continue
            source = self.nodes.get(nid)
            at = source.get("valid_to") if source else archived.get(nid)
            explicit = source and source.get("superseded_by") and at is None
            if explicit or (isinstance(at, (int, float)) and at <= ref):
                invalid.append(nid)
        # 年龄遗忘或普通删除不是事实被纠正，不能仅凭来源缺失废掉巩固结果。
        return invalid

    @staticmethod
    def _version_known(n: dict, ref: float) -> bool:
        return n.get("created", 0) <= ref and n.get("updated", n.get("created", 0)) <= ref

    def _edge_weight(self, e: dict, ref: float) -> float:
        days = max(0.0, (ref - e.get("decay_at", e.get("last", ref))) / DAY)
        return e["w"] * 0.5 ** (days / self.config.edge_half_life)

    def _make_room(self, ref: float) -> None:
        """旧实验库可按数量回收；个人自适应记忆绝不以消息数量驱逐。"""
        if self.config.max_nodes is None or self._adaptive_retention_enabled():
            return
        needed = len(self.nodes) - self.config.max_nodes + 1
        if needed <= 0:
            return
        candidates = [(not s["forgotten_by_age"], s["effective_salience"], n["reinforced"], nid)
                      for nid, n in self.nodes.items()
                      for s in [self._node_state(n, ref)] if not s["protected"]]
        if len(candidates) < needed:
            raise ValidationError("知识库容量已满且剩余节点均受保护；请提高 max_nodes 或明确删除节点")
        removed = []
        for _, _, _, nid in sorted(candidates)[:needed]:
            self.remove(nid, _sync=False)
            removed.append(nid)
        # 仅保存总量和最后一批，避免容量日志本身无限增长。
        self.meta["capacity_evictions"] = self.meta.get("capacity_evictions", 0) + len(removed)
        self.meta["last_capacity_evicted_ids"] = removed

    def _anchor_info(self, n: dict) -> dict:
        return {"trigger": "emotional_impact", "threshold": self.config.anchor_threshold,
                "impact": n.get("impact", 0.0), "event_at": n.get("event_at", n["created"]),
                "session_id": n.get("session_id"), "before_ids": [], "after_ids": [],
                "bridge_ids": [], "bridges": [], "context_snippets": [],
                "note": None if n.get("session_id") else "缺少会话标识，仅保留事件自身，不猜测上下文"}

    @staticmethod
    def _context_snippet(n: dict, relation: str) -> dict:
        return {"id": n["id"], "label": n.get("label", "")[:200],
                "excerpt": n.get("text", n.get("excerpt", ""))[:240],
                "created": n.get("created"),
                "captured_at": max(n.get("created", 0), n.get("updated", n.get("captured_at", n.get("created", 0)))),
                "event_at": n["event_at"], "session_id": n.get("session_id"),
                "relation": relation, "is_excerpt": True}

    def _sync_anchors(self, *, create_edges: bool = True) -> None:
        """写入时更新有限的真实事件引用。读取永远不扩写记忆。"""
        groups: dict[str, list[dict]] = {}
        anchors = {}
        old_infos = {n["id"]: deepcopy(n.get("anchor_info", {})) for n in self.nodes.values()}
        ts = _now()
        for n in self.nodes.values():
            is_anchor = abs(n.get("impact", 0.0)) >= self.config.anchor_threshold
            if is_anchor:
                n["anchor_info"] = self._anchor_info(n)
                anchors[n["id"]] = n
            else:
                n.pop("anchor_info", None)
            if n.get("session_id") and (n.get("event_recorded") or is_anchor) and n.get("event_at", ts) <= ts:
                groups.setdefault(n["session_id"], []).append(n)
        desired: dict[str, list[dict]] = {}

        def relation(anchor, event, kind):
            if anchor["id"] == event["id"]:
                return
            key = self._key(anchor["id"], event["id"])
            desired.setdefault(key, []).append({"anchor": anchor["id"], "kind": kind,
                                               "session_id": anchor.get("session_id")})

        for events in groups.values():
            events.sort(key=lambda n: (n["event_at"], n["created"], n["id"]))
            times = [n["event_at"] for n in events]
            positions = {n["id"]: i for i, n in enumerate(events)}
            group_anchors = [n for n in events if n["id"] in anchors]
            for anchor in group_anchors:
                info = anchor["anchor_info"]
                at = anchor["event_at"]
                index = positions[anchor["id"]]
                window = self.config.context_window_hours * 3600
                left = bisect_left(times, at - window)
                right = bisect_right(times, at + window)
                before = events[max(left, index - self.config.context_before):index]
                after = events[index + 1:min(right, index + 1 + self.config.context_after)]
                for field, members, kind in (("before_ids", before, "context_before"),
                                             ("after_ids", after, "context_after")):
                    archived = [snippet for snippet in old_infos[anchor["id"]].get("context_snippets", [])
                                if snippet["id"] not in self.nodes
                                and snippet["relation"] == kind and snippet.get("session_id") == anchor["session_id"]
                                and (snippet["event_at"] <= at if kind == "context_before" else snippet["event_at"] >= at)
                                and abs(snippet["event_at"] - at) <= window]
                    candidates = {snippet["id"]: self._context_snippet(snippet, kind) for snippet in archived}
                    candidates.update({event["id"]: self._context_snippet(event, kind) for event in members})
                    ordered = sorted(candidates.values(), key=lambda s: (s["event_at"], s["id"]))
                    maximum = self.config.context_before if kind == "context_before" else self.config.context_after
                    selected = (ordered[-maximum:] if kind == "context_before" else ordered[:maximum]) if maximum else []
                    info[field] = [snippet["id"] for snippet in selected]
                    info["context_snippets"].extend(selected)
                    for snippet in selected:
                        if snippet["id"] in self.nodes:
                            relation(anchor, self.nodes[snippet["id"]], kind)
            for first, second in zip(group_anchors, group_anchors[1:]):
                gap = second["event_at"] - first["event_at"]
                if gap > self.config.bridge_window_hours * 3600:
                    continue
                middle = {event["id"]: event for event in events[positions[first["id"]] + 1:positions[second["id"]]]}
                for anchor in (first, second):
                    for snippet in old_infos[anchor["id"]].get("context_snippets", []):
                        if snippet["id"] not in self.nodes and snippet["relation"] == "bridge" and snippet.get("session_id") == first["session_id"] and first["event_at"] < snippet["event_at"] < second["event_at"]:
                            middle.setdefault(snippet["id"], snippet)
                middle = sorted(middle.values(), key=lambda event: (event["event_at"], event["id"]))
                maximum = min(self.config.bridge_max_events - len(anchor["anchor_info"]["bridge_ids"])
                              for anchor in (first, second))
                if maximum == 0 or not middle:
                    continue
                if len(middle) > maximum:
                    # 等距抽取有限条已存事件；不会生成两锚点之间不存在的事情。
                    middle = ([middle[len(middle) // 2]] if maximum == 1 else
                              [middle[round(i * (len(middle) - 1) / (maximum - 1))] for i in range(maximum)])
                ids = [n["id"] for n in middle]
                for anchor, other in ((first, second), (second, first)):
                    info = anchor["anchor_info"]
                    info["bridges"].append({"other_anchor": other["id"], "event_ids": ids,
                                            "other_anchor_created": other["created"],
                                            "other_anchor_event_at": other["event_at"]})
                    info["bridge_ids"] = list(dict.fromkeys(info["bridge_ids"] + ids))
                    for event in middle:
                        info["context_snippets"].append(self._context_snippet(event, "bridge"))
                        if event["id"] in self.nodes:
                            relation(anchor, event, "bridge")
        for key, e in list(self.edges.items()):
            if "anchor_relations" not in e:
                continue
            relations = desired.get(key, [])
            if relations:
                e["anchor_relations"] = relations
            elif e.get("automatic_anchor"):
                del self.edges[key]
            else:
                e.pop("anchor_relations", None)
        if create_edges:
            for key, relations in desired.items():
                e = self.edges.get(key)
                if e is None:
                    a, b = key.split("|", 1)
                    self.edges[key] = {"w": 0.45, "n": 1, "last": ts, "decay_at": ts,
                                       "valid_from": max(self.nodes[a]["created"], self.nodes[b]["created"]),
                                       "valid_to": None, "automatic_anchor": True,
                                       "anchor_relations": relations}
                else:
                    e["anchor_relations"] = relations

    @staticmethod
    def _number(value, name: str, low: float | None = None,
                high: float | None = None) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValidationError(f"{name} 必须是有限数值")
        if (low is not None and value < low) or (high is not None and value > high):
            raise ValidationError(f"{name} 超出有效范围")
        return float(value)

    # ────────────────────────── 内部 ──────────────────────────
    def _must(self, nid: str) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            raise NotFound(f"没有这个节点: {nid}")
        return n

    def _vec_for(self, n: dict) -> set:
        raw = f'{n["label"]} {n.get("text", "")} {" ".join(n.get("tags") or [])}'
        return set(self.encoder(raw))

    @staticmethod
    def _key(a: str, b: str) -> str:
        return "|".join(sorted((a, b)))
