"""Per-library organizer settings. Credentials are intentionally not serializable here."""
from copy import deepcopy
from urllib.parse import urlsplit
import ipaddress

from ..errors import ValidationError

DEFAULT_PROFILE = {"enabled": False, "provider_id": "", "base_url": "", "model": "", "cadence": "batch",
                   "batch_size": 6, "auto_trigger_count": 0, "max_input_chars": 18000, "max_ops": 12,
                   "daily_call_limit": 100, "daily_char_limit": 200000, "max_attempts": 3}


def validate_profile(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULT_PROFILE):
        raise ValidationError("整理设置包含未知字段；API密钥必须交给凭证存储，不得写入配置")
    result = {**DEFAULT_PROFILE, **data}
    if type(result["enabled"]) is not bool:
        raise ValidationError("enabled必须是布尔值")
    if result["cadence"] not in ("session", "batch"):
        raise ValidationError("cadence只能是session或batch")
    for key, size in (("provider_id", 200), ("base_url", 2000), ("model", 200)):
        if not isinstance(result[key], str) or len(result[key]) > size:
            raise ValidationError(f"{key}必须是有界字符串")
        if key == "base_url" and any(ord(c)<32 or ord(c)==127 for c in result[key]):
            raise ValidationError("整理API地址不能包含控制字符")
        result[key] = result[key].strip()
    for key, low, high in (("batch_size", 1, 12), ("auto_trigger_count", 0, 500), ("max_input_chars", 3000, 48000),
                           ("max_ops", 1, 24), ("daily_call_limit", 1, 1000),
                           ("daily_char_limit", 3000, 2000000), ("max_attempts", 1, 8)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValidationError(f"{key}必须是{low}~{high}的整数")
    if result["base_url"]:
        endpoint(result["base_url"])
    return result


def get_profile(brain):
    return validate_profile(brain.meta.get("organizer_profile", {}))


def save_profile(brain, **settings):
    profile = validate_profile({**get_profile(brain), **settings})
    brain.meta["organizer_profile"] = deepcopy(profile)
    return deepcopy(profile)


def endpoint(base_url):
    if (not isinstance(base_url,str) or not base_url or len(base_url)>2000 or "\\" in base_url
            or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in base_url)):
        raise ValidationError("整理API地址不能包含空白、控制字符或反斜杠")
    try:
        p = urlsplit(base_url)
        port = p.port
        hostname = p.hostname
    except (ValueError,TypeError):
        raise ValidationError("整理API地址或端口格式不合法") from None
    if not hostname or p.username is not None or p.password is not None or p.query or p.fragment:
        raise ValidationError("整理API地址不合法，不能包含认证信息、查询或片段")
    if port is not None and not 1 <= port <= 65535:
        raise ValidationError("整理API端口必须是1~65535")
    if '/connections/' in p.path:
        raise ValidationError("整理API请填写厂商地址，不能使用爱之屋自己的记忆接入地址")
    local = p.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(p.hostname).is_loopback
    except ValueError:
        pass
    if p.scheme != "https" and not (p.scheme == "http" and local):
        raise ValidationError("整理API须用HTTPS，本机loopback调试可用HTTP")
    return p.geturl().rstrip("/") + ("" if p.path.rstrip("/").endswith("/chat/completions") else "/chat/completions")
