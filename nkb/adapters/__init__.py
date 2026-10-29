"""对外服务：HTTP 与 MCP。按需 import，避免顶层库被拖重。

    from nkb.adapters.http import serve
    from nkb.adapters.mcp import serve as mcp_serve
"""

__all__ = ["http", "mcp"]
