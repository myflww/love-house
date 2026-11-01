# macOS 0.10.2 接入、整理状态与星云自旋移植交接

## 交接范围与基线

Windows 0.10.2rc1 以已发布的 Windows 0.10.1rc1 为基线，新增三项共享功能。本次没有构建 macOS 新安装包。Mac 当前发布基线为 `v0.10.1`；生产源码 `b2279da12c3b14d4708595343433849f3f8f2911`，不要将 Windows 原生入口覆盖到 Mac 工程。

从 `codex/windows-0102-astrbot` 获取共享增量。发布后的精确受测提交与哈希见 `v0.10.2rc1` 的 `Windows-0102-verification.json`；发布标签还带最终文档与受测文件索引。所有测试使用合成资料；成功案例中的私人标识和路径没有进入公开交接书。

## 1. AstrBot 快速配置与插件 0.3.0

主要文件：`nkb/service/astrbot_setup.py`（新增）、`nkb/service/agent_sources.py`、`nkb/service/host.py`、`nkb/viz/web/agent-sources-ui.js`、`extensions/astrbot-love-house/` 及相关 AstrBot／agent sources 回归。

保留现有管理界面会话鉴权与人工归属确认。向导收集同机范围、平台、目标会话 `/sid`，生成实际存在的私有来源配置、固定标识、会话白名单和完整插件 JSON。配置路径必须来自 Mac 自身的来源服务，不能复制 Windows 绝对路径。另一台服务器或隔离容器不能直接使用本机文件，需走对应宿主的安全配置流程。

插件固定目录为 `astrbot_plugin_love_house`，配置文件为 `data/config/astrbot_plugin_love_house_config.json`。升级时保留其他绑定；坏绑定逐条降级，冲突会话拒绝归属。状态命令只报告安全原因计数，不能输出 UMO、正文或来源 token。交付后清空插件正文的状态需兼容旧 `queued`；持久 SDK 队列不等于远端入库回执。

同步 `metadata.yaml`、包生成器、插件自报版本和 Mac 原生“导出插件”的默认文件名到 `LoveHouse-AstrBot-0.3.0-experimental.zip`。保持 `source_client.py` 与共享 SDK 字节一致及确定性 ZIP 白名单。不要提交配置、journal 或用户聊天数据库。

同时核对 `scripts/build_macos.py` 的插件包资源输出，以及 `desktop/AtlasApp.swift` 的 Bundle 资源查找、保存面板默认文件名和读取路径；不能只改面板显示的版本而仍读取旧资源。目标分支中若有 0.1.0／0.2.0 的旧字样，应将这几个环节一起对齐到 0.3.0。

生成的插件 JSON 字段为 `enabled:true`、`record_scheduled_outputs:false`、`record_observations:true`，以及 `bindings` 数组；每条绑定包含 `runtime_agent_id`、`source_config_path`、`allowed_umos`、`platform`。来源 token 不进入这份插件 JSON，而留在受权限保护的私有来源文件中。

## 2. 当前库整理 API 状态

主要文件：`nkb/service/host.py` 的 `organizer_view`，`nkb/viz/web/memory-organizer-ui.js`，`tests/test_organizer_configuration_status.py`、`tests/js/organizer-configuration-ui.test.cjs`。

后端返回分库 `library_id` 和 `configuration={configured,state,scope,network_verified:false}`。连接撤销、外库连接、凭据不可用按失败关闭。保留 Mac Keychain 语义，不引入 Windows Credential Manager 实现。

前端库名下常驻 `organizerLibraryApiStatus`，整理面板顶部 `organizerApiStatus` 展开显示服务、模型及保存范围。成功 POST 后立即更新，GET 失败保留本次已确认配置并说明读取失败；换库／epoch 切换必须清空，过期响应不能覆盖新库。密钥不得进入标签、DOM 文本、日志或截图。

“已配置”只代表本机配置；查看和保存不得偷偷发起付费模型请求。只在会话有效的凭据重启后应显示需重新填写。原始导出不依赖整理就绪。

## 3. 原版动态星云自旋

直接移植 `nkb/viz/art/approved-atlas-renderer.js` 和同步构建的 `neural-art.bundle.js`，配套 `tests/js/approved-atlas-renderer.test.mjs`、`tests/test_neural_atlas.py`。原版画笔函数保持不变。

渲染相机围绕当前目标的世界 Y 轴转动，正 yaw 对应前景点屏幕向左，速度 0.035rad/s，使用实际经过时间。仅改变视角，不修改节点坐标、关系、召回或存档。

实际输入画布 `#cv` 悬停后暂停，移开恢复；`#artCanvas` 是绘制层，不接收指针。拖拽／捕获、手动暂停、减少动态、隐藏、平面及过渡过程中停止，恢复不补跳。对焦点／可见性恢复重查悬停。只读 dataset：`autoRotate`、`autoRotateYaw`、`autoRotateReason`、`autoRotateHovered`、`autoRotateInteracting`。

## Mac 验证与交付

运行 Python 项目回归及 `desktop` 适配回归；使用现有 Node 测试入口运行 JS 回归，`nkb/viz/art` 下 `npm ci`、`npm run build` 重建 bundle。新增配置状态及 AstrBot 测试必须保留旧来源鉴权、库隔离、失败降级与不泄露凭证的断言。

可先在目标源码与开发虚拟环境执行：

```sh
python3 -m unittest discover -s tests -v
(cd nkb/viz/art && npm ci && npm run build)
node --test tests/js/*.test.cjs tests/js/*.test.mjs
python3 extensions/astrbot-love-house/package.py --check
```

官方 AstrBot 离线契约测试需要将 `ASTRBOT_OFFLINE_SOURCE` 指向固定版本的官方源码，并准备对应测试依赖。未提供源码时的跳过不能算成兼容性通过；Windows 本轮对 4.29.3 和 4.29.4 分别验证了真实配置读取与临时模型消息契约，不能据此宣称真实 QQ 或其他宿主版本已测。

在实际 Mac 原生窗口验证：向导生成的 JSON 能对齐 Mac 私有文件与唯一 UMO；状态在换库、保存失败、Keychain 锁定及重启后正确；星云缓慢左转、整画布悬停暂停、拖拽和平面切换自然，节点数据不变。真实 AstrBot 用测试机器人和测试会话完成重载、对话入库、召回、断线恢复；合成测试不能宣称真实 QQ 已验证。

Mac 构建应重新生成 Mac 包、校验文件和独立验收证据，更新按系统区分的下载说明。禁止把 Windows 构建证据当成 Mac 包验证，也不要移动已有发布标签或覆盖旧附件。继续保留作者署名、非商用许可、默认单窗口隔离与原有记忆。
