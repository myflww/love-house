"""存储后端协议。

`Brain` 只依赖这个协议，不关心背后是 JSON 文件、SQLite 还是对象存储。
想要自己的后端，实现 `load()` 和 `save()` 两个方法就行：

    class MyStorage:
        def load(self) -> dict: ...
        def save(self, data: dict) -> None: ...

    brain = Brain(storage=MyStorage(), path="ignored")

`load()` 返回的就是 `brain.json` 那份结构，不需要额外抽象。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    path: object

    def load(self) -> dict: ...

    def save(self, data: dict) -> None: ...
