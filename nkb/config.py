"""配置。

优先级（低 → 高）：
    代码默认值  <  知识库文件配置（兼容旧 half_life） <  显式 Config  <  环境变量

环境变量都是 `NKB_` 前缀，见 `_ENV_MAP`。配置文件支持 `nkb.toml`：

    [nkb]
    steps = 4
    damping = 0.55

    [nkb.half_life]
    episode = 30
"""
from __future__ import annotations

import os
import math
import tomllib
from copy import deepcopy
from dataclasses import dataclass, field, fields
from pathlib import Path

from .errors import ConfigError

DEFAULT_HALF_LIFE: dict[str, float | None] = {
    "concept": None,      # 概念不衰减
    "source": None,       # 来源不衰减
    "fact": 365.0,
    "preference": 365.0,
    "question": 180.0,
    "answer": 180.0,
    "doc": 240.0,
    "episode": 60.0,
    "commitment": None,   # 承诺不衰减，直到被了结
    "reflection": None,   # 反思/归纳是"信念"，不随时间变淡
}

_ENV_MAP = {
    "NKB_STEPS": ("steps", int),
    "NKB_DAMPING": ("damping", float),
    "NKB_K": ("k", int),
    "NKB_SEED_FLOOR": ("seed_floor", float),
    "NKB_AUTO_LINK_TOP": ("auto_link_top", int),
    "NKB_RECOVERY_DAYS": ("recovery_days", float),
    "NKB_ANCHOR_THRESHOLD": ("anchor_threshold", float),
    "NKB_MAX_NODES": ("max_nodes", int),
}


@dataclass(slots=True)
class Config:
    half_life: dict = field(default_factory=lambda: dict(DEFAULT_HALF_LIFE))

    drop_below: float = 0.05          # 低于此值进入休眠；唤醒窗内不提前删除
    edge_max: float = 0.999           # 边权上限，保证严格小于 1
    edge_half_life: float = 90.0      # 边自己的半衰期（天）

    seed_floor: float = 0.06          # 点火阈值：低于它且无标签命中，不进种子
    steps: int = 3                    # 扩散跳数
    damping: float = 0.6              # 每跳衰减
    retain: float = 0.86              # 节点自身保留系数
    k: int = 8                        # 默认返回条数
    min_score: float = 0.08           # 低于这个分数不出现在结果里

    hebbian_lr: float = 0.14          # 赫布学习率
    salience_bump: float = 0.34       # 被召回一次回多少血
    auto_link_top: int = 2            # 新节点自动连几个

    recovery_days: float = 200.0     # 可遗忘节点最后一次提起后的恢复窗口
    anchor_threshold: float = 0.75   # 情绪冲击绝对值达到阈值，形成重要事件锚点
    important_threshold: float = 0.95
    context_before: int = 2          # 每个锚点前后各至多保留多少条真实事件引用
    context_after: int = 2
    context_window_hours: float = 6.0
    bridge_window_hours: float = 24.0 # 同会话相邻锚点的最大桥接间隔
    bridge_max_events: int = 6        # 只引用真实发生的中间事件，绝不生成补写
    max_nodes: int = 10000            # 容量硬上限；全受保护时拒绝继续写入

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        def number(name, value):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ConfigError(f"{name} 必须是有限数值")

        for name in ("drop_below", "edge_max", "seed_floor", "damping", "retain",
                     "min_score", "hebbian_lr", "salience_bump", "anchor_threshold",
                     "important_threshold"):
            value = getattr(self, name)
            number(name, value)
            if not 0 <= value <= 1:
                raise ConfigError(f"{name} 必须落在 [0,1]")
        for name in ("drop_below", "edge_max", "anchor_threshold", "important_threshold"):
            if getattr(self, name) == 0 or (name in ("drop_below", "edge_max") and getattr(self, name) == 1):
                raise ConfigError(f"{name} 超出有效范围")
        for name in ("edge_half_life", "recovery_days", "context_window_hours", "bridge_window_hours"):
            value = getattr(self, name)
            number(name, value)
            if value <= 0:
                raise ConfigError(f"{name} 必须大于 0")
        for name in ("steps", "k", "auto_link_top", "context_before", "context_after", "bridge_max_events", "max_nodes"):
            value = getattr(self, name)
            minimum = 1 if name in ("steps", "k", "max_nodes") else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ConfigError(f"{name} 必须是至少 {minimum} 的整数")
        if not isinstance(self.half_life, dict):
            raise ConfigError("half_life 必须是字典")
        for kind, hl in self.half_life.items():
            if hl is not None:
                number(f"half_life[{kind}]", hl)
                if hl <= 0:
                    raise ConfigError(f"half_life[{kind}] 必须是正数或 None")

    # ── 序列化 ──
    def to_dict(self) -> dict:
        return {f.name: deepcopy(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Config":
        if not data:
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        if "half_life" in kwargs:
            if kwargs["half_life"] is not None and not isinstance(kwargs["half_life"], dict):
                raise ConfigError("half_life 必须是字典")
            merged = dict(DEFAULT_HALF_LIFE)
            merged.update(kwargs["half_life"] or {})
            kwargs["half_life"] = merged
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """从 nkb.toml 读 [nkb] 段。文件不存在就返回默认值。"""
        p = Path(path) if path else Path.cwd() / "nkb.toml"
        if not p.exists():
            return cls()
        try:
            with p.open("rb") as f:
                raw = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"读不了配置文件 {p}: {exc}") from exc
        return cls.from_dict(raw.get("nkb", {}))

    def with_env(self, env: dict | None = None) -> "Config":
        """叠加环境变量，返回新对象。"""
        env = os.environ if env is None else env
        data = self.to_dict()
        for key, (name, caster) in _ENV_MAP.items():
            if key not in env or caster is None:
                continue
            try:
                data[name] = caster(env[key])
            except ValueError as exc:
                raise ConfigError(f"{key}={env[key]!r} 无法解析") from exc
        return Config.from_dict(data)
