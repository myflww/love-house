"""Discover public model limits without retaining credentials or provider bodies."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import socket
import ssl
import threading
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ..errors import ValidationError
from .config import endpoint

_LOCK = threading.RLock()
_CATALOGS = {}
_MODELS_BYTES = 4 * 1024 * 1024
_OFFICIAL_MODELS = ('deepseek-flash', 'deepseek-v4-pro')
_CACHE_FILE = 'model-capabilities.json'
_CACHE_SCHEMA = 'love-house-model-capabilities/v1'


class CapabilityError(ValidationError):
    def __init__(self, message, code='models_unavailable'):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def models_endpoint(base_url):
    return endpoint(base_url).removesuffix('/chat/completions') + '/models'


def official_deepseek(base_url):
    parsed = urlsplit(endpoint(base_url))
    return (parsed.scheme == 'https' and parsed.hostname == 'api.deepseek.com'
            and parsed.port in (None, 443))


def _text(value, maximum=200):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _count(value):
    return type(value) is int and 0 < value <= 1000000000


def normalize_models(response, *, secret=''):
    if not isinstance(response, dict) or not isinstance(response.get('data'), list) or len(response['data']) > 1024:
        raise CapabilityError('模型列表格式不正确，未采用服务返回内容', 'invalid_models')
    models = []
    seen = set()
    for raw in response['data']:
        if not isinstance(raw, dict) or not _text(raw.get('id')):
            continue
        identifier = raw['id'].strip()
        if identifier in seen or (secret and secret in identifier):
            continue
        item = {'id': identifier}
        if _text(raw.get('name')) and not (secret and secret in raw['name']):
            item['name'] = raw['name'].strip()
        for field in ('context_window', 'max_output_tokens'):
            if _count(raw.get(field)):
                item[field] = raw[field]
        effort = raw.get('effort')
        if isinstance(effort, dict):
            levels = effort.get('supported_levels', [])
            if isinstance(levels, list):
                levels = list(dict.fromkeys(level for level in levels[:32]
                    if isinstance(level, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', level)
                    and level not in ('auto', 'none') and not (secret and secret in level)))
                if levels:
                    item['effort'] = {'supported_levels': levels}
                    if effort.get('default_level') in levels:
                        item['effort']['default_level'] = effort['default_level']
        seen.add(identifier)
        models.append(item)
    if not models:
        raise CapabilityError('服务没有返回可用的模型列表，请核对服务地址和模型权限', 'empty_models')
    return models


def models_transport(request, *, timeout):
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(_MODELS_BYTES + 1)
    if len(raw) > _MODELS_BYTES:
        raise CapabilityError('模型列表超过安全读取范围，未采用返回内容', 'invalid_models')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, TypeError):
        raise CapabilityError('模型列表不是有效JSON，未采用返回内容', 'invalid_models') from None


def discover_models(base_url, key, *, send=None):
    url = models_endpoint(base_url)
    if (not isinstance(key, str) or not key.strip() or len(key.strip()) > 4096
            or any(not 33 <= ord(c) <= 126 for c in key.strip())):
        raise CapabilityError('请先配置有效的整理API密钥，再读取模型列表', 'missing_credential')
    key = key.strip()
    if key in url:
        raise CapabilityError('模型API地址不能包含密钥，请填写不含凭据的服务基础地址', 'invalid_models')
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key,
        'Accept': 'application/json'}, method='GET')
    try:
        models = normalize_models((send or models_transport)(request, timeout=30), secret=key)
    except CapabilityError:
        raise
    except urllib.error.HTTPError as error:
        code = 'redirect_blocked' if 300 <= error.code < 400 else 'models_authentication' if error.code in (401, 403) else 'models_unavailable'
        message = ('模型列表发生重定向，已阻止转发密钥；请填写最终API地址' if code == 'redirect_blocked' else
            '模型服务拒绝访问，请核对密钥和模型权限' if code == 'models_authentication' else
            '暂时无法读取模型列表，请检查服务地址与网络；仍可手动填写模型')
        raise CapabilityError(message, code) from None
    except (TimeoutError, socket.timeout, ssl.SSLError, urllib.error.URLError):
        raise CapabilityError('暂时无法读取模型列表，请检查网络、证书与代理；仍可手动填写模型') from None
    except Exception:
        raise CapabilityError('模型列表读取失败，仍可手动填写模型') from None
    # Only normalized public capability fields survive this request.
    with _LOCK:
        if len(_CATALOGS) >= 64 and url not in _CATALOGS:
            _CATALOGS.pop(next(iter(_CATALOGS)))
        _CATALOGS[url] = deepcopy(models)
    return {'models': deepcopy(models), 'models_endpoint': url, 'source': 'api'}


def cached_models(base_url):
    with _LOCK:
        return deepcopy(_CATALOGS.get(models_endpoint(base_url), []))


def _read_cache(root):
    try:
        with (Path(root) / _CACHE_FILE).open('rb') as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:return {}
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('schema') != _CACHE_SCHEMA:return {}
        rows = value.get('catalogs')
        if not isinstance(rows, list) or len(rows) > 64:return {}
        result = {}
        for row in rows:
            if not isinstance(row, dict):continue
            try:
                base = endpoint(row.get('base_url'))
                result[base] = normalize_models({'data':row.get('models')})
            except ValidationError:continue
        return result
    except (OSError, ValueError, UnicodeError):return {}


def load_cache(root):
    """Restore public metadata only; a damaged optional cache cannot block boot."""
    catalogs = _read_cache(root)
    with _LOCK:
        for base, models in catalogs.items():
            _CATALOGS[models_endpoint(base)] = models
        while len(_CATALOGS) > 64:_CATALOGS.pop(next(iter(_CATALOGS)))
    return len(catalogs)


def save_cache(root, base_url, models):
    """Persist only the normalized catalog returned by authenticated discovery."""
    temporary = None
    try:
        base = endpoint(base_url)
        clean = normalize_models({'data':models})
        with _LOCK:
            catalogs = _read_cache(root)
            catalogs[base] = clean
            while len(catalogs) > 64:catalogs.pop(next(iter(catalogs)))
            value = {'schema':_CACHE_SCHEMA, 'catalogs':[
                {'base_url':url, 'models':items} for url, items in catalogs.items()]}
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=Path(root),
                    prefix='.model-capabilities-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, Path(root) / _CACHE_FILE)
        return True
    except (OSError, ValidationError, ValueError):return False
    finally:
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass


def capabilities_for(profile):
    base = profile.get('base_url', '')
    if not base:
        return {}
    model = profile.get('model', '')
    for item in cached_models(base):
        if item['id'] == model:
            return item
    # Official API documentation verified 2026-11-03. Provider discovery wins;
    # gateways and names alone never inherit these vendor-specific capabilities.
    if official_deepseek(base) and model in _OFFICIAL_MODELS:
        return {'id': model, 'context_window': 1048576, 'max_output_tokens': 393216,
            'effort': {'supported_levels': ['low', 'high', 'max'], 'default_level': 'high'}}
    return {}


def effective_limits(profile):
    metadata = capabilities_for(profile)
    limits = {field: profile.get(field, 0) or metadata.get(field, 0)
        for field in ('context_window', 'max_output_tokens')}
    if profile.get('context_window', 0) and not profile.get('max_output_tokens', 0):
        reserve = max(1, profile['context_window'] // 2)
        limits['max_output_tokens'] = min(limits['max_output_tokens'], reserve) if limits['max_output_tokens'] else reserve
    return {**limits, 'max_input_chars': profile.get('max_input_chars', 0)}
