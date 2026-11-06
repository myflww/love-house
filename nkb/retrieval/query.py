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
_COMPARISON = re.compile(r'前后|对比|变化|变了|改口|后来|为什么改|\b(?:comparison|compare|changed|change over time)\b',re.I)
_UNFINISHED = re.compile(r"没做完|未完成|还没完成|未解决|待跟进|尚未完成|\b(?:unfinished|unresolved|pending)\b", re.I)
_FILLER = re.compile(r"还记得|记不记得|记得|请问|可以告诉我|告诉我|我们|那个|那件事|那件|这件事|这个|东西|事情|事儿|什么|怎么样|怎样|怎么|是否|是不是|我|你|她|它|的|了|吗|呢|呀|啊|[?？!！。，,\s]+")
# Anchored conversational frames are not topics. Keep the remaining object
# verbatim, including negation and short names; do not remove words globally.
_FOCUS_PREFIX = re.compile(
    r"^\s*(?:(?:我|你|您)\s*(?:真正|具体|实际|刚才|刚刚|之前|上次|上回|现在|目前|当前)?\s*(?:所指的(?:是)?|指的是|说的是|问的是|(?:指的|说的|问的)(?=不是)|提到的是|说过的|提到的)|"
    r"(?:我|你|您)(?:的意思是|的问题是)|我(?:想|要)(?:说的是|问的是|问一下|问问)|我是说|"
    r"准确地说|具体来说|换句话说|也就是说|就是说|"
    r"(?:请|麻烦)(?:你|您)?(?:告诉我|帮我回忆|回忆一下|说一下|说说|问一下)|"
    r"(?:能不能|能否|可以)(?:请)?(?:你|您)?(?:告诉我|说一下|说说|回忆一下)|"
    r"(?:你|您)?(?:还记得|记不记得)|请问(?:一下)?|告诉我|说一下|说说)\s*[：:,，]?\s*",re.I)
_FOLLOW_UP_ONLY = re.compile(r"^(?:然后|之后|接着|后来|还有|再然后|再后来|接下来|继续)(?:呢|吗|呀|啊|吧|[？?！!。，,\s])*$")
_POINTER_ONLY = re.compile(r"^(?:这|那|哪)(?:一个|一件|一些|一位|一段|一条|一项|个人|件事|句话|个|件|些|位|段|条|项|人|事|话)?(?:呢|吗|呀|啊|[？?！!。，,\s])*$")
_QUESTION_PREFIX = re.compile(r'^\s*(?:究竟为什么|到底为什么|为什么|为何|怎么会|怎么|如何)\s*[：:,，]?\s*')
_QUESTION_SUFFIX = re.compile(r'(?<!不)(?:是什么|是怎么样|是怎么回事|怎么样|怎么回事)[？?。！!\s]*$')
_QUOTED = re.compile(r'“([^”\r\n]+)”|"([^"\r\n]+)"|「([^」\r\n]+)」|『([^』\r\n]+)』|《([^》\r\n]+)》|(?<![A-Za-z0-9])\'([^\'\r\n]+)\'(?![A-Za-z0-9])')
_LOOKUP_REQUEST = re.compile(
    r'^(?:(?:请问|请|麻烦|帮我|替我|能否|能不能|可以)(?:你|您)?\s*)*'
    r'(?:搜索|检索|查找|寻找|搜一下|搜一搜|搜搜|搜|找出|找一下|找找|找|精确匹配|字面匹配)')
_LITERAL_NOUN_REQUEST = re.compile(
    r'^(?:在)?(?:(?:所有|全部|历史)?(?:原话|原文|原句|记忆|记录)(?:里面|中|里))?'
    r'(?:包含|含有).+的(?:原话|原文|原句|记忆|记录)[？?。！!\s]*$')
_LITERAL_PREFIX = re.compile(
    r'^(?:(?:请问|请|麻烦|帮我|替我|能否|能不能|可以)(?:你|您)?\s*)*'
    r'(?:(?:搜索|检索|查找|寻找|搜一下|搜一搜|搜搜|搜|找出|找一下|找找|找|精确匹配|字面匹配)\s*(?:一下)?\s*[：:]?\s*)?'
    r'(?:(?:在)?(?:所有|全部|历史)?(?:原话|原文|原句|记忆|记录)(?:里面|中|里)?\s*)?'
    r'(?:(?:包含|含有|提到|出现过)\s*[：:]?\s*)?')


def _topic_focus(text):
    # Each successful match consumes a complete leading frame. A space avoids
    # creating a new bigram where a frame was removed.
    for _ in range(8):
        changed=_FOCUS_PREFIX.sub(' ',text,count=1)
        changed=_QUESTION_PREFIX.sub(' ',changed,count=1)
        if changed==text:break
        text=changed
    return _QUESTION_SUFFIX.sub(' ',text,count=1).strip()


def _literal_focus(text):
    """Only an actual lookup object is literal; mention/quotation alone is not.

    Multiple quoted alternatives and extra commentary stay ordinary topic
    queries, rather than masquerading as one exact substring request.
    """
    matches=list(_QUOTED.finditer(text))
    if len(matches)>1:return None
    if matches:
        match=matches[0];needle=next(v for v in match.groups() if v is not None).strip()
        framed=text[:match.start()]+' __QUOTED_OBJECT__ '+text[match.end():]
        payload=_LITERAL_PREFIX.sub(' ',framed,count=1).strip()
        payload=re.sub(r'的(?:原话|原文|原句|记忆|记录)[？?。！!\s]*$','',payload).strip(' ？?。！!')
        if payload=='__QUOTED_OBJECT__':return needle
        if (not text[:match.start()].strip() and re.fullmatch(
                r'(?:这[一二三四五六七八九十几\d]*个字)?在(?:哪些|哪段|哪句)?(?:原话|原文|原句|记忆|记录)(?:里|中)?(?:出现|提到)(?:过)?[？?。！!\s]*',text[match.end():])):
            return needle
        return None
    if not (_LOOKUP_REQUEST.match(text) or _LITERAL_NOUN_REQUEST.fullmatch(text)):return None
    payload=_LITERAL_PREFIX.sub(' ',text,count=1).strip()
    return re.sub(r'的(?:原话|原文|原句|记忆|记录)[？?。！!\s]*$','',payload).strip()


def _quoted_words(text):
    # Quote punctuation is a boundary, never a license to concatenate the
    # surrounding object/negation into a new token or discard commentary.
    return _QUOTED.sub(lambda m:' '+next(v for v in m.groups() if v is not None)+' ',text).strip()
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
    literal: bool = False
    contextual: bool = False

    def public(self):
        value = {"intent": self.intent or "relevance", "needs_clarification": self.needs_clarification or self.invalid_date,
                 "unfinished_only": self.unfinished, "inferred_facts": False}
        if self.start is not None:
            value["event_time_range"] = {"from": self.start, "to_exclusive": self.end, "timezone": "local"}
        if self.literal:
            value['literal_query']=True
        if self.contextual:
            value['contextual_query']=True
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
    original = query.strip()
    quoted=bool(_QUOTED.search(original))
    literal_search=_literal_focus(original)
    literal=literal_search is not None
    quoted_parts={}
    def mask_quote(match):
        key='__QUERY_QUOTE_'+str(len(quoted_parts))+'__'
        quoted_parts[key]=match.group(0)
        return key
    def restore_quotes(value):
        for key,part in quoted_parts.items():value=value.replace(key,part)
        return value
    # Quoted wording is the lookup object, not a calendar/current/unfinished
    # instruction. Date cues outside a quoted phrase still narrow its sources.
    text=(_QUOTED.sub(' ',original) if quoted else
          original.replace(literal_search,' ',1) if literal_search else original)
    if not literal:text=_QUOTED.sub(mask_quote,original)
    frame=_FOCUS_PREFIX.match(original)
    contextual=bool(frame and re.search(r'指的|意思|说的|问的|说过|提到|我是说',frame[0]))
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
    intent = ("comparison" if _COMPARISON.search(text) or _HISTORY.search(text) and _CURRENT.search(text) else
              "historical" if _HISTORY.search(text) else "recent" if _RECENT.search(text) else
              "current" if _CURRENT.search(text) else None)
    unfinished = bool(_UNFINISHED.search(text))
    if not literal:
        # A date may precede an explicit lookup frame. Recheck only after that
        # known date has been removed, keeping quote contents protected.
        literal_search=_literal_focus(restore_quotes(text).strip())
        literal=literal_search is not None
    # Keep meaningful wording for matching. Time words themselves are not a
    # substitute for an actual topic or for source event timestamps.
    search = _topic_focus(_CURRENT.sub(" ", _RECENT.sub(" ", _HISTORY.sub(" ", _topic_focus(text)))))
    if literal:
        search=literal_search
        return QueryPlan(search,intent,start,end,unfinished,not bool(search),invalid,True,False)
    search=_quoted_words(restore_quotes(search))
    stripped = _FILLER.sub("", _UNFINISHED.sub("", search))
    ambiguous = (not stripped or bool(_FOLLOW_UP_ONLY.fullmatch(search))
                 or bool(_POINTER_ONLY.fullmatch(search))) and not unfinished
    if unfinished:
        search = _UNFINISHED.sub(" ", search).strip() or "承诺 约定 待办"
        generic = _FILLER.sub('', search)
        if re.fullmatch(r'(?:承诺|约定|待办|任务|项目|还|我|这|那|个|件)*', generic):
            search = "承诺 约定 待办"
    contextual=contextual or ambiguous
    return QueryPlan(search,intent,start,end,unfinished,ambiguous,invalid,False,contextual)
