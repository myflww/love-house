# 参与

爱之屋公开源码，采用 **PolyForm Noncommercial License 1.0.0**。欢迎在非商业许可范围内使用、研究、改进和分享；这不是 OSI 开源许可。提交贡献表示你有权按本项目许可提供该贡献；第三方材料须保留其原许可与署名。许可范围见 [发布与许可](docs/发布与许可.md)。

## 先跑起来

```bash
python3 -m unittest discover -s tests -v
python3 -m nkb doctor                        # 自检
make check                                   # 提交前跑这个
```

核心 Python 服务没有第三方运行依赖，需要 Python 3.11+。前端与宿主适配器的预构建资源随源码提供；重建资源时分别在 `nkb/viz/art` 和 `extensions/deepseek-harness` 执行 `npm ci`，然后运行各自的构建/测试命令。想跑 lint 再 `make dev`。桌面构建还需要 macOS、Xcode Command Line Tools 与完整 Python 3.12 runtime。

## 代码地图

```
nkb/core/brain.py       门面类：把下面这些零件串起来
nkb/retrieval/spread.py 扩散算法（纯函数，无状态，最好改的地方）
nkb/retrieval/scoring.py点火策略
nkb/retrieval/encoders.py 文本 -> 集合
nkb/storage/jsonfile.py 原子写 JSON
nkb/render/markdown.py  召回结果 -> 注入文本
nkb/adapters/           HTTP / MCP
nkb/cli/main.py         命令行
nkb/viz/web/index.html  前端（单文件，无构建）
```

**改动前先看 `docs/架构.md`**，那里有公式和取舍。改算法要连公式一起改。

## 四条规矩

1. **不要为了让测试通过去放宽语义。**
   比如"遗忘应该删掉旧节点"这条，测试是意图的刻录。改行为就先改测试，并在 commit 里说明为什么。

2. **前端和 Python 的检索公式必须一致。**
   `nkb/viz/web/index.html` 里的 `seedScores()` / `spread()` 是 `scoring.py` / `spread.py` 的复刻。
   只改一边，服务模式和离线模式就会给出不同分数。改完用同一句话各查一次比对。

3. **新增依赖要讨论。**
   运行时零依赖是核心卖点（`pip install` 之后任何机器都能跑）。
   需要第三方库的功能，做成可选 extras，并在没有它时优雅降级。

4. **所有异常走 `nkb/errors.py`。**
   别抛裸 `Exception`。调用方需要能 `except NKBError` 一把抓。

## 加一个编码器（接 embedding / 分词器）

最小实现：

```python
# my_pkg.py
def my_encoder(text: str) -> set[str]:
    vec = model.encode(text)              # 你自己的模型
    return {f"b{int(v*100)}" for v in vec}  # 量化成可比较的集合
```

三种接法，任选：

```python
Brain(encode=my_encoder)                                  # 直接传
from nkb.retrieval.encoders import register_encoder
register_encoder("mine", my_encoder); Brain(encode="mine")  # 注册
```

发布成插件让 `Brain(encode="mine")` 在任何地方可用：

```toml
[project.entry-points."nkb.encoders"]
mine = "my_pkg:my_encoder"
```

> 注意：默认打分用集合交并（`dice` / containment）。用真向量的话，
> 要么量化成集合，要么自己实现一个 `SeedScorer`（签名字见 `retrieval/scoring.py`）。

## 加一个存储后端

实现两个方法即可，`Brain` 不关心背后是什么：

```python
class SqliteStorage:
    path = "brain.db"
    def load(self) -> dict: ...
    def save(self, data: dict) -> None: ...

brain = Brain(storage=SqliteStorage(), path="brain.db")
```

约定：`load()` 返回的结构必须和 `brain.json` 一致（见 `docs/架构.md`）。
写操作要原子——中途失败不能留下半个库。

## 加一个渲染格式

```python
from nkb.render import register_renderer

@register_renderer("slack")
def render_slack(result, max_chars=1800):
    return "\n".join(f'• {h["label"]}（{h["score"]:.2f}）' for h in result["hits"])
```

## 加一个 MCP 工具

`nkb/adapters/mcp.py` 里两处：`TOOLS` 加 schema，`call_tool` 加分支。
工具内部抛异常不要紧，`call_tool` 会把它包成 `isError` 返回给模型 —— 进程不能死。

## 提交

- 一个 commit 一件事。信息写"为什么"，不写"改了什么"（diff 已经说明了）。
- 涉及行为变化：同时改测试 + `CHANGELOG.md`。
- 改了 `kernel` 无关的东西也要跑 `make test`。

## 不要做的事

- 不要把未经证据验证的模型输出当成事实；整理模型由用户明确启用，原文先保存，推断、冲突和人格候选保留审阅入口。
- 不要把 `brain.json` 提交进仓库（已经在 `.gitignore` 里）。要分享用 `nkb viz` 导出。
- 不要在没有衰减的情况下扩大库。不衰减的库会越长越吵，这是设计问题不是性能问题。

## 公开发布

使用 `scripts/prepare_public_release.py` 生成新的干净发布目录，再检查其相对路径/哈希清单；不要直接将整个开发工作目录上传。用户库、Key、连接令牌、导出分享文件、回滚副本和验收截图必须留在本机。公开发布步骤、扫描范围及许可证依据见 [发布与许可](docs/发布与许可.md)。
