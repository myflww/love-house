"""Standard-library provider transport, invoked only by an enabled queued organizer job."""
import json
import socket
import ssl
import urllib.error
import urllib.request

from ..errors import ValidationError
from .config import endpoint
from .capabilities import capabilities_for, effective_limits, official_deepseek
from .rules import SYSTEM_GUIDANCE


class OrganizerError(ValidationError):
    def __init__(self, message, code="organizer_error"):
        super().__init__(message)
        self.code = code


class OrganizerConflict(OrganizerError):
    def __init__(self, message="原文或旧记忆已变化，未应用过时整理结果"):
        super().__init__(message, "stale_input")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(request, *, timeout):
    limit = getattr(request, '_organizer_response_limit', 128 * 1024 * 1024)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise OrganizerError("整理模型返回过大，未应用", "invalid_output")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, TypeError):
        raise OrganizerError(failure_message("invalid_output"), "invalid_output") from None


def _supports_deepseek_thinking(url, model, metadata):
    """Use DeepSeek's documented toggle only at its supported public endpoint.

    A compatible gateway or a model name containing 'deepseek' is not proof
    that the provider accepts this extension to the chat-completions schema.
    """
    return (official_deepseek(url) and (model in {"deepseek-flash", "deepseek-v4-pro"}
            or bool(metadata.get('effort', {}).get('supported_levels'))))


def validate_key(key):
    if not isinstance(key, str) or not key.strip():
        raise OrganizerError("整理模型尚未配置可用凭证", "missing_credential")
    key = key.strip()
    if len(key) > 4096 or any(not 33 <= ord(c) <= 126 for c in key):
        raise OrganizerError("整理模型密钥须为最多4096个可见ASCII字符，不能包含空白", "invalid_credential")
    return key


def resolve_model(profile, credential):
    """Validate the effective provider before reserving a paid-call budget."""
    # A runtime dict allows the root KeyStore to resolve a reused provider; none is persisted.
    resolved = {**profile, **({k: credential[k] for k in ("base_url", "model") if k in credential}
                              if isinstance(credential, dict) else {})}
    key = validate_key(credential.get("api_key") if isinstance(credential, dict) else credential)
    if not isinstance(resolved.get("model"), str) or not resolved["model"].strip():
        raise OrganizerError("整理模型名称未配置", "missing_model")
    url = endpoint(resolved.get("base_url"))
    metadata = capabilities_for(resolved)
    limits = effective_limits(resolved)
    context = resolved.get('context_window', 0)
    if (metadata.get('max_output_tokens') and limits['max_output_tokens'] > metadata['max_output_tokens']
            or context and resolved.get('max_output_tokens', 0) >= context):
        raise OrganizerError(failure_message('invalid_output_limit'), 'invalid_output_limit')
    if context and metadata.get('context_window') and context > metadata['context_window']:
        raise OrganizerError(failure_message('invalid_context_limit'), 'invalid_context_limit')
    effort = resolved.get('reasoning_effort', 'auto')
    supported = metadata.get('effort', {}).get('supported_levels', [])
    if effort not in ('auto', 'none') and supported and effort not in supported:
        raise OrganizerError(failure_message('unsupported_effort'), 'unsupported_effort')
    return resolved, key, url


def failure_message(code):
    # Only fixed local messages may reach the UI or durable task journal. Never
    # copy a provider's error body, reason, request URL or exception text.
    return {
        "missing_credential":"整理模型尚未配置凭证，原文仍保留",
        "invalid_credential":"整理密钥格式不正确，请重新粘贴不含空白的厂商API密钥；原文仍保留",
        "missing_model":"整理模型名称尚未配置，原文仍保留",
        "provider_authentication":"整理API拒绝了密钥（HTTP 401）；请检查密钥与厂商地址是否匹配",
        "provider_insufficient_balance":"整理API余额不足（HTTP 402）；请检查厂商账户余额，原文仍保留",
        "provider_access_denied":"整理API拒绝访问（HTTP 403）；请检查账户、模型权限和服务限制",
        "provider_not_found":"整理API地址或模型不存在（HTTP 404）；请检查完整基础地址和模型名称",
        "provider_request_rejected":"整理API不接受请求（HTTP 400/422）；请确认该服务支持OpenAI兼容聊天及JSON输出",
        "rate_limited":"整理API遇到频率或额度限制（HTTP 429）；请检查额度，任务保留并自动等待重试",
        "provider_unavailable":"整理API服务暂时不可用（HTTP 5xx）；原文保留，将按重试规则处理",
        "redirect_blocked":"整理API发生重定向，已阻止转发密钥；请填写厂商最终API地址",
        "provider_http_error":"整理API未成功响应；请检查厂商服务和模型配置，原文仍保留",
        "tls_error":"整理API证书验证失败；请检查系统时间、证书或代理设置，不要关闭证书验证",
        "timeout":"整理模型请求超时，原文仍保留，将按重试规则处理",
        "provider_error":"整理模型连接失败；请检查网络和代理，原文仍保留",
        "invalid_output":"整理模型未返回有效JSON，未应用结果；请使用支持JSON输出的兼容模型",
        "truncated_output":"整理输出被截断，未应用；普通记忆将缩小分片自动重试",
        "context_length_exceeded":"整理输入超过服务上下文容量，未应用；将缩小分片自动重试，原文仍保留",
        "unsupported_effort":"所选推理强度不受当前模型支持，请重新选择服务提供的强度",
        "invalid_output_limit":"输出长度超过当前模型的服务上限，请重新选择",
        "invalid_context_limit":"自定上下文超过当前模型的服务上限，请重新选择",
        "invalid_persona_trait":"人格资料未通过角色、依据或指令边界检查，原文仍保留；可检查资料后明确重试",
        "invalid_persona_traits":"本次人格资料均未通过校验，未形成人格；原文仍保留，请检查资料后明确重试",
        "persona_learning_disabled":"人格或随对话学习已关闭，未发送快速整理资料；需要时由你重新开启",
        "invalid_persona_plan":"人格缓存的任务用途不一致，未应用；请重新预览后明确开始",
    }.get(code, "整理未完成，原文仍保留，可查看状态或重试")


def model_options(profile):
    """Shared output/reasoning choices for organizer and explicit reading indexes."""
    request_data = {}
    metadata = capabilities_for(profile)
    output_tokens = effective_limits(profile)['max_output_tokens']
    if output_tokens:
        if metadata.get('max_output_tokens') and output_tokens > metadata['max_output_tokens']:
            raise OrganizerError(failure_message('invalid_output_limit'), 'invalid_output_limit')
        request_data['max_tokens'] = output_tokens
    effort = profile.get('reasoning_effort', 'auto')
    supported = metadata.get('effort', {}).get('supported_levels', [])
    if effort != 'auto':
        if effort != 'none' and supported and effort not in supported:
            raise OrganizerError(failure_message('unsupported_effort'), 'unsupported_effort')
        if _supports_deepseek_thinking(endpoint(profile['base_url']), profile['model'], metadata):
            request_data['thinking'] = {'type': 'disabled' if effort == 'none' else 'enabled'}
            if effort != 'none':request_data['reasoning_effort'] = effort
        else:
            request_data['reasoning_effort'] = effort
    return request_data


def call_model(profile, credential, payload, send=transport):
    resolved, key, url = resolve_model(profile, credential)
    policy = SYSTEM_GUIDANCE
    if profile.get('max_ops') == 1 and payload.get('purpose') != 'persona':
        policy += '\n本次是输出截断后的缩小分片重试，operations最多1项，使用简短JSON；逐字证据与其他规则仍须完整遵守。'
    request_data = {"model": resolved["model"], "messages": [{"role": "system", "content": policy},
                           {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                       "stream": False,
                       "response_format": {"type": "json_object"}, **model_options(resolved)}
    output_tokens = request_data.get('max_tokens', 0)
    body = json.dumps(request_data, ensure_ascii=False, allow_nan=False).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    # Covers large final JSON plus the provider's reasoning envelope. This is a
    # wire safety guard, unrelated to memory retention or model token settings.
    response_limit = max(16 * 1024 * 1024, min(128 * 1024 * 1024,
        output_tokens * 64 + 1024 * 1024)) if output_tokens else 128 * 1024 * 1024
    request._organizer_response_limit = response_limit
    try:
        response = send(request, timeout=300)
        try:
            choice=response["choices"][0]
            content=choice["message"]["content"]
        except (KeyError,IndexError,TypeError):
            raise OrganizerError(failure_message("invalid_output"), "invalid_output") from None
        if choice.get("finish_reason") == "length":
            raise OrganizerError(failure_message("truncated_output"), "truncated_output")
        if not isinstance(content, str) or len(content.encode('utf-8')) > response_limit or key in content:
            raise OrganizerError(failure_message("invalid_output"), "invalid_output")
        try:
            return json.loads(content)
        except (ValueError, TypeError):
            raise OrganizerError(failure_message("invalid_output"), "invalid_output") from None
    except OrganizerError:
        raise
    except urllib.error.HTTPError as exc:
        context_error = False
        if exc.code in (400, 422):
            try:
                raw = exc.read(65537)
                error = json.loads(raw).get('error', {}) if len(raw) <= 65536 else {}
                context_error = (isinstance(error, dict) and error.get('code') in (
                    'context_length_exceeded', 'context_window_exceeded', 'max_context_length_exceeded'))
            except Exception:pass
        code = ("redirect_blocked" if 300 <= exc.code < 400 else
                "context_length_exceeded" if context_error else
                {401:"provider_authentication",402:"provider_insufficient_balance",403:"provider_access_denied",404:"provider_not_found",
                 400:"provider_request_rejected",422:"provider_request_rejected",429:"rate_limited"}.get(
                    exc.code, "provider_unavailable" if 500 <= exc.code < 600 else "provider_http_error"))
        raise OrganizerError(failure_message(code), code) from None
    except ssl.SSLCertVerificationError:
        raise OrganizerError(failure_message("tls_error"), "tls_error") from None
    except (TimeoutError, socket.timeout):
        raise OrganizerError(failure_message("timeout"), "timeout") from None
    except urllib.error.URLError as exc:
        code = ("tls_error" if isinstance(exc.reason, ssl.SSLCertVerificationError) else
                "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "provider_error")
        raise OrganizerError(failure_message(code), code) from None
    except (json.JSONDecodeError, UnicodeError):
        raise OrganizerError(failure_message("invalid_output"), "invalid_output") from None
    except Exception:
        raise OrganizerError(failure_message("provider_error"), "provider_error") from None
