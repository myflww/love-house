"""编码器：把文本变成可比较的集合。

默认是字符二元组（中文友好、零依赖、无训练）。想换成向量 / 分词器 / 任何东西，
只要满足 `Encoder` 协议：吃字符串，吐 set。

三种注册方式：

    # 1) 直接传函数
    Brain(encode=my_encoder)

    # 2) 注册到全局表，之后按名字用
    from nkb.retrieval.encoders import register_encoder
    register_encoder("mine", my_encoder)
    Brain(encode="mine")

    # 3) 发布成插件（别人装了你的包就能用名字引用）
    #    pyproject.toml:
    #    [project.entry-points."nkb.encoders"]
    #    mine = "my_pkg:encoder"
"""
from __future__ import annotations

import re
from importlib import metadata
from typing import Callable

from ..errors import NotFound

KEEP = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")
ENTRY_POINT_GROUP = "nkb.encoders"

Encoder = Callable[[str], set[str]]

_REGISTRY: dict[str, Encoder] = {}
_ENTRY_CACHE: dict[str, Encoder] | None = None


def bigram(text: str) -> set[str]:
    """字符二元组。

    中文不需要分词器：'手冲咖啡' -> {手冲, 冲咖, 咖啡}。
    英文按连续字符切，'neural-kb' -> {ne, eu, ur, ra, al, lk, kb}。
    """
    out: set[str] = set()
    for chunk in KEEP.findall(text or ""):
        if len(chunk) == 1:
            out.add(chunk)
        for i in range(len(chunk) - 1):
            out.add(chunk[i:i + 2])
    return out


def register_encoder(name: str, fn: Encoder, *, overwrite: bool = False) -> None:
    if name in _REGISTRY and not overwrite:
        raise ValueError(f"编码器已存在: {name}（要覆盖请传 overwrite=True）")
    _REGISTRY[name] = fn


def _entry_points() -> dict[str, Encoder]:
    global _ENTRY_CACHE
    if _ENTRY_CACHE is None:
        found: dict[str, Encoder] = {}
        try:
            for ep in metadata.entry_points(group=ENTRY_POINT_GROUP):
                try:
                    found[ep.name] = ep.load()
                except Exception:      # 第三方包坏了不该拖垮我们
                    continue
        except Exception:
            pass
        _ENTRY_CACHE = found
    return _ENTRY_CACHE


def available() -> dict[str, str]:
    """列出可用编码器：名字 -> 来源。"""
    out = {name: "builtin" for name in _REGISTRY}
    out.setdefault("bigram", "builtin")
    for name in _entry_points():
        out.setdefault(name, "plugin")
    return out


def get_encoder(spec: Encoder | str | None) -> Encoder:
    if spec is None:
        return bigram
    if callable(spec):
        return spec
    if spec == "bigram":
        return bigram
    if spec in _REGISTRY:
        return _REGISTRY[spec]
    eps = _entry_points()
    if spec in eps:
        return eps[spec]
    raise NotFound(f"没有这个编码器: {spec}（可用: {', '.join(available())}）")


register_encoder("bigram", bigram, overwrite=True)
