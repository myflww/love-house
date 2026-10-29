"""兼容 `python -m nkb.cli`。推荐用 `python -m nkb` 或装好后的 `nkb`。"""
import sys

from .main import main

sys.exit(main())
