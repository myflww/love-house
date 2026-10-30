"""异常层级。

全部继承自 `NKBError`，同时也继承对应的内置异常 —— 这样调用方既可以
`except NKBError` 一把抓，也可以用 `except ValueError` 接住老习惯。
"""
from __future__ import annotations


class NKBError(Exception):
    """所有本库异常的基类。"""


class ValidationError(NKBError, ValueError):
    """入参不合法（空 label、越界显著性、自连等）。"""


class NotFound(NKBError, KeyError):
    """节点 / 边 / 编码器不存在。"""

    def __str__(self) -> str:  # KeyError 会加引号，这里去掉
        return str(self.args[0]) if self.args else ""


class StorageError(NKBError, OSError):
    """读写失败：文件损坏、权限、磁盘满。"""


class ConfigError(NKBError, ValueError):
    """配置值非法或配置文件解析失败。"""
