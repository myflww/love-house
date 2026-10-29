# 爱之屋 macOS 桌面版

原生 AppKit 窗口内嵌 WKWebView，使用应用内置 Python 3.12 启动回环 HTTP 服务。
构建和运行都不依赖 Node、网络 CDN、系统 Python 或开发工作区中的知识库。

构建（Apple Silicon，macOS 13 或更新）：

```sh
python3.12 scripts/build_macos.py
open dist/爱之屋.app
```

构建脚本复制实际 Python 运行时、后端和页面资源，编译原生窗口和密钥 helper、编码批准的图标，
执行本机 ad hoc 签名与校验，再用临时数据验证多库、凭据和退出清理。它不会安装应用。

爱之屋沿用旧版的 `local.neural-knowledge.atlas` bundle ID 与 `NeuralKnowledge` 数据目录，
不会因显示名称变化而创建另一份空白用户数据。图标只由批准的
`assets/branding/love-house-icon.png` 缩放和编码为标准 macOS iconset/ICNS，保留原图供追溯。

本机 API 凭据通过 `Contents/MacOS/NeuralCredential` 与 macOS Keychain 交互，使用固定的新 service，
按 provider、记忆库和连接引用隔离 account。密钥仅经私有 stdin/stdout 管道传递，不进入进程参数或日志；
界面只能获得 `storage/key_saved/credential_ready` 元数据。Keychain 不可用时明确降为本进程 session-only，
不会宣称持久保存成功。所有密钥验收只使用随机 FAKE account，不请求任何真实模型 API。

首次默认进入空的实际记忆库，新建库同样为空。示例仅供用户主动打开浏览，不自动成为个人记忆。
库注册表、各库 JSON 和私有原始事件 journal 存放在
`~/Library/Application Support/NeuralKnowledge`；升级时若发现旧 `personal.brain.json`，
注册表将其映射为默认库，保留原文件。连接固定归属一个库，不跟随当前页面选库。

运行日志：`~/Library/Logs/NeuralKnowledge/app.log`。服务绑定 `127.0.0.1` 的动态空闲端口；
确认健康后才载入页面。数据目录有单写者文件锁，退出应用会终止后端、关闭端口并删除就绪文件；
应用异常消失时后端会检测父进程并自行退出。菜单支持 Cmd+R 刷新、Cmd+0 返回全图、Cmd+Q 退出。

“导入笔记”使用原生文件选择面板，只读取用户明确选择的 `.md`、`.markdown`、`.txt`、`.rst`
文件，支持多选；不会自动扫描文件夹或笔记库。界面可预览待导入条目，再确认写入。

原生端到端自检（使用一次性临时个人库，不读取正式个人文件）：

```sh
dist/爱之屋.app/Contents/MacOS/NeuralAtlas --smoke-test
```

自检使用明确标为测试的数据，验证默认空库、多库隔离、固定连接、被动事件回执、人格导入/学习、
原文和附件引用留存及服务重启恢复；完成后自动退出并清理临时数据，不发起真实模型请求。

DeepSeek Harness 自动存档使用随包提供的真正宿主插件，监听已提交事件并在 pre-step 注入所选连接的
人格和记忆材料。由向导生成/应用本连接独立配置；不会把模型主动调用工具冒充被动自动采集。
具体版本、原始事件、队列、停用及安全配置契约见 `extensions/deepseek-harness/README.md`。

旧 `desktop/harness_bridge.py` 仍兼容显式旧路径与固定 `--library-id`，作为手动 `tools_only` 接入备用，
不提供宿主自动归档证明。它只连接已发现的本机 Controller，不另起写者，不退回示例或跟随页面选库。
自动存档连接和旧工具的目标库应分别核对。网页操作继续由 Harness 的审批与用户授权控制。

桥与双库隔离测试也只使用临时数据：

```sh
python3.12 -m unittest discover -s desktop -p 'test_*.py' -v
```

此包使用本机 ad hoc 签名，适合本机使用。它未经过 Developer ID 签名或公证，不能将本机验证描述为公开分发验收。
