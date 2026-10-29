"""neural-kb —— 可视化、可解释、零依赖的神经知识库。

    from nkb import Brain

    b = Brain.open("brain.json")
    r = b.recall("为什么不用向量库")
    print(r["hits"][0]["label"], r["hits"][0]["score"])

公开接口都在这里。子模块是内部实现，按需 import：

    nkb.core        图与学习（Brain）
    nkb.retrieval   编码器 / 点火策略 / 扩散算法
    nkb.storage     存储后端（默认 JSON 文件）
    nkb.render      召回结果 -> 上下文文本
    nkb.ingest      文档导入
    nkb.adapters    HTTP 与 MCP
    nkb.viz         可视化装配
    nkb.cli         命令行
"""
from . import render
from ._version import __version__
from .config import Config
from .core.brain import SCHEMA_VERSION, Brain
from .errors import ConfigError, NKBError, NotFound, StorageError, ValidationError
from .retrieval.encoders import bigram, get_encoder, register_encoder
from .retrieval.scoring import OverlapScorer, dice
from .retrieval.spread import adjacency, spread_activation

__all__ = [
    "Brain", "Config", "SCHEMA_VERSION",
    "render",
    "bigram", "dice", "get_encoder", "register_encoder",
    "OverlapScorer", "adjacency", "spread_activation",
    "NKBError", "ValidationError", "NotFound", "StorageError", "ConfigError",
    "__version__",
]
