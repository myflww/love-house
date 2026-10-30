"""内部小工具。不对外承诺稳定性。"""
from __future__ import annotations

import time

DAY = 86400.0


def now() -> float:
    return time.time()


def fmt_age(ts: float, ref: float | None = None) -> str:
    """把时间戳说成人话。'3 天前' 比 '1761900000' 有用得多。"""
    d = ((ref if ref is not None else now()) - ts) / DAY
    if d < 1:
        return "今天"
    if d < 2:
        return "昨天"
    if d < 30:
        return f"{int(d)} 天前"
    if d < 365:
        return f"{int(d / 30)} 个月前"
    return f"{d / 365:.1f} 年前"
