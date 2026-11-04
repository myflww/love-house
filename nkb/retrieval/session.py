"""Request-local recall views with incrementally validated, non-persistent vectors.

No result, lifecycle decision, source permission or memory body is cached across
requests. Only encodings are reused after checking their exact input fields.
"""
from __future__ import annotations

from copy import copy
from hashlib import sha256

from ..errors import ValidationError
from .scoring import OverlapScorer


class PreparedRecall:
    def __init__(self, brain, *, view=None):
        self.brain = brain
        self.view_mode=view
        encoder = brain.encoder
        self.encoder = encoder
        cache = getattr(brain, "_semantic_vectors", None)
        if not isinstance(cache, dict) or cache.get("encoder") is not encoder:
            cache = {"encoder": encoder, "entries": {}}
            brain._semantic_vectors = cache
        self.cache = cache["entries"]
        # A removed node must not leave even an encoding input in this cache.
        for nid in self.cache.keys() - brain.nodes.keys():
            self.cache.pop(nid, None)

    def view(self, candidate_ids=None, *, plan=None):
        from ..companion.dedup import is_duplicate
        if self.brain.encoder is not self.encoder:
            self.__init__(self.brain,view=self.view_mode)
        if candidate_ids is not None:
            if not isinstance(candidate_ids, (set, frozenset, list, tuple)) or any(not isinstance(i, str) for i in candidate_ids):
                raise ValidationError("candidate_ids必须是本图节点ID集合")
            candidate_ids = set(candidate_ids)
        brain = self.brain
        from ..companion.versions import resolve_view,historical_projection,is_historical
        mode=resolve_view(self.view_mode) if self.view_mode is not None else ('history' if plan and plan.intent=='historical' else 'comparison' if plan and plan.intent=='comparison' else 'current')
        tombstones = set(brain.meta.get("memory_tombstones", {}).get("node_ids", []))
        library = brain.meta.get("library_id")
        selected = set()
        vectors = {} if type(brain.scorer) is OverlapScorer else dict(brain._vec)
        projected_nodes=None
        # This pass is deliberately linear and live: arbitrary metadata edits,
        # removals and revoked evidence cannot be hidden by a stale result cache.
        for nid, node in brain.nodes.items():
            if candidate_ids is not None and nid not in candidate_ids:
                continue
            meta = node.get("meta", {})
            if (nid in tombstones or meta.get("memory_disabled") or meta.get("forgotten")
                    or library and meta.get("library_id") not in (None, library)
                    or is_duplicate(node, brain) or plan is not None and not plan.accepts(node)):
                continue
            if mode=='current' and is_historical(node):continue
            if mode!='current' and is_historical(node):
                if projected_nodes is None:projected_nodes=dict(brain.nodes)
                projected_nodes[nid]=historical_projection(node)
            material = f'{node.get("label", "")} {node.get("text", "")} {" ".join(node.get("tags") or [])}'
            anchor = self.correction_anchor(node, tombstones, library)
            if anchor:
                material += ' ' + anchor
            signature = sha256(material.encode("utf-8")).digest()
            entry = self.cache.get(nid)
            if entry is None or entry[0] != signature:
                vector = brain._vec_for(node)
                if anchor:
                    vector = vector | set(brain.encoder(anchor))
                entry = (signature, vector)
                self.cache[nid] = entry
            selected.add(nid)
            vectors[nid] = entry[1]
        view = copy(brain)
        # Full live nodes remain available to lifecycle/anchor evidence checks.
        # candidate_ids restricts both seed and result lanes in Brain.recall.
        view._vec = vectors
        if projected_nodes is not None:view.nodes=projected_nodes
        return view, selected

    def correction_anchor(self, node, tombstones, library):
        """An old topic can locate its explicit correction, never become its value.

        This material is encoded only; it is not put in the result node, hit
        text or evidence packet. Removing either side invalidates reuse on the
        next call, including when a request-local preparation is reused.
        """
        meta = node.get('meta', {})
        previous = meta.get('corrects')
        if (meta.get('source') != 'user_confirmed' or meta.get('confirmed') is not True
                or meta.get('speaker') != 'user' or not isinstance(previous, str)):
            return ''
        old = self.brain.get(previous)
        if (old is None or previous in tombstones or old.get('superseded_by') != node['id']
                or old.get('meta', {}).get('forgotten')
                or old.get('meta', {}).get('library_id') not in (None, library)
                or meta.get('library_id') not in (None, library)):
            return ''
        from ..companion.lifecycle import safe_topic_tags
        return ' '.join([str(old.get('label', ''))[:200], *safe_topic_tags(old)])


def prepare_recall(brain, *, view=None):
    return PreparedRecall(brain,view=view)
