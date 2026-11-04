"""Conservative, local query cues. Dates narrow evidence; cues never create it."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import math
import re

_DATE = re.compile(r"(?<!\d)(\d{4})\s*(?:年|[-/])\s*(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})(?:日|号)?(?!\d)")
_RECENT = re.compile(r"最近|最新|刚才|刚刚|上次|上回|最后一次|\b(?:latest|recent|last time)\b", re.I)
_HISTORY = re.compile(r"以前|曾经|当时|最初|过去|历史|\b(?:previously|historical|used to)\b", re.I)
_CURRENT = re.compile(r"现在|目前|如今|当前|\b(?:currently|now)\b", re.I)
_UNFINISHED = re.compile(r"没做完|未完成|还没完成|未解决|待跟进|尚未完成|\b(?:unfinished|unresolved|pending)\b", re.I)
_FILLER = re.compile(r"还记得|记不记得|记得|请问|可以告诉我|告诉我|我们|那个|那件事|那件|这件事|这个|东西|事情|事儿|什么|怎么样|怎样|怎么|是否|是不是|我|你|她|它|的|了|吗|呢|呀|啊|[?？!！。，,\s]+")
# Small auditable equivalence groups describe query wording, not user facts.
# They only match a stored organizer alias; they cannot invent an address,
# preference, person or event that has no corresponding source record.
_TOPICS = (
    ('住址', '居住地点', '住在哪', '住哪里', '住哪儿', '住在哪里', '家在哪', '家在哪里', '安家地点', '住处'),
    ('饮食偏好', '喜欢吃', '爱吃', '喜欢的食物'),
    ('饮品偏好', '喜欢喝', '爱喝', '喜欢的饮料'),
    ('工作单位', '任职单位', '在哪上班', '在哪里上班'),
)


def topic_alias_match(query, alias):
    query, alias = query.casefold(), alias.casefold()
    return any(any(word in query for word in group) and any(word in alias for word in group)
               for group in _TOPICS)


@dataclass(frozen=True)
class QueryPlan:
    search: str
    intent: str | None = None
    start: float | None = None
    end: float | None = None
    unfinished: bool = False
    needs_clarification: bool = False
    invalid_date: bool = False

    def public(self):
        value = {"intent": self.intent or "relevance", "needs_clarification": self.needs_clarification or self.invalid_date,
                 "unfinished_only": self.unfinished, "inferred_facts": False}
        if self.start is not None:
            value["event_time_range"] = {"from": self.start, "to_exclusive": self.end, "timezone": "local"}
        if self.invalid_date:
            value["reason"] = "invalid_calendar_date"
        elif self.needs_clarification:
            value["reason"] = "missing_topic"
        return value

    def accepts(self, node):
        if self.invalid_date:
            return False
        if self.unfinished and not (node.get("kind") == "commitment" and node.get("meta", {}).get("status", "open") == "open"):
            return False
        if self.start is None:
            return True
        metadata = node.get("meta", {})
        stamp = source_event_time(node, require_explicit=True)
        # Source-time unknown imports do not acquire a date from import time.
        if metadata.get("source_time_unknown"):
            return False
        return type(stamp) in (int, float) and math.isfinite(stamp) and self.start <= stamp < self.end


def source_event_time(node, *, require_explicit=False):
    metadata = node.get('meta', {})
    if metadata.get('source_time_unknown'):
        return None
    atom = metadata.get('memory_atom')
    if metadata.get('source') in ('organizer', 'user_confirmed') and isinstance(atom, dict):
        stamp = atom.get('event_at')
        if type(stamp) in (int, float) and math.isfinite(stamp):
            return stamp
    evidence = metadata.get('evidence')
    if isinstance(evidence, dict):
        stamp = evidence.get('source_event_at')
        if type(stamp) in (int, float) and math.isfinite(stamp):
            return stamp
    return node.get('event_at') if not require_explicit or node.get('event_explicit') else None


def plan_query(query, reference):
    """Resolve explicit calendar dates and local relative days at a fixed clock.

    No language model, external service, hidden history or cross-window context.
    Unresolved pronouns are reported as ambiguous instead of guessed.
    """
    text = query.strip()
    local = datetime.fromtimestamp(reference)
    start = end = None
    invalid = False
    match = _DATE.search(text)
    if match:
        try:
            day = date(*(int(part) for part in match.groups()))
            start = datetime.combine(day, time.min).timestamp()
            end = datetime.combine(day + timedelta(days=1), time.min).timestamp()
        except (ValueError, OverflowError, OSError):
            invalid = True
        text = _DATE.sub(" ", text)
    else:
        relative = next(((cue, offset) for cue, offset in (("前天", -2), ("昨天", -1), ("今天", 0)) if cue in text), None)
        if relative:
            cue, offset = relative
            day = local.date() + timedelta(days=offset)
            start = datetime.combine(day, time.min).timestamp()
            end = datetime.combine(day + timedelta(days=1), time.min).timestamp()
            text = text.replace(cue, " ")
        elif "上周" in text or re.search(r"\blast week\b", text, re.I):
            day = local.date() - timedelta(days=local.weekday() + 7)
            start = datetime.combine(day, time.min).timestamp()
            end = datetime.combine(day + timedelta(days=7), time.min).timestamp()
            text = re.sub(r"上周|\blast week\b", " ", text, flags=re.I)
    intent = ("comparison" if _HISTORY.search(text) and _CURRENT.search(text) else
              "historical" if _HISTORY.search(text) else "recent" if _RECENT.search(text) else
              "current" if _CURRENT.search(text) else None)
    unfinished = bool(_UNFINISHED.search(text))
    stripped = _FILLER.sub("", _UNFINISHED.sub("", _CURRENT.sub("", _RECENT.sub("", _HISTORY.sub("", text)))))
    ambiguous = not stripped and not unfinished
    # Keep meaningful wording for matching. Time words themselves are not a
    # substitute for an actual topic or for source event timestamps.
    search = _CURRENT.sub(" ", _RECENT.sub(" ", _HISTORY.sub(" ", text))).strip()
    if unfinished:
        search = _UNFINISHED.sub(" ", search).strip() or "承诺 约定 待办"
        generic = _FILLER.sub('', search)
        if re.fullmatch(r'(?:承诺|约定|待办|任务|项目|还|我|这|那|个|件)*', generic):
            search = "承诺 约定 待办"
    return QueryPlan(search or text, intent, start, end, unfinished, ambiguous, invalid)
