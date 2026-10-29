"""可视化页面装配。

前端只有一份 HTML（nkb/web/index.html），两种用法：
  serve  页面自己去 /api/graph 拉数据（能写、能实时更新）
  viz    数据直接烧进 HTML，双击就能看，不依赖服务
"""
from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

PLACEHOLDER = "/*__NKB_DATA__*/null"
THREE_PLACEHOLDER = "/*__NKB_THREE__*/"


def template() -> str:
    root = resources.files("nkb.viz")
    html = root.joinpath("web/index.html").read_text("utf-8")
    bundle = root.joinpath("art/neural-art.bundle.js")
    if THREE_PLACEHOLDER in html:
        # 本地打包的 MIT Three.js；单HTML导出与桌面版均无需CDN。
        script = bundle.read_text("utf-8") if bundle.is_file() else ""
        script = script.replace("</script", "<\\/script").replace("</SCRIPT", "<\\/SCRIPT")
        html = html.replace(THREE_PLACEHOLDER, script)
    # Small product components stay local and are inlined for desktop and offline exports.
    # The connection flow is installed before hints so its dynamic buttons receive help.
    components = []
    for filename in ("connection-ux.js", "library-manager-ui.js", "memory-organizer-ui.js", "memory-portability-ui.js", "dialogue-import-ui.js", "window-handoff-ui.js", "update-checker-ui.js", "warm-theme.js", "button-hints.js"):
        path = root.joinpath("web/" + filename)
        if path.is_file():
            code = re.sub(r"</script", lambda _: "<\\/script", path.read_text("utf-8"), flags=re.IGNORECASE)
            components.append(f'<script data-nkb-component="{filename}">\n{code}\n</script>')
    if components:
        scripts = "\n".join(components) + "\n"
        position = html.lower().rfind("</body>")
        html = html[:position] + scripts + html[position:] if position >= 0 else html + scripts
    return html


def html_for_serve() -> str:
    return template()


def build(brain, out: str | Path) -> Path:
    data = json.dumps(brain.export(), ensure_ascii=False)
    # 防止节点正文里出现 </script> 把 HTML 截断
    data = data.replace("<", "\\u003c")
    html = template().replace(PLACEHOLDER, data)
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, "utf-8")
    return p
