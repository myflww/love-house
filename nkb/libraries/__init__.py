"""独立本地记忆库注册表；库名不是文件路径，旧个人库保持原位。"""
from .manager import LibraryError, LibraryManager

__all__ = ["LibraryManager", "LibraryError"]
