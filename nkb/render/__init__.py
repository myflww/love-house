"""渲染层：召回结果 -> 能塞进上下文的文本。

两种内置格式，也可以自己注册：

    from nkb.render import register_renderer

    @register_renderer("slack")
    def render_slack(result, max_chars=1800):
        return "\\n".join(f'• {h["label"]}（{h["score"]:.2f}）' for h in result["hits"])

    nkb render --format slack
"""
from __future__ import annotations

from .markdown import MAX_CHARS, SYSTEM_HINT, to_markdown, to_plain

RENDERERS = {
    "markdown": to_markdown,
    "plain": to_plain,
}


def register_renderer(name: str, fn=None, *, overwrite: bool = False):
    """两种用法都支持：

        register_renderer("slack", my_fn)
        @register_renderer("slack")
        def my_fn(result, max_chars=1800): ...
    """
    def install(f):
        if name in RENDERERS and not overwrite:
            raise ValueError(f"渲染器已存在: {name}")
        RENDERERS[name] = f
        return f

    return install if fn is None else install(fn)


def get_renderer(name: str = "markdown"):
    try:
        return RENDERERS[name]
    except KeyError:
        raise KeyError(f"没有这个渲染器: {name}（可用: {', '.join(RENDERERS)}）") from None


__all__ = ["to_markdown", "to_plain", "MAX_CHARS", "SYSTEM_HINT",
           "RENDERERS", "register_renderer", "get_renderer"]
