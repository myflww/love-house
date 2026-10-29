"""Evidence-bound JSON memory atoms; data only, never code or a hidden encoding."""
from copy import deepcopy
from hashlib import sha256
import json
import math
import re
import unicodedata

from .model import OrganizerError

SCHEMA = 'love-house-memory-atom/v1'
_WORD = re.compile(r'^[\w.:-]{1,120}$', re.UNICODE)
_NEGATIVE = re.compile(r'不喜欢|不再|从不|没有|不是|不住|不在|不想|不希望|不同意|不能|不愿|\b(?:not|never|no longer|don\'t|doesn\'t|isn\'t|can\'t|won\'t)\b',re.I)
_COMPLEX = re.compile(r'但是|不过|然而|并非|不是不|\b(?:but|however|unless)\b',re.I)
_ROLE = {'user':'user','用户':'user','使用者':'user','我':'user','agent':'agent','assistant':'agent','助手':'agent','代理':'agent','tool':'tool','工具':'tool'}


def _text(value, maximum, name):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or any(ord(c)<32 for c in value):
        raise OrganizerError('模型机器记录'+name+'字段不合法','invalid_atom')
    return value.strip()


def normalize_atom(op):
    """Only model value/entity literals are copied from already validated evidence.

    Predicate semantics remain a model extraction, explicitly labelled as such;
    value verification never claims mathematical proof of a semantic relation.
    Legacy outputs remain usable as a full-verbatim text atom.
    """
    supplied=op.get('atom')
    evidence=op['evidence']
    role='user' if any(e['role']=='user' for e in evidence) else 'tool' if op.get('observation') else 'agent'
    if supplied is None:
        return {'subject':role,'predicate':op['key'],'value':op['verbatim_text'] or '\n'.join(e.get('context',e['quote']) for e in evidence)[:2000],
                'qualifiers':{'polarity':'unknown'},'relation_status':'verbatim_fallback'},False
    if not isinstance(supplied,dict) or set(supplied)-{'subject','predicate','value','qualifiers'}:
        raise OrganizerError('机器记录只允许subject/predicate/value/qualifiers','invalid_atom')
    subject=_text(supplied.get('subject'),120,'subject')
    predicate=_text(supplied.get('predicate'),120,'predicate')
    if not _WORD.fullmatch(predicate):raise OrganizerError('机器属性必须是简短稳定标识','invalid_atom')
    value=_text(supplied.get('value'),1200,'value')
    contexts=[e.get('context',e['quote']) for e in evidence if e['role']==role or role=='agent']
    contexts=[c for c in contexts if isinstance(c,str)]
    matching=[c for c in contexts if value in c]
    if not matching:raise OrganizerError('机器值不属于当前证据原文','invalid_atom')
    canonical_subject=_ROLE.get(subject.casefold(),_ROLE.get(subject))
    if canonical_subject is None and not any(subject in c for c in contexts):
        raise OrganizerError('机器主语不属于证据实体或固定角色','invalid_atom')
    subject=canonical_subject or subject
    qualifiers=supplied.get('qualifiers',{})
    if not isinstance(qualifiers,dict) or set(qualifiers)-{'polarity','scope','unit'}:
        raise OrganizerError('机器限定项只允许polarity/scope/unit；时间由程序记录','invalid_atom')
    qualifiers=deepcopy(qualifiers)
    for field,limit in (('scope',160),('unit',30)):
        if field in qualifiers:
            qualifiers[field]=_text(qualifiers[field],limit,field)
            if not any(qualifiers[field] in c for c in contexts):
                raise OrganizerError('机器限定项不属于证据原文','invalid_atom')
    negative=any(_NEGATIVE.search(c) for c in matching)
    polarity=qualifiers.get('polarity','negated' if negative else 'affirmed')
    if polarity not in ('affirmed','negated','unknown'):
        raise OrganizerError('机器polarity只能是affirmed/negated/unknown','invalid_atom')
    qualifiers['polarity']=polarity
    review=(polarity=='unknown' or (negative and polarity!='negated') or (not negative and polarity=='negated')
            or (negative and any(_COMPLEX.search(c) for c in matching)))
    return {'subject':subject,'predicate':predicate,'value':value,'qualifiers':qualifiers,
            'relation_status':'model_extracted'},review


def source_references(evidence):
    """All source IDs are retained without copying unbounded conversation bodies."""
    result=[];seen=set()
    for e in evidence:
        if not isinstance(e,dict) or not isinstance(e.get('id'),str):continue
        ref={k:deepcopy(e[k]) for k in ('id','role','receipt_id','source_event_at') if k in e}
        key=json.dumps(ref,ensure_ascii=False,sort_keys=True)
        if key not in seen:seen.add(key);result.append(ref)
    return result


def atom_signature(atom):
    if not isinstance(atom,dict):return ''
    if atom.get('relation_status')!='model_extracted':return ''
    def norm(value):
        return ' '.join(unicodedata.normalize('NFKC',value).split()) if isinstance(value,str) else value
    material={k:norm(atom.get(k)) for k in ('subject','predicate','value','layer')}
    material['qualifiers']={k:norm(v) for k,v in sorted((atom.get('qualifiers') or {}).items())}
    return sha256(json.dumps(material,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def make_atom(op,node,library_id,sources=None):
    atom=deepcopy(op.get('atom') or normalize_atom(op)[0])
    refs=source_references(sources if sources is not None else op['evidence'])
    stamps=[e.get('source_event_at') for e in refs if isinstance(e.get('source_event_at'),(int,float))
            and not isinstance(e.get('source_event_at'),bool) and math.isfinite(e['source_event_at'])]
    atom.update(schema=SCHEMA,library_id=library_id,layer=node.get('meta',{}).get('organizer_layer',op['layer']),key=op['key'],
                domain=op['domain'],certainty=op['certainty'],valid_from=node['valid_from'],valid_to=node.get('valid_to'),
                event_at=max(stamps) if stamps else node.get('event_at'),recorded_at=node['created'],evidence=refs)
    if node.get('meta',{}).get('evidence_scope')=='tool_observation':atom['outcome']=node['meta'].get('outcome','observed')
    return atom
