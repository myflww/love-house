"""只在显式 reply 调用中使用官方 HTTPS 接口，不保存密钥或伪造成功。"""
from __future__ import annotations

import json
import math
import os
import socket
import urllib.error
import urllib.request

from ..errors import NKBError, ValidationError

ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-flash"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class CompanionError(NKBError, RuntimeError):
    """可以安全给界面显示的错误；不包含服务端响应、请求内容或密钥。"""

    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post_json(request: urllib.request.Request, *, timeout: float) -> dict:
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise CompanionError("服务返回内容过大，本轮未生成可保存的回复", "invalid_response")
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise CompanionError("服务返回了无法解析的内容，本轮未成功", "invalid_response") from None


class DeepSeekClient:
    """transport(request, *, timeout)->dict 可注入离线测试；构造时不取 key、不联网。"""

    def __init__(self, transport=None, *, timeout: float = 45.0):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValidationError("timeout 必须是 0~60 秒内的有限正数")
        self._transport = transport or _post_json
        self.timeout = float(timeout)

    def reply(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
              messages: list[dict] | None = None) -> str:
        if api_key is not None and not isinstance(api_key, str):
            raise ValidationError("API Key 必须是字符串")
        key = (api_key or "").strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise CompanionError("尚未提供 DeepSeek API Key，请填写密钥或设置 DEEPSEEK_API_KEY", "missing_key")
        if len(key) > 4096 or any(c.isspace() or ord(c) < 32 for c in key):
            raise CompanionError("API Key 格式不正确，请重新填写", "invalid_key")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValidationError("model 必须是最多 200 字的非空字符串")
        if not isinstance(messages, list) or not messages or len(messages) > 100:
            raise ValidationError("messages 必须是 1~100 条角色消息")
        normalized = []
        for message in messages:
            if (not isinstance(message, dict) or message.get("role") not in ("system", "user", "assistant")
                    or not isinstance(message.get("content"), str) or len(message["content"]) > 100000):
                raise ValidationError("每条消息必须包含明确的 role 和字符串 content")
            normalized.append({"role": message["role"], "content": message["content"]})
        try:
            body = json.dumps({"model": model.strip(), "messages": normalized, "stream": False,
                               "max_tokens": 2048, "thinking": {"type": "disabled"}},
                              ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, UnicodeError):
            raise ValidationError("消息包含无法发送的字符") from None
        request = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json"})
        try:
            response = self._transport(request, timeout=self.timeout)
            choice = response["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip() or len(content) > 100000:
                raise CompanionError("服务没有返回有效的文本回复，本轮未成功", "invalid_response")
            if choice.get("finish_reason") == "length":
                raise CompanionError("回复达到长度上限且不完整，本轮未保存，请缩短问题后重试", "truncated_response")
            # 极端情况下服务回显凭证，也不能把凭证交给UI、聊天记录或日志。
            if key in content:
                raise CompanionError("服务回复包含敏感凭证，本轮已丢弃且未保存", "unsafe_response")
            return content
        except CompanionError:
            raise
        except urllib.error.HTTPError as exc:
            code = exc.code
            if 300 <= code < 400:
                message, error = "服务尝试重定向，已阻止转发 API Key", "redirect_blocked"
            elif code in (401, 403):
                message, error = "DeepSeek 密钥或权限校验未通过", "authentication_failed"
            elif code == 429:
                message, error = "DeepSeek 请求受限，请稍后重试", "rate_limited"
            elif code >= 500:
                message, error = "DeepSeek 服务暂时不可用，请稍后重试", "service_unavailable"
            else:
                message, error = f"DeepSeek 未接受请求（HTTP {code}），请检查模型和参数", "request_rejected"
            raise CompanionError(message, error) from None
        except (TimeoutError, socket.timeout):
            raise CompanionError("DeepSeek 调用超时，本轮未成功，请稍后重试", "timeout") from None
        except urllib.error.URLError as exc:
            code = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "connection_failed"
            message = "DeepSeek 调用超时，本轮未成功" if code == "timeout" else "无法连接 DeepSeek，请检查网络后重试"
            raise CompanionError(message, code) from None
        except (KeyError, TypeError, IndexError):
            raise CompanionError("DeepSeek 返回结构不完整，本轮未成功", "invalid_response") from None
        except Exception:
            raise CompanionError("DeepSeek 调用失败，本轮未成功，请检查网络或服务设置", "transport_error") from None
