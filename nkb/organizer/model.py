"""Standard-library provider transport, invoked only by an enabled queued organizer job."""
import json
import socket
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


def call_model(profile, credential, payload, send=transport):
    # A runtime dict allows the root KeyStore to resolve a reused provider; none is persisted.
    resolved = {**profile, **({k: credential[k] for k in ("base_url", "model") if k in credential}
                              if isinstance(credential, dict) else {})}
    key = credential.get("api_key") if isinstance(credential, dict) else credential
    if not isinstance(key, str) or not key.strip():
        raise OrganizerError("整理模型尚未配置可用凭证", "missing_credential")
    key = key.strip()
    if len(key) > 4096 or any(c.isspace() or ord(c) < 32 for c in key):
        raise OrganizerError("整理模型凭证格式不正确", "invalid_credential")
    if not isinstance(resolved["model"], str) or not resolved["model"].strip():
        raise OrganizerError("整理模型名称未配置", "missing_model")
    url = endpoint(resolved["base_url"])
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
        content = response["choices"][0]["message"]["content"]
        if response["choices"][0].get("finish_reason") == "length":
            raise OrganizerError("整理输出不完整，未应用", "truncated_output")
        if not isinstance(content, str) or len(content) > 100000 or key in content:
            raise OrganizerError("整理输出不合法，未应用", "invalid_output")
        return json.loads(content)
    except OrganizerError:
        raise
    except urllib.error.HTTPError as exc:
        code = "redirect_blocked" if 300 <= exc.code < 400 else "provider_http_error"
        raise OrganizerError("整理API未成功响应，原文仍保留", code) from None
    except (TimeoutError, socket.timeout):
        raise OrganizerError("整理模型超时，任务将重试，原文仍保留", "timeout") from None
    except Exception:
        raise OrganizerError("整理模型连接或输出格式失败，原文仍保留", "provider_error") from None
