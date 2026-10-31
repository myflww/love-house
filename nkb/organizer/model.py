"""Standard-library provider transport, invoked only by an enabled queued organizer job."""
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ..errors import ValidationError
from .config import endpoint
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
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise OrganizerError("整理模型返回过大，未应用", "invalid_output")
    return json.loads(raw)


def _non_thinking_json_task(url, model):
    """Use DeepSeek's documented toggle only at its supported public endpoint.

    A compatible gateway or a model name containing 'deepseek' is not proof
    that the provider accepts this extension to the chat-completions schema.
    """
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == "api.deepseek.com"
            and parsed.port in (None, 443)
            and model in {"deepseek-flash", "deepseek-v4-pro", "deepseek-chat"})


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
    if not isinstance(resolved["model"], str) or not resolved["model"].strip():
        raise OrganizerError("整理模型名称未配置", "missing_model")
    url = endpoint(resolved["base_url"])
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
        "rate_limited":"整理API遇到频率或额度限制（HTTP 429）；请检查额度，任务仍受原预算限制",
        "provider_unavailable":"整理API服务暂时不可用（HTTP 5xx）；原文保留，将按重试规则处理",
        "redirect_blocked":"整理API发生重定向，已阻止转发密钥；请填写厂商最终API地址",
        "provider_http_error":"整理API未成功响应；请检查厂商服务和模型配置，原文仍保留",
        "tls_error":"整理API证书验证失败；请检查系统时间、证书或代理设置，不要关闭证书验证",
        "timeout":"整理模型请求超时，原文仍保留，将按重试规则处理",
        "provider_error":"整理模型连接失败；请检查网络和代理，原文仍保留",
        "invalid_output":"整理模型未返回有效JSON，未应用结果；请使用支持JSON输出的兼容模型",
        "truncated_output":"整理输出达到长度上限，未应用；请减少每批条数或选择合适的整理模型",
    }.get(code, "整理未完成，原文仍保留，可查看状态或重试")


def call_model(profile, credential, payload, send=transport):
    resolved, key, url = resolve_model(profile, credential)
    policy = SYSTEM_GUIDANCE
    request_data = {"model": resolved["model"], "messages": [{"role": "system", "content": policy},
                           {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                       "stream": False, "max_tokens": 4096,
                       "response_format": {"type": "json_object"}}
    if _non_thinking_json_task(url, resolved["model"]):
        # The organizer asks for bounded JSON, so reserve its existing token
        # budget for the result instead of an optional reasoning transcript.
        request_data["thinking"] = {"type": "disabled"}
    body = json.dumps(request_data, ensure_ascii=False, allow_nan=False).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    try:
        response = send(request, timeout=45)
        try:
            choice=response["choices"][0]
            content=choice["message"]["content"]
        except (KeyError,IndexError,TypeError):
            raise OrganizerError(failure_message("invalid_output"), "invalid_output") from None
        if choice.get("finish_reason") == "length":
            raise OrganizerError("整理输出不完整，未应用", "truncated_output")
        if not isinstance(content, str) or len(content) > 100000 or key in content:
            raise OrganizerError("整理输出不合法，未应用", "invalid_output")
        try:
            return json.loads(content)
        except (ValueError, TypeError):
            raise OrganizerError(failure_message("invalid_output"), "invalid_output") from None
    except OrganizerError:
        raise
    except urllib.error.HTTPError as exc:
        code = ("redirect_blocked" if 300 <= exc.code < 400 else
                {401:"provider_authentication",402:"provider_insufficient_balance",403:"provider_access_denied",404:"provider_not_found",
                 400:"provider_request_rejected",422:"provider_request_rejected",429:"rate_limited"}.get(
                    exc.code, "provider_unavailable" if 500 <= exc.code < 600 else "provider_http_error"))
        raise OrganizerError(failure_message(code), code) from None
    except (TimeoutError, socket.timeout):
        raise OrganizerError("整理模型超时，任务将重试，原文仍保留", "timeout") from None
    except urllib.error.URLError as exc:
        code = "tls_error" if isinstance(exc.reason, ssl.SSLCertVerificationError) else "provider_error"
        raise OrganizerError(failure_message(code), code) from None
    except Exception:
        raise OrganizerError("整理模型连接或输出格式失败，原文仍保留", "provider_error") from None
