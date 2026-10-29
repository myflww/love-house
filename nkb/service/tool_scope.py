"""Server-side argument allowlist for the connection-bound Agent tool surface."""
from ..errors import ValidationError

# The stdio schema is a usability aid; this separate root-side validation is the
# actual boundary. Clients cannot add confirmation, library or source IDs that
# a given tool did not declare.
FIELDS = {
    "memory_status": ({}, ()), "memory_persona": ({}, ()),
    "memory_bootstrap": ({"max_chars": ("int", 2000, 32000)}, ()),
    "memory_list": ({"cursor": ("str", 1024), "limit": ("int", 1, 100)}, ()),
    "memory_read": ({"memory_id": ("str", 200), "field": ("enum", ("value", "assistant", "display")),
                     "offset": ("int", 0, 100000000), "max_chars": ("int", 1, 32000), "revision": ("str", 64)}, ("memory_id",)),
    "memory_context": ({"query": ("str", 10000), "session_id": ("str", 200), "max_chars": ("int", 512, 32000)}, ("query",)),
    "memory_remember": ({"text": ("str", 40000), "kind": ("str", 64), "important": ("bool",), "session_id": ("str", 200)}, ("text", "session_id")),
    "memory_record_turn": ({"user": ("str", 40000), "assistant": ("str", 40000), "session_id": ("str", 200),
                            "request_id": ("str", 200), "source_session_id": ("str", 200), "source_event_id": ("str", 200)},
                           ("user", "assistant", "session_id", "request_id")),
    "memory_event": ({"text": ("str", 40000), "source_url": ("str", 4000), "session_id": ("str", 200),
                      "request_id": ("str", 200), "outcome": ("enum", ("observed", "success", "failed"))},
                     ("text", "source_url", "session_id", "request_id", "outcome")),
    "memory_persona_import": ({"text": ("str", 4000), "user_request": ("str", 4000), "explicit": ("true",),
                               "session_id": ("str", 200), "request_id": ("str", 200)},
                              ("text", "user_request", "explicit", "session_id", "request_id")),
}


def validate_tool_arguments(name, args):
    if not isinstance(name, str) or name not in FIELDS:
        raise ValidationError("未知记忆工具；不会执行任意接口或代码")
    if not isinstance(args, dict):
        raise ValidationError("工具参数须为对象")
    fields, required = FIELDS[name]
    if set(args) - set(fields):
        raise ValidationError("工具含未声明参数；不能选择其他库或伪造确认")
    if any(k not in args for k in required):
        raise ValidationError("工具缺少必填参数")
    for key, value in args.items():
        rule = fields[key]
        valid = ((rule[0] == "str" and isinstance(value, str) and bool(value.strip()) and len(value) <= rule[1])
                 or (rule[0] == "int" and type(value) is int and rule[1] <= value <= rule[2])
                 or (rule[0] == "bool" and type(value) is bool)
                 or (rule[0] == "true" and value is True)
                 or (rule[0] == "enum" and isinstance(value, str) and value in rule[1]))
        if not valid:
            raise ValidationError("工具参数格式或范围不正确：" + key)
    return dict(args)
