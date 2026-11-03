# Windows 0.10.2rc1 更新与接入说明

已公开发布 Windows 0.10.2rc1 修复预览，并完成下列固定记录对应的公开下载安装复核。


本轮将用户提供的成功接入案例整理为可重复的配置流程，避免让用户猜测私有文件路径、固定宿主标识和 UMO 的对应关系。案例中的个人标识、聊天内容、真实配置及路径未纳入源码和安装包。

## 最短接入步骤

1. 在爱之屋选择这条鱼的记忆库，打开“同鱼活动来源”，选择 AstrBot。
2. 选择同机共享文件系统与活动平台。在要接入的 AstrBot 私聊或群聊执行 `/sid`，粘贴 UMO。每个会话只分给一个绑定；不要用昵称猜测标识。
3. 确认该宿主属于当前这条鱼，生成来源与插件配置。来源凭证保留在本机私有文件内；完整插件 JSON 自动填好文件路径、固定标识和会话白名单。
4. 安装导出的 0.3.0 实验插件，目录固定为 `data/plugins/astrbot_plugin_love_house`。按向导给出的 `data/config/astrbot_plugin_love_house_config.json` 路径配置插件。已有插件设置须合并绑定，避免覆盖其他记忆库。
5. 在 AstrBot 面板重载插件，在目标会话发一轮测试对话。用 `/lovehouse_status` 查看状态，并回爱之屋确认真实来源上报和新增记忆。

插件通过 AstrBot 消息生命周期钩子交接真实对话，并在请求前取回本库材料。普通 MCP 工具配置不能代替这一步。聊天模型无须“想起”主动调用保存工具。

另一台服务器或隔离容器无法直接使用 Windows 本机路径。需在对应宿主环境创建可读取的私有配置；跨机器网络保持 HTTPS 和来源鉴权。快速向导不自动修改外部宿主、不读取聊天数据库，也不会代替用户确认归属或重启机器人。

## 看懂运行状态

- 配置生成：文件已准备好，尚不能证明插件加载。
- 已上报真实活动：至少有真实钩子事件到达绑定来源；仍应核对目标库和实际新增原文。
- 持久交接并清空正文：SDK 已接管交付，插件只保留摘要；不是原文无故丢失，也不应当作远端入库回执。
- 召回候选被预算省略：提高上下文预算或减少固定身份材料；不要把 `selected>0, included=0, omitted>0` 当成没有匹配。
- 无效绑定：状态中说明是哪条序号及原因；其他有效绑定继续工作。重复 UMO 或身份冲突会拒绝，不自动选择记忆库。

诊断只显示安全原因及计数，不展示凭证、正文和完整 UMO。群聊、定时输出、外部浏览器 Agent 的覆盖范围以实际钩子为准，不能从安装成功推断全部活动已覆盖。

## 整理 API 的可见状态

库名下新增常驻整理 API 状态，整理面板顶部展示当前库服务、模型和密钥保存范围。“仅本次运行”在重启后需要重新填写；安全存储中的密钥暂不可读时会显示“密钥不可用”。外库连接、断开的连接和保存失败均不标记就绪。

状态读取、配置保存和预览不调用模型。配置成功不等于联网校验成功；厂商拒绝、余额或网络错误以之后的真实整理结果为准。原文保存和完整分享导出不受可选整理 API 阻断。

## 星云的观看方式

动态星云以约 0.035 弧度／秒水平左转。鼠标移入画布任意位置、拖拽操作或手动暂停会停止自旋，离开后继续，不补算暂停期间的角度。平面模式、切换过程、后台页面及减少动态效果停止自旋。原版画笔和节点的真实数据保持原有含义，旋转不产生关系或召回记录。

## 验证与升级

发布附件 `Windows-0102-verification.json` 固定受测源码、构建记录、安装包及插件摘要；`Windows-SHA256SUMS.txt` 校验 EXE／ZIP。独立匿名下载 CI 会核对公开文件，再运行便携和安装各自的后端、原生与普通用户环境检查。

覆盖升级验证从公开 0.10.1rc1 EXE 安装开始，以两份独立合成记忆库验证库内容、来源、设置、明确关闭的人格选择、凭据元数据和重启保留。新增原生检查验证配置向导、分库 API 状态、左转与悬停恢复，并继续执行旧版导出、人格、图形及原文保留检查。

升级前备份完整数据目录。回退旧程序时同时恢复升级前的配套数据快照。Win10 真机、缺失／损坏运行时、真实 QQ 长期运行及真实模型厂商账户不由合成测试替代。


## 本轮发布状态与固定证据

[冻结生产源码 `b1af91dba0b8f6145cf18e364cc24f0ee633b911`](https://github.com/myflww/love-house/tree/b1af91dba0b8f6145cf18e364cc24f0ee633b911)。Main 基线为 `bafc2e92566fa0a72f1d22503112eef343e56a25`；下载文档更新不表示生产分支已全部合并到 Main。

- [Windows 发布页](https://github.com/myflww/love-house/releases/tag/v0.10.2rc1)
- [EXE 安装包](https://github.com/myflww/love-house/releases/download/v0.10.2rc1/LoveHouse-Setup-0.10.2rc1-Windows-x64.exe) · [ZIP 便携包](https://github.com/myflww/love-house/releases/download/v0.10.2rc1/LoveHouse-0.10.2rc1-Windows-x64.zip)
- [Windows 校验文件](https://github.com/myflww/love-house/releases/download/v0.10.2rc1/Windows-SHA256SUMS.txt) · [本轮验证附件](https://github.com/myflww/love-house/releases/download/v0.10.2rc1/Windows-0102-verification.json)
- [Windows 构建、安装与原生检查](https://github.com/myflww/love-house/actions/runs/41337307386) · [Harness 实际宿主轮次](https://github.com/myflww/love-house/actions/runs/41337307343) · [完整回归](https://github.com/myflww/love-house/actions/runs/41337307434) · [发布及附件校验](https://github.com/myflww/love-house/actions/runs/41339292498) · [公开下载后安装与启动](https://github.com/myflww/love-house/actions/runs/41339499539)
