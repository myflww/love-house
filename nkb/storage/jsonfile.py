"""JSON 文件后端。

两个刻意的选择：

1. **原子写**：先写 `*.tmp` 再 `os.replace`。中途断电不会留下半个 JSON。
   这是文件存储最容易踩的坑，代价只有两行。
2. **缩进 1 空格**：为了 `git diff` 好看。知识库应该能进版本控制，
   你能看到"上周加了什么、哪条边变粗了"。

代价是全量读写。几千节点完全够用；真到十万级换 SQLite（见 ROADMAP）。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..errors import StorageError


class JsonFileStorage:
    def __init__(self, path: str | Path, *, indent: int = 1, fsync: bool = True):
        self.path = Path(path)
        self.indent = indent
        self.fsync = fsync

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict:
        if not self.path.exists():
            raise StorageError(f"找不到知识库文件: {self.path}")
        try:
            raw = self.path.read_text("utf-8")
        except OSError as exc:
            raise StorageError(f"读不了 {self.path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"{self.path} 不是合法 JSON（第 {exc.lineno} 行）: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise StorageError(f"{self.path} 的顶层必须是对象")
        return data

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=self.indent)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent),
                                       prefix=self.path.name + ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                if self.fsync:
                    os.fsync(f.fileno())
            os.replace(tmp, self.path)
            tmp = None
        except OSError as exc:
            raise StorageError(f"写不了 {self.path}: {exc}") from exc
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
