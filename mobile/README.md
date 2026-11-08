# Android 移动端

新版 0.10.6rc1 正在接入与桌面同版本的完整记忆引擎，并完成原签名与覆盖升级验收；当前公开发行 APK 仍为 0.8.0rc2。新版原生壳通过 Chaquopy 内置 Python 3.12，在应用私有目录运行 `MemoryHost`，模型凭据适配 Android Keystore。完整记忆界面与旧版离线视图并存，旧库仅在用户明确选择后迁移，不删除原库。版本、架构、签名进度与运行边界见 [Android 0.10.6 更新说明](../docs/ANDROID-0106-UPDATE.md)。

手机本机完整引擎提供共享核心的整理、人格、召回、更正历史、独立库与神经星图。服务仅监听 `127.0.0.1`，不默认暴露到局域网或公网。手机不能因生成配置就读取其他 App；持续记录需要实际 Agent 宿主上报。关闭完整界面或进程、系统省电可能停止手机接收，不作为全天候后台服务承诺。

电脑或云服务器上的 Agent 应连接运行在对应设备的爱之屋服务，手机通过用户主动填写的 HTTPS 地址管理那台服务的存档。远端页面使用系统浏览器，不取得本机 IndexedDB 或原生文件桥；打开远端服务也不会自动上传本机库。通用远程配置适用于支持 HTTP MCP 和自定义 Authorization header 的私有 Agent 客户端；OAuth-only 托管平台需要专用授权适配。配置说明见 [私人远程记忆服务](../docs/PRIVATE-REMOTE-MEMORY.md)。

Android APK 的覆盖升级必须使用原发行签名。当前发行下载及本机功能范围见[手机版安装与使用](../docs/手机版安装与使用.md)，以对应安装包的验证记录为准。Android 28/36 的模拟器结果不代表所有实体手机已验收。

## 本机离线存档模式

移动版与桌面版共用单库分享 JSON 格式，界面和记忆保存在设备本地。`web/` 提供 Android 本机离线视图；其静态预览不包含桌面后端、账号、云同步或模型调用。

本机离线模式支持：

- 多个独立记忆库，手动记录原文、回复与标签。
- 编辑、删除、关键词检索和标签关联星图。
- 桌面单库分享 JSON 导入、JSON 备份与 Markdown 阅读导出。
- IndexedDB 原子保存，关闭后继续使用；浏览器版本首次加载完成后可离线打开。

此处 `web/` 仍是保留旧库的简化视图，其标签星图最多显示 80 个节点，全部记录仍可搜索和导出；它与新版完整引擎页面不是同一个管理入口。新版桌面或完整引擎导出的库应在“完整记忆”中导入，旧离线视图不支持所有新配置（例如时间保留模式的 `max_nodes:null`），不能作为新版全量格式的导入入口。导入不会执行文件里的连接、密钥或模型配置。“迁移当前旧库”由明确的用户操作将所选离线库转为脱敏分享格式导入本机完整引擎，原 IndexedDB 保留，新旧库不会自动双向合并。

Android 原生壳位于 `../android/`。新版增加互联网权限用于本机引擎、模型 API 和更新检查；网络策略只允许 `127.0.0.1` 使用 HTTP，远端服务与模型 API 使用 HTTPS。没有跨 App 采集、录音、相机、无障碍或广泛存储权限。系统文件选择器用于用户主动导入与备份。卸载 APK 或清除应用数据会删除本机记忆，升级前请导出 JSON；只有相同包名与原发行签名的覆盖安装才能保留旧数据。

项目已停止提供 iPhone 版，不再发布其安装入口或运行专用发布工作流。旧主屏幕版用户请先按[迁移说明](../docs/手机版安装与使用.md#旧-iphone-版的记忆迁移)从原应用导出 JSON；保留原应用及网站数据，直至备份和导入均已核对。此变更不会远程删除已有设备上的存档。

本机移动视图已验证 360px 布局、IndexedDB 关闭后恢复、实际 JSON 下载和重新导入；停止本地测试服务器后，仍能重新加载、读取、编辑和导出合成记忆。浏览器验证不等于 Android 真机测试。

## 本地开发

用 Python 3 启动静态预览：

```sh
python -m http.server 8301 --bind 127.0.0.1 --directory mobile/web
```

服务工作线程需要 HTTPS 或本机 localhost 安全来源。通过局域网 HTTP 打开的页面不能验证离线安装能力。正式部署须把根目录的 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 一并复制到网页目录；字体许可位于 `web/assets/ark-pixel-OFL.txt`。

存储和实际桌面格式互通检查：

```sh
node --test mobile/tests/store.test.mjs
python mobile/tests/test_desktop_interop.py -v
```

## Android 构建

新版需要 JDK 17、Gradle 8.13、Android SDK 36 / Build-Tools 36.0.0、Chaquopy 17.2.0 及可用于构建的 Python 3.12；本轮 Android 实际 Python 运行时为 3.12.15。默认最低 Android 8.0（API 26），仅打包 `arm64-v8a` 和 `x86_64`；请保持 Android System WebView 更新。最终以构建脚本中固定的依赖版本和实际构建证据为准。

```sh
python scripts/prepare_mobile_assets.py
python scripts/prepare_android_engine.py
gradle -p android :app:assembleDebug :app:assembleDebugAndroidTest :app:assembleRelease :app:lintRelease
gradle -p android :app:connectedDebugAndroidTest
python scripts/check_android_test_results.py
```

可把 `LOVE_HOUSE_BUILD_PYTHON` 设为正常 Python 3.12 的完整路径；不要使用桌面安装包内部的 Python 开发构建。资源准备仅打包审查通过的共享核心和静态文件，不复制个人库、模型 Key 或机器路径。`assembleRelease` 只生成未签名开发产物，不能当作可安装下载包。发行 APK 必须在持有仓库外原发行私钥的电脑签名，再验证该签名文件的安装与回归。任何私钥、签名口令、真实记忆和本地 SDK 路径都不应进入仓库、网站或 CI 产物。

项目继续采用 PolyForm Noncommercial 1.0.0，保留 myflww 作者署名和第三方许可。
