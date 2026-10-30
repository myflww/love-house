"""命令行入口。`nkb --help`。"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

from .._version import __version__
from .. import render
from ..core.brain import Brain
from ..config import Config
from ..errors import NKBError
from ..ingest import ingest_dir
from ..viz import builder as viz

DEFAULT = "brain.json"


def _load(path: str) -> Brain:
    p = Path(path)
    if not p.exists():
        sys.exit(f"找不到 {p}。先跑 `nkb init` 或 `nkb init --demo`。")
    return Brain.open(p, config=Config.load() if Path('nkb.toml').exists() else None)


def _tags(s: str | None) -> list[str]:
    return [t.strip() for t in (s or "").replace("，", ",").split(",") if t.strip()]


# ────────────────────────── 命令 ──────────────────────────
def cmd_init(a):
    from ..core.seed import demo_brain
    p = Path(a.brain)
    if p.exists() and not a.force:
        sys.exit(f"{p} 已存在。要覆盖加 --force。")
    if a.atlas:
        from ..core.atlas import atlas_brain
        b = atlas_brain(p, name="爱之屋 · 框架示例")
    elif a.demo:
        b = demo_brain(p, name=p.stem)
    else:
        b = Brain.new(p, name=p.stem)
    b.save()
    print(f"建好了：{p}（{b.name}，{len(b.nodes)} 节点）")
    if a.demo or a.atlas:
        print("下一步： nkb serve        打开可视化")
        print("         nkb recall \"为什么不用向量库\"")


def cmd_add(a):
    b = _load(a.brain)
    nid = b.add(a.label, a.text or "", kind=a.kind,
                tags=_tags(a.tags), salience=a.salience, impact=a.impact,
                event_at=_parse_when(a.event_at) if a.event_at else None,
                session_id=a.session,
                meta={"important": True} if a.important else None)
    links = [] if a.no_link else b.auto_link(nid, top=a.link_top)
    b.save()
    print(f"已加入 {nid} · {a.kind} · {a.label}")
    for i, w in links:
        print(f"  自动连到 {b.nodes[i]['label']}  (w={w})")


def cmd_link(a):
    b = _load(a.brain)
    w = b.link(a.a, a.b, a.w)
    b.save()
    print(f"{b.nodes[a.a]['label']}  ⇄  {b.nodes[a.b]['label']}   w={w}")


def cmd_recall(a):
    b = _load(a.brain)
    r = b.recall(a.query, k=a.k, steps=a.steps, damping=a.damping)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif a.md:
        print(render.to_markdown(r))
    else:
        if not r["hits"]:
            print("没有命中。知识库里没有相关内容。")
        else:
            print(f"查询：{a.query}   点燃 {len(r['seeds'])} 个，访问 {r['visited']} 个，"
                  f"扩散 {r['steps']} 跳")
            for i, h in enumerate(r["hits"], 1):
                path = " → ".join(h["path_labels"][:-1]) if len(h["path"]) > 1 else "直接命中"
                print(f"{i:>2}. [{h['score']:.2f}] {h['label']}  ({h['kind']}, {h['depth']} 跳)")
                print(f"    来自：{path}")
    if a.learn and r["hits"]:
        info = b.reinforce([h["id"] for h in r["hits"][:4]])
        b.save()
        print(f"\n已强化：{info['nodes']} 个节点，{info['pairs']} 条边")


def cmd_get(a):
    b = _load(a.brain)
    nid = a.id
    if nid not in b.nodes:
        cands = [i for i, n in b.nodes.items() if a.id in n["label"]]
        if len(cands) != 1:
            sys.exit(f"找不到唯一节点：{a.id}（候选 {len(cands)} 个）")
        nid = cands[0]
    n = b.nodes[nid]
    print(f"{n['label']}   [{n['kind']}]   {nid}")
    print(f"显著性 {n['salience']}   被召回 {n['recalls']} 次")
    if n["tags"]:
        print(f"标签：{'、'.join(n['tags'])}")
    print()
    print(n["text"] or "（无正文）")
    nb = b.neighbors(nid)
    if nb:
        print("\n邻居：")
        for i, w in nb:
            print(f"  ({w:.2f}) {b.nodes[i]['label']}")


def cmd_stats(a):
    b = _load(a.brain)
    s = b.stats()
    print(f"{s['name']}  ·  {s['nodes']} 节点 / {s['edges']} 边")
    print(f"连接强度合计 {s['strength']}   平均边权 {s['mean_w']}   "
          f"显著性合计 {s['salience_sum']}   累计召回 {s['recalls']}")
    for k, v in sorted(s["kinds"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {v}")


def cmd_ingest(a):
    b = _load(a.brain)
    r = ingest_dir(b, a.dir, kind=a.kind, mode=a.mode)
    b.save()
    print(f"已存盘：{a.brain}  ({len(b.nodes)} 节点)")


def cmd_forget(a):
    b = _load(a.brain)
    r = b.forget()
    b.save()
    print(f"清理 {r['dropped']} 个节点，变淡 {r['thinned']} 条边")
    for i in r["dropped_ids"][:10]:
        print(f"  掉了：{i}")


def cmd_serve(a):
    from ..adapters.http import serve
    b = _load(a.brain)
    httpd = serve(b, host=a.host, port=a.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停了。")
    finally:
        httpd.server_close()
        b.save()


def cmd_mcp(a):
    from ..adapters.mcp import serve as mcp_serve
    b = _load(a.brain)
    print(f"[nkb-mcp] ready · {b.name} · {len(b.nodes)} nodes", file=sys.stderr)
    mcp_serve(b)
    b.save()


def cmd_viz(a):
    b = _load(a.brain)
    out = viz.build(b, a.out)
    print(f"写好了：{out}（自包含，双击就能开，不需要服务器）")


def cmd_export(a):
    b = _load(a.brain)
    Path(a.out).write_text(json.dumps(b.export(), ensure_ascii=False, indent=1), "utf-8")
    print(f"已导出 {a.out}")


def cmd_preview(a):
    """预览未来，不修改或保存知识库。"""
    b = _load(a.brain)
    result = b.preview(days=a.days)
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    counts = {}
    for n in result["nodes"]:
        counts[n["state"]] = counts.get(n["state"], 0) + 1
    print(f"+{a.days:g} 天 · 只读预览，不改写知识库")
    for state, title in [("active", "清晰"), ("fading", "淡化"),
                         ("dormant", "休眠"), ("forgotten", "已遗忘/失效")]:
        print(f"  {title}: {counts.get(state, 0)}")


def _parse_when(text: str) -> float | None:
    """接受 2026-11-01 / +3d / +12h / 空。"""
    import time
    from datetime import datetime
    if not text:
        return None
    text = text.strip()
    if text.startswith("+"):
        unit = text[-1]
        n = float(text[1:-1])
        if unit not in ("d", "h", "w") or not math.isfinite(n):
            raise ValueError("相对时间请使用 +3d / +12h / +2w")
        return time.time() + n * {"d": 86400, "h": 3600, "w": 604800}[unit]
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    sys.exit(f"看不懂的时间：{text}（用 2026-11-01 或 +3d）")


def cmd_commit(a):
    b = _load(a.brain)
    nid = b.commit(a.what, due=_parse_when(a.due), text=a.text or "")
    b.save()
    print(f"记下了承诺 {nid}：{a.what}" + (f"（到期 {a.due}）" if a.due else ""))


def cmd_due(a):
    b = _load(a.brain)
    rows = b.due(now=None)
    if not rows:
        print("没有未了结的承诺。")
        return
    from ..utils import fmt_age
    for r in rows:
        when = fmt_age(r["due"])
        mark = f"逾期 {r['overdue_days']:.0f} 天" if r["overdue_days"] > 0 else f"到期 {when}"
        print(f"  · {r['label']}  [{mark}]  {r['id']}")


def cmd_resolve(a):
    b = _load(a.brain)
    n = b.resolve(a.id, a.note or "")
    b.save()
    print(f"了结了：{n['label']}")


def cmd_supersede(a):
    b = _load(a.brain)
    b.supersede(a.old, a.new)
    b.save()
    print(f"{b.nodes[a.old]['label']} 已被 {b.nodes[a.new]['label']} 取代（旧记录保留，不再参与检索）")


def cmd_history(a):
    b = _load(a.brain)
    chain = b.history(a.id)
    for i, h in enumerate(chain):
        from ..utils import fmt_age
        vf = fmt_age(h["valid_from"]) if h["valid_from"] else "?"
        vt = ("至今有效" if h["valid_to"] is None
              else f"到 {fmt_age(h['valid_to'])} 失效")
        print(f"  {'└─' if i else '  '} {h['label']}  （{vf} 起，{vt}）")


def cmd_reflect(a):
    from ..core.lifecycle import reflect
    b = _load(a.brain)
    r = reflect(b, min_cluster=a.min_cluster, max_new=a.max_new)
    b.save()
    if not r["created"]:
        print(f"没有新的可归纳（已有 {len(r['skipped'])} 个主题反思过，"
              f"或没有标签重复到 {a.min_cluster} 次）")
    for c in r["created"]:
        print(f"归纳出：{b.nodes[c['id']]['label']}（来自 {c['members']} 条）")


def cmd_tick(a):
    from ..core.lifecycle import tick
    b = _load(a.brain)
    r = tick(b, reflect_new=not a.no_reflect)
    b.save()
    print(f"tick · {r['summary']}")
    for d in r["due"]:
        flag = "逾期" if d["overdue_days"] > 0 else "将到期"
        print(f"  ! {d['label']}（{flag}）")


def cmd_bench(a):
    from .. import bench
    b = _load(a.brain)
    if a.probes:
        result = bench.run_probes(b, bench.load_probes(a.probes), k=a.k)
    else:
        result = bench.leave_one_out(b, k=a.k)
    print(bench.format_report(result, verbose=a.verbose))
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))


def cmd_doctor(a):
    """自检。接不上、跑不动的时候第一个该跑的命令。"""
    from importlib import resources
    from ..adapters.mcp import handle as mcp_handle

    ok = fail = 0
    def line(good, text, hint=""):
        nonlocal ok, fail
        mark = "✓" if good else "✗"
        ok += 1 if good else 0
        fail += 0 if good else 1
        print(f"  {mark} {text}" + (f"\n      → {hint}" if not good and hint else ""))

    print("neural-kb doctor\n")

    v = sys.version_info
    line(v >= (3, 11), f"Python {v.major}.{v.minor}.{v.micro}（需要 ≥ 3.11）",
         "升级 Python，或用 pyenv 装一个新的")

    p = Path(a.brain)
    brain = None
    if not p.exists():
        line(False, f"知识库文件 {p} 不存在", "单库模式可运行 `nkb init` 创建空库；桌面模式请用爱之屋或 scripts/launch.py")
    else:
        try:
            brain = Brain.open(p)
            s = brain.stats()
            line(True, f"{p.name} 可读 · {s['nodes']} 节点 / {s['edges']} 边")
        except Exception as exc:
            line(False, f"{p.name} 读不了：{exc}", "文件可能坏了；有备份就换回来")

    if brain is not None:
        try:
            probe = p.parent / f".nkb-write-test-{os.getpid()}"
            probe.write_text("ok", "utf-8")
            probe.unlink()
            line(True, f"目录可写：{p.parent}")
        except OSError as exc:
            line(False, f"目录不可写：{exc}", "换目录，或改权限")

        n = len(brain.nodes)
        line(True, f"节点数 {n}" + ("（正常的空白记忆库）" if n == 0 else ""))

        dead = [i for i in brain.nodes if not brain.neighbors(i)]
        line(not dead, f"孤立节点 {len(dead)} 个",
             "孤立节点不会被扩散带到；跑 `nkb link` 或重新 ingest")

    from ..retrieval.encoders import available
    encs = available()
    line(bool(encs), f"可用编码器：{', '.join(sorted(encs))}")

    try:
        asset = resources.files("nkb.viz").joinpath("web/index.html")
        size = len(asset.read_bytes()) // 1024
        line(True, f"可视化资源 web/index.html（{size} KB）")
    except Exception as exc:
        line(False, f"可视化资源缺失：{exc}", "重装：pip install --force-reinstall .")

    if brain is not None:
        try:
            resp = mcp_handle(brain, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "2024-11-05"}})
            line(resp["result"]["serverInfo"]["name"] == "neural-kb",
                 "MCP 协议自检通过（initialize + tools）")
        except Exception as exc:
            line(False, f"MCP 自检失败：{exc}", "看 nkb/adapters/mcp.py")

    key = os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY")
    print(f"  {'✓' if key else '·'} 模型 API key {'已设置' if key else '未设置（只有 examples/03 需要）'}")

    print(f"\n{ok} 项通过" + (f"，{fail} 项失败" if fail else "，全部通过"))
    return 0 if fail == 0 else 1


def cmd_config(a):
    cfg = (_load(a.brain).config if Path(a.brain).exists() else Config.load().with_env())
    if a.write:
        target = Path("nkb.toml")
        if target.exists() and not a.force:
            sys.exit("nkb.toml 已存在。要覆盖加 --force。")
        rows = ["# 留空的类型使用默认半衰期；TOML 没有 null，不要写 kind = null。", "[nkb]"]
        for key, value in cfg.to_dict().items():
            if key != "half_life":
                rows.append(f"{key} = {json.dumps(value)}")
        rows.extend(["", "[nkb.half_life]"])
        for key, value in cfg.half_life.items():
            rows.append(f"# {key} 默认不衰减" if value is None else f"{key} = {value}")
        target.write_text("\n".join(rows) + "\n", "utf-8")
        print(f"写好模板：{target}")
        return
    print(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=1))


# ────────────────────────── 参数 ──────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nkb", description=f"neural-kb {__version__} · 可解释的神经知识库")
    p.add_argument("-b", "--brain", default=DEFAULT, help=f"知识库文件（默认 {DEFAULT}）")
    p.add_argument("-V", "--version", action="version", version=f"neural-kb {__version__}")

    # 让 -b 写在子命令后面也生效（python -m nkb.cli mcp -b /path/brain.json）
    # 用 SUPPRESS 保证没写时不会把主解析器的值覆盖成默认值。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-b", "--brain", default=argparse.SUPPRESS,
                        help="知识库文件（同全局 --brain）")

    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", parents=[common], help="新建知识库")
    demo = s.add_mutually_exclusive_group()
    demo.add_argument("--demo", action="store_true", help="填入10条基础示例知识")
    demo.add_argument("--atlas", action="store_true", help="填入可浏览的神经图谱示例（非个人记忆）")
    s.add_argument("--force", action="store_true", help="覆盖已有文件")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("add", parents=[common], help="加一条知识")
    s.add_argument("label")
    s.add_argument("--text", default="")
    s.add_argument("--kind", default="concept")
    s.add_argument("--tags", default="")
    s.add_argument("--salience", type=float, default=0.6)
    s.add_argument("--impact", type=float, default=0.0, help="情绪冲击 -1~1")
    s.add_argument("--session", default=None, help="同一会话的标识，用于锚点上下文")
    s.add_argument("--event-at", default=None, help="事件时间，例如 '2026-10-28 08:30'")
    s.add_argument("--important", action="store_true", help="标记重要记忆，免于时间遗忘")
    s.add_argument("--no-link", action="store_true", help="不自动连边")
    s.add_argument("--link-top", type=int, default=2)
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("link", parents=[common], help="连边")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("-w", type=float, default=0.4)
    s.set_defaults(fn=cmd_link)

    s = sub.add_parser("recall", parents=[common], help="检索")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=None, help="返回数量，默认使用知识库配置")
    s.add_argument("--steps", type=int, default=None, help="扩散跳数，默认使用知识库配置")
    s.add_argument("--damping", type=float, default=None, help="阻尼，默认使用知识库配置")
    s.add_argument("--json", action="store_true", help="输出完整 JSON（含 seeds/trail）")
    s.add_argument("--md", action="store_true", help="输出要注入模型的那段文本")
    s.add_argument("--learn", action="store_true", help="这次检索同时强化被召回节点")
    s.set_defaults(fn=cmd_recall)

    s = sub.add_parser("get", parents=[common], help="看一个节点")
    s.add_argument("id")
    s.set_defaults(fn=cmd_get)

    s = sub.add_parser("stats", parents=[common], help="统计")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("commit", parents=[common], help="记一条承诺（前瞻记忆）")
    s.add_argument("what")
    s.add_argument("--due", default="", help="2026-11-01 或 +3d")
    s.add_argument("--text", default="")
    s.set_defaults(fn=cmd_commit)

    s = sub.add_parser("due", parents=[common], help="看未了结的承诺")
    s.set_defaults(fn=cmd_due)

    s = sub.add_parser("resolve", parents=[common], help="了结一个承诺")
    s.add_argument("id")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_resolve)

    s = sub.add_parser("supersede", parents=[common], help="新事实取代旧事实（旧的不删，退出检索）")
    s.add_argument("old")
    s.add_argument("new")
    s.set_defaults(fn=cmd_supersede)

    s = sub.add_parser("history", parents=[common], help="一条知识被取代的链条")
    s.add_argument("id")
    s.set_defaults(fn=cmd_history)

    s = sub.add_parser("reflect", parents=[common], help="把重复出现的碎片压成一条归纳")
    s.add_argument("--min-cluster", type=int, default=3, dest="min_cluster")
    s.add_argument("--max-new", type=int, default=2, dest="max_new")
    s.set_defaults(fn=cmd_reflect)

    s = sub.add_parser("tick", parents=[common], help="醒一次：遗忘 → 反思 → 看欠着的事")
    s.add_argument("--no-reflect", action="store_true")
    s.set_defaults(fn=cmd_tick)

    s = sub.add_parser("bench", parents=[common], help="测检索：留一法或自定义探针")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--probes", default="")
    s.add_argument("--json", action="store_true")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(fn=cmd_bench)

    s = sub.add_parser("doctor", parents=[common], help="自检：能不能读、能不能写、MCP 通不通")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("config", parents=[common], help="查看或生成配置")
    s.add_argument("--write", action="store_true", help="写一份 nkb.toml 模板")
    s.add_argument("--force", action="store_true", help="覆盖已有 nkb.toml")
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("ingest", parents=[common], help="导入一个目录下的 md/txt")
    s.add_argument("dir")
    s.add_argument("--kind", default="doc")
    s.add_argument("--mode", default="heading", choices=["heading", "whole"])
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("forget", parents=[common], help="执行一次衰减")
    s.set_defaults(fn=cmd_forget)

    s = sub.add_parser("preview", parents=[common], help="只读预览未来记忆，不修改库")
    s.add_argument("--days", type=float, default=30)
    s.add_argument("--json", action="store_true", help="输出完整预测图谱")
    s.set_defaults(fn=cmd_preview)

    s = sub.add_parser("serve", parents=[common], help="起 HTTP + 可视化")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("mcp", parents=[common], help="以 MCP server 运行（stdio）")
    s.set_defaults(fn=cmd_mcp)

    s = sub.add_parser("viz", parents=[common], help="导出单文件可视化")
    s.add_argument("--out", default="brain.html")
    s.set_defaults(fn=cmd_viz)

    s = sub.add_parser("export", parents=[common], help="导出 JSON")
    s.add_argument("--out", default="graph.json")
    s.set_defaults(fn=cmd_export)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (NKBError, ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
