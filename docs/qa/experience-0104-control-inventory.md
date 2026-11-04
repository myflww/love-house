# 爱之屋 0.10.4 操作与控件清单

本清单来自公开源码的静态盘点，覆盖主模板、动态模块及原生菜单。截图、真实点击、响应式和键盘结果由本轮界面验收另行记录；静态存在不等于某个状态中可见或已经点击通过。没有读取用户资料、模型密钥或真实对话。

## 简化原则与结构决定

- 主导航：记忆、连接、整理、显示、更多；记忆库目标始终独立可见。
- 添加菜单：手动添加、笔记导入、聊天导入、完整存档导入。四者的写入/角色/建库含义不同，统一入口但保留专用预览。
- 显示菜单：视图、筛选、只读时间预览、选中详情、重排、动效、主题、全屏。放大/缩小/适应画面留在画布旁。
- 更多：备份迁移、记忆规律、更新、高级召回。扩散跳数和传播系数不再优先展示。
- 人格与整理：清除重复 API 推荐卡，保留明确模型状态；以启用开关＋保存设置统一操作。快速人格整理仍需范围预览和明确模型调用。
- 详情：纠正/停用为常用动作；原文编辑、人工强化、布局邻居归高级；永久忘记保留单独危险区、范围预览与确认。

## 容易混淆但需要保留的不同动作

| 动作 | 区别与保留理由 |
| --- | --- |
| 搜索框输入 / 关联召回 | 输入先筛选，提交执行引擎关联召回；需要文字说明与独立反馈。 |
| 定位 / 显示全图 / 返回全图 | 定位一个节点；适应当前可见集合；退出邻居/召回聚焦。不同状态，不能简单合并。 |
| 编辑 / 纠正 | 编辑修改原条目；纠正保存新事实与替代关系。默认突出纠正，原文编辑放高级并说明。 |
| 暂不使用 / 真正忘记 | 前者可恢复并保留原文；后者清除关联原文和派生，保留独立确认。 |
| 备份 / 导出分享 / 复制记忆包 | 恢复快照、可迁移完整副本、有限上下文摘录的目的和范围不同。 |
| 连接新窗口 / 导入聊天 | 前者持续接收获准窗口；后者一次性导入所选文件，不能互相冒充已接通。 |
| 自动整理 / 立即整理 / 快速人格 | 后台节奏、处理当前积压、一次人格预览任务不同，保留明确状态和调用界限。 |
| 关闭顶端× / 底部取消 | 长表单中两个同意图退出点用于减少滚动，均不自动保存；属于合理重复。 |

## 主模板控件逐项清单

共 164 个静态按钮、输入、选择及展开控件（含明确隐藏的旧兼容界面）。

| 来源 | 控件／标识 | 表面与意图 | 风险／禁用及错误规则 | 决定 | 证据范围 |
| --- | --- | --- | --- | --- | --- |
| index.html:47 | button `libraryMenuBtn` | app · 切换记忆库 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:48 | input `q` | app / searchForm · 搜索节点或输入想要召回的内容 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:48 | button `searchBtn` | app / searchForm · 关联召回 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:50 | button `companionBtn` | app · 连接与记忆 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:50 | button `addBtn` | app · 添加记忆 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:50 | button `importBtn` | app · 导入笔记 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:51 | button `menuBtn` | app · 节点列表 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:52 | button `filterBtn` | app · 筛选节点 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:53 | button `timeBtn` | app · 时间预览 | 本地只读/导航/显示；不因查看扩大授权 | 移到显示菜单或高级折叠；不删除能力 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:54 | button `detailBtn` | app · 节点详情 | 本地只读/导航/显示；不因查看扩大授权；disabled=None | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:55 | button `settingsBtn` | app · 图谱设置 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:56 | button `viewBtn` | app · 切换分析视图 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:57 | button `layoutBtn` | app · 整理布局 | 本地只读/导航/显示；不因查看扩大授权 | 移到显示菜单或高级折叠；不删除能力 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:57 | button `pauseBtn` | app · 暂停动效 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:58 | button `themeBtn` | app · 切换浅色主题 | 本地只读/导航/显示；不因查看扩大授权 | 移到显示菜单或高级折叠；不删除能力 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:58 | button `fullscreenBtn` | app · 进入全屏 | 本地只读/导航/显示；不因查看扩大授权 | 移到显示菜单或高级折叠；不删除能力 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:63 | button `closeNodes` | app / sidebar · 关闭节点列表 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:64 | button `allTab` | app / sidebar · 全部节点 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:64 | button `recallTab` | app / sidebar · 召回路径 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:68 | button `resetFilters` | app / filterPanel · 重置 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:68 | button `closeFilters` | app / filterPanel · 关闭筛选 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:69 | button `previewReset` | app / timePanel · 回到此刻 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:69 | button `closeTime` | app / timePanel · 关闭时间预览 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:69 | input `days` | app / timePanel · 只读预览未来的记忆衰减天数 | 先改草稿；实际写入依所属保存/确认动作；min=0；max=365 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:74 | button `clearFocus` | app / stage / scopeBanner · 返回全图 ↗ | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:76 | button `zoomIn` | app / stage · 放大图谱 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:76 | button `zoomOut` | app / stage · 缩小图谱 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:76 | button `fitBtn` | app / stage · 适应所有可见节点 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:78 | button `minimapBtn` | app / stage · 缩略导航 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:82 | button `emptyAction` | app / stage / emptyStage · 添加第一段记忆 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:82 | button `previewNebula` | app / stage / emptyStage · 预览星云 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:83 | button `closeSettings` | app / stage / settings · 关闭设置 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:83 | button `organizeBtn` | app / stage / settings · 记忆整理 未启用 | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:83 | button `backupBtn` | app / stage / settings · 备份与恢复 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:83 | input `steps` | app / stage / settings · 关联召回扩散跳数 | 先改草稿；实际写入依所属保存/确认动作；min=1；max=5 | 移到显示菜单或高级折叠；不删除能力 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:83 | input `damping` | app / stage / settings · 关联传播系数 | 先改草稿；实际写入依所属保存/确认动作；min=30；max=90 | 移到显示菜单或高级折叠；不删除能力 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:83 | select `labels` | app / stage / settings · 节点标签显示方式 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:83 | input `learn` | app / stage / settings · 手动关联召回时巩固记忆 | 先改草稿；实际写入依所属保存/确认动作 | 移到显示菜单或高级折叠；不删除能力 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:85 | button `closeDetail` | app / inspector · 关闭节点详情 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `closeAI` | app / legacyCompanion · 关闭AI陪伴 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `directTab` | app / legacyCompanion · API聊天 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `packetTab` | app / legacyCompanion · Harness接入 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | summary `(无ID展开/字段)` | app / legacyCompanion / aiSettings · 设置 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | input `companionName` | app / legacyCompanion / aiSettings · 她的名字 | 停用兼容界面，不作为当前操作；maxlength=80 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | input `companionUserName` | app / legacyCompanion / aiSettings · 你的称呼 | 停用兼容界面，不作为当前操作；maxlength=80 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | textarea `companionPersona` | app / legacyCompanion / aiSettings · 稳定人设 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `savePersona` | app / legacyCompanion / aiSettings · 保存人设 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | input `aiKey` | app / legacyCompanion / aiSettings · API密钥 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | input `aiModel` | app / legacyCompanion / aiSettings · 模型 | 停用兼容界面，不作为当前操作；maxlength=100 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | input `aiSession` | app / legacyCompanion / aiSettings · 当前对话 | 停用兼容界面，不作为当前操作；maxlength=200 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `newAISession` | app / legacyCompanion / aiSettings · 新对话 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | textarea `aiMessage` | app / legacyCompanion / directPanel · 你想说的话 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `sendAI` | app / legacyCompanion / directPanel · 发送 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | select `rememberKind` | app / legacyCompanion / directPanel · 记忆类型 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `rememberAI` | app / legacyCompanion / directPanel · 记住这条 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | textarea `harnessConfig` | app / legacyCompanion / harnessPanel · Harness接入配置 | 停用兼容界面，不作为当前操作；readonly=None | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `copyHarness` | app / legacyCompanion / harnessPanel · 复制接入配置 | 停用兼容界面，不作为当前操作；disabled=None | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `checkHarness` | app / legacyCompanion / harnessPanel · 记忆自检 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | summary `(无ID展开/字段)` | app / legacyCompanion / harnessPanel · 网页记忆包（备选） | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | textarea `packetQuery` | legacyCompanion / harnessPanel / packetPanel · 这次想聊什么 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `buildPacket` | legacyCompanion / harnessPanel / packetPanel · 生成记忆包 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | textarea `memoryPacket` | legacyCompanion / harnessPanel / packetPanel · 网页记忆包 | 停用兼容界面，不作为当前操作；readonly=None | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `copyPacket` | legacyCompanion / harnessPanel / packetPanel · 复制记忆包 | 停用兼容界面，不作为当前操作；disabled=None | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | summary `(无ID展开/字段)` | legacyCompanion / harnessPanel / packetPanel · 保存网页对话 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | textarea `recordUser` | legacyCompanion / harnessPanel / packetPanel · 我说的 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | textarea `recordAssistant` | legacyCompanion / harnessPanel / packetPanel · AI回复 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:86 | button `recordAI` | legacyCompanion / harnessPanel / packetPanel · 保存对话 | 停用兼容界面，不作为当前操作 | 保留隐藏兼容，不暴露重复聊天入口 | 静态源码；真实UI状态待逐流程验收 |
| index.html:87 | button `closeMemoryPanel` | app / aiPanel · 关闭连接与记忆 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:87 | button `connectTab` | app / aiPanel · 连接 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:87 | button `personaTab` | app / aiPanel · 人格 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:87 | button `activityTab` | app / aiPanel · 活动 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | summary `(无ID展开/字段)` | aiPanel / connectionsPanel / newConnectionDetails · 绑定新对话 | 本地只读/导航/显示；不因查看扩大授权 | 保留渐进展开；避免默认展示全部技术选项 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | select `connectionLibrary` | aiPanel / connectionsPanel / newConnectionDetails · 1 · 选记忆库 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | select `connectionHost` | aiPanel / connectionsPanel / newConnectionDetails · 2 · 选接入方式 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | select `providerPreset` | connectionsPanel / newConnectionDetails / providerFields · API服务 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `providerBaseUrl` | connectionsPanel / newConnectionDetails / providerFields · 上游 API 基础地址 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `providerModel` | connectionsPanel / newConnectionDetails / providerFields · 模型名称 | 先改草稿；实际写入依所属保存/确认动作；maxlength=120 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `providerKey` | connectionsPanel / newConnectionDetails / providerFields · 上游 API 密钥 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `providerSaveKey` | connectionsPanel / newConnectionDetails / providerFields · providerSaveKey | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `connectionName` | aiPanel / connectionsPanel / newConnectionDetails · 连接名称（可选） | 先改草稿；实际写入依所属保存/确认动作；maxlength=80 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | select `connectionScopeMode` | aiPanel / connectionsPanel / newConnectionDetails · 接收范围 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `connectionScope` | connectionsPanel / newConnectionDetails / connectionScopeRow · 宿主会话 ID | 先改草稿；实际写入依所属保存/确认动作；maxlength=200 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | button `detectHarnessBtn` | aiPanel / connectionsPanel / newConnectionDetails · 检测宿主 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | button `createConnectionBtn` | aiPanel / connectionsPanel / newConnectionDetails · 3 · 生成接入配置 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | summary `(无ID展开/字段)` | aiPanel / connectionsPanel / connectionConfigPanel · 查看完整配置 | 本地只读/导航/显示；不因查看扩大授权 | 保留渐进展开；避免默认展示全部技术选项 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | textarea `connectionConfig` | aiPanel / connectionsPanel / connectionConfigPanel · 宿主接入配置 | 先改草稿；实际写入依所属保存/确认动作；readonly=None | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | button `copyConnectionConfig` | aiPanel / connectionsPanel / connectionConfigPanel · 复制接入配置 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `apiBaseUrl` | connectionsPanel / connectionConfigPanel / apiBaseRow · 本地接入地址 | 先改草稿；实际写入依所属保存/确认动作；readonly=None | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | button `copyApiBase` | connectionsPanel / connectionConfigPanel / apiBaseRow · 复制地址 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | input `clientApiKey` | connectionConfigPanel / apiBaseRow / clientKeyRow · 本地接入令牌 | 先改草稿；实际写入依所属保存/确认动作；readonly=None | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | button `copyClientKey` | connectionConfigPanel / apiBaseRow / clientKeyRow · 复制令牌 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | button `planConnectionBtn` | connectionsPanel / connectionConfigPanel / configureActions · 预览改动 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | button `applyConnectionBtn` | connectionsPanel / connectionConfigPanel / configureActions · 应用接入配置 | 当前库写入；忙碌/只读/库切换时禁用；disabled=None | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:88 | summary `(无ID展开/字段)` | aiPanel / connectionsPanel / connectionConfigPanel · 修改计划 | 本地只读/导航/显示；不因查看扩大授权 | 保留渐进展开；避免默认展示全部技术选项 | 静态源码；真实UI状态待逐流程验收 |
| index.html:89 | input `personaEnabled` | app / aiPanel / personaPanel · personaEnabled | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:89 | input `personaLearning` | app / aiPanel / personaPanel · personaLearning | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:89 | textarea `personaText` | app / aiPanel / personaPanel · 粘贴或编辑人格 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:89 | button `savePersonaImport` | app / aiPanel / personaPanel · 保存人格 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:89 | button `reloadPersonaBtn` | app / aiPanel / personaPanel · 重新读取 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:90 | button `refreshActivityBtn` | app / aiPanel / activityPanel · 刷新 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:90 | button `organizerActivityBtn` | app / aiPanel / activityPanel · 记忆整理 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:91 | button `closeLibraries` | app / libraryPanel · 关闭记忆库列表 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:91 | button `newLibraryBtn` | app / libraryPanel · ＋ 新记忆库 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | button `closeOrganizer` | app / organizerPanel · 关闭记忆整理 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | button `previewOrganizer` | app / organizerPanel · 预览批次 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | button `runOrganizer` | app / organizerPanel · 立即整理 | 明确调用模型；需本库有效模型及启用条件 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | summary `(无ID展开/字段)` | app / organizerPanel / organizerSettings · 整理设置 | 本地只读/导航/显示；不因查看扩大授权 | 保留渐进展开；避免默认展示全部技术选项 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | input `organizerEnabled` | app / organizerPanel / organizerSettings · organizerEnabled | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | select `organizerMode` | app / organizerPanel / organizerSettings · 整理模型 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | select `organizerConnection` | organizerPanel / organizerSettings / organizerConnectionRow · 使用哪个模型连接 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | select `organizerProviderPreset` | organizerPanel / organizerSettings / organizerSeparate · API服务 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | input `organizerProviderBaseUrl` | organizerPanel / organizerSettings / organizerSeparate · 上游 API 基础地址 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | input `organizerProviderModel` | organizerPanel / organizerSettings / organizerSeparate · 模型名称 | 先改草稿；实际写入依所属保存/确认动作；maxlength=120 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | input `organizerProviderKey` | organizerPanel / organizerSettings / organizerSeparate · 整理模型密钥 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | input `organizerProviderSaveKey` | organizerPanel / organizerSettings / organizerSeparate · organizerProviderSaveKey | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | select `organizerCadence` | app / organizerPanel / organizerSettings · 整理节奏 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | input `organizerBatchSize` | app / organizerPanel / organizerSettings · 每批条数 | 先改草稿；实际写入依所属保存/确认动作；min=1；max=12 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:92 | button `saveOrganizerSettings` | app / organizerPanel / organizerSettings · 保存整理设置 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| index.html:93 | button `closeBackups` | app / backupPanel · 关闭备份与恢复 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:93 | button `createBackup` | app / backupPanel · 创建备份 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | button `cancelAdd` | addDialog / addForm · 关闭添加记忆 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | input `newLabel` | addDialog / addForm · 记忆名称 | 先改草稿；实际写入依所属保存/确认动作；required=None；maxlength=300 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | textarea `newText` | addDialog / addForm · 完整内容 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | select `newKind` | addDialog / addForm · 类型 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | input `newImpact` | addDialog / addForm · 情绪冲击（−1—1） | 先改草稿；实际写入依所属保存/确认动作；min=-1；max=1 | 移到显示菜单或高级折叠；不删除能力 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | input `newSession` | addDialog / addForm · 会话标识（可选） | 先改草稿；实际写入依所属保存/确认动作；maxlength=200 | 移到显示菜单或高级折叠；不删除能力 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | input `newEventAt` | addDialog / addForm · 事件发生时间 | 先改草稿；实际写入依所属保存/确认动作 | 移到显示菜单或高级折叠；不删除能力 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | input `newImportant` | addDialog / addForm · newImportant | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | input `newTags` | addDialog / addForm · 标签（逗号分隔） | 先改草稿；实际写入依所属保存/确认动作 | 移到显示菜单或高级折叠；不删除能力 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | button `cancelAddBottom` | addDialog / addForm · 取消 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:97 | button `saveAdd` | addDialog / addForm · 保存记忆 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | button `closeImport` | importDialog · 关闭笔记导入 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | input `importFiles` | importDialog · 选择笔记文件（可多选） | 先改草稿；实际写入依所属保存/确认动作；accept=.md,.markdown,.txt,.rst | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | input `pasteName` | importDialog · 或粘贴文本 · 笔记名称 | 先改草稿；实际写入依所属保存/确认动作；maxlength=200 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | textarea `pasteText` | importDialog · 笔记正文 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | select `importMode` | importDialog · 内容拆分 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | button `cancelImport` | importDialog · 取消 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | button `previewImport` | importDialog · 预览条目 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:98 | button `confirmImport` | importDialog · 确认导入 | 当前库写入；忙碌/只读/库切换时禁用；disabled=None | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:99 | button `cancelLibrary` | newLibraryDialog / newLibraryForm · 关闭新建记忆库 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:99 | input `newLibraryName` | newLibraryDialog / newLibraryForm · 名称 | 先改草稿；实际写入依所属保存/确认动作；required=None；maxlength=80 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:99 | button `confirmLibrary` | newLibraryDialog / newLibraryForm · 创建空白库 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:100 | button `cancelDisconnect` | disconnectDialog · 取消 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:100 | button `confirmDisconnect` | disconnectDialog · 确认断开 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:101 | button `closeRawActivity` | rawActivityDialog · 关闭原始记录 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:102 | button `cancelProvider` | providerDialog / providerForm · 关闭模型设置 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:102 | select `editProviderPreset` | providerDialog / providerForm · API服务 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:102 | input `editProviderBaseUrl` | providerDialog / providerForm · 上游 API 基础地址 | 先改草稿；实际写入依所属保存/确认动作；required=None | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:102 | input `editProviderModel` | providerDialog / providerForm · 模型名称 | 先改草稿；实际写入依所属保存/确认动作；required=None；maxlength=120 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:102 | input `editProviderKey` | providerDialog / providerForm · 上游 API 密钥 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:102 | input `editProviderSaveKey` | providerDialog / providerForm · editProviderSaveKey | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:102 | button `saveProvider` | providerDialog / providerForm · 保存模型设置 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:103 | button `closeOrganizerPreview` | organizerPreviewDialog · 关闭整理预览 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:104 | button `cancelForgetMemory` | forgetMemoryDialog · 关闭忘记确认 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:104 | input `confirmForgetCheck` | forgetMemoryDialog · confirmForgetCheck | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:104 | button `cancelForgetBottom` | forgetMemoryDialog · 取消 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:104 | button `confirmForgetMemory` | forgetMemoryDialog · 确认永久忘记 | 影响范围预览后写入；隐私清除保留独立确认；disabled=None | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:105 | button `cancelRestoreBackup` | restoreBackupDialog · 关闭恢复确认 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:105 | input `restoredLibraryName` | restoreBackupDialog · 新库名称（可选） | 先改草稿；实际写入依所属保存/确认动作；maxlength=80 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:105 | button `confirmRestoreBackup` | restoreBackupDialog · 确认恢复新Agent | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:106 | button `cancelCorrectMemory` | correctMemoryDialog / correctMemoryForm · 关闭纠正内容 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:106 | input `correctMemoryLabel` | correctMemoryDialog / correctMemoryForm · 名称（可选） | 先改草稿；实际写入依所属保存/确认动作；maxlength=100 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:106 | textarea `correctMemoryText` | correctMemoryDialog / correctMemoryForm · 正确内容 | 先改草稿；实际写入依所属保存/确认动作 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| index.html:106 | button `confirmCorrectMemory` | correctMemoryDialog / correctMemoryForm · 保存纠正 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |

## 动态模块按钮与生成族

共 112 项可静态定位的按钮或生成族。同一族可以按连接、记忆、候选、人格特征等记录生成多行；不同状态的完整文案与作用范围仍需在隔离环境点击验收。

| 来源／处理器位置 | 标识或生成族 | 意图／文案 | 风险／禁用及错误规则 | 决定 | 证据范围 |
| --- | --- | --- | --- | --- | --- |
| agent-sources-ui.js:11 | `agentSourcesBtn` | 同鱼活动来源 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:14 | `closeAgentSources` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:17 | `copyAgentSourcePath` | 复制配置路径 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:39 | `copyAstrbotSetup` | 复制插件配置 JSON | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:40 | `generateAstrbotSetup` | 为此来源生成插件配置 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:43 | `createAgentSource` | 生成来源与插件配置 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:44 | `exportAstrBotPlugin` | 导出 AstrBot 实验插件 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:50 | `refreshAgentSources` | 刷新状态 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:50 | `addHarnessSource` | 连接 Harness 窗口 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| agent-sources-ui.js:10 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-help-ui.js:16 | `closeConnectionHelp` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-help-ui.js:22 | `connectionHelpRoute-` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:17 | `startConnectionWizard` | 连接一条大肥鱼 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:19 | `closeConnectionWizard` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:25 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:27 | `connectionAstrBotChoice` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:28 | `connectionWorkBuddyChoice` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:71 | `connectionWizardBack` | 上一步 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:71 | `connectionWizardNext` | 下一步 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:160 | `copyAgentSetup` | 复制给配置助手 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:160 | `copyAgentMcp` | 复制 MCP 配置 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:163 | `copyAgentConfigPath` | 复制配置路径 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:169 | `fixConnectionModel` | 模型与密钥 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:170 | `connectHarnessNow` | 备份配置并连接 Harness | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:170 | `connectWorkBuddyNow` | 预览 WorkBuddy 配置 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:170 | `verifyChatConnection` | 检查是否收到对话 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:170 | `openConnectionLibrary` | 打开保存的记忆库 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:178 | `applyWorkBuddyConfig` | 备份并合并到 WorkBuddy | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:201 | `cancelConnectionRebind` | 取消 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| connection-ux.js:201 | `confirmConnectionRebind` | 换发配置并等待新窗口 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| dialogue-import-ui.js:12 | `closeDialogueImport` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| dialogue-import-ui.js:22 | `cancelDialogueImport` | 取消 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| dialogue-import-ui.js:22 | `previewDialogueImport` | 预览记录 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| dialogue-import-ui.js:22 | `applyDialogueImport` | 确认导入 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| dialogue-import-ui.js:25 | `dialogueImportBtn` | ▤ | 本地只读/导航/显示；不因查看扩大授权 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| dialogue-import-ui.js:26 | `dialogueImportFromNotes` | 导入聊天记录 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| dialogue-import-ui.js:9 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:12 | `experienceLibraryBtn` | 她的经历 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:13 | `experienceOrganizerBtn` | 她的经历 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:18 | `closeExperienceTimeline` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:25 | `refreshExperienceTimeline` | 刷新经历 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:26 | `moreExperienceTimeline` | 再看一些 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:27 | `continueExperienceOrganization` | 继续整理 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:28 | `experienceSourcesBtn` | 活动来源 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:29 | `experienceAllNodesBtn` | 在列表中搜索 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| experience-ui.js:11 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:12 | `closeLibraryDelete` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:15 | `cancelLibraryDelete` | 取消 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:15 | `confirmLibraryDelete` | 确认移入回收站 | 影响范围预览后写入；隐私清除保留独立确认 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:16 | `closeLibraryTrash` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:17 | `refreshLibraryTrash` | 刷新列表 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:17 | `doneLibraryTrash` | 完成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:19 | `openLibraryTrash` | 回收站 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:57 | `(逐条动态按钮)` | 恢复并打开 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:67 | `(逐条动态按钮)` | 删除 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| library-manager-ui.js:10 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:18 | `organizerLibraryApiStatus` | 整理API · 状态待确认 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:104 | `openMachineMemoryPreview` | AI记忆格式预览 | 本地只读/导航/显示；不因查看扩大授权 | 移到显示菜单或高级折叠；不删除能力 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:104 | `openDuplicateRecordings` | 重复来源审阅 | 本地只读/导航/显示；不因查看扩大授权 | 移到显示菜单或高级折叠；不删除能力 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:105 | `duplicateRecordingSettingsBtn` | 重复来源 | 本地只读/导航/显示；不因查看扩大授权 | 移到显示菜单或高级折叠；不删除能力 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:110 | `readMachineMemoryPreview` | 读取本次记忆材料 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:110 | `copyMachineMemoryJSON` | 复制机器JSON | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:128 | `refreshDuplicateRecordings` | 刷新来源 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:128 | `reconcileDuplicateRecordings` | 检查明确重复 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-organizer-ui.js:11 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:14 | `inheritWithAgent` | 复制给其他 Agent | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:15 | `inheritWithHarness` | 连接 Harness 新窗口 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:24 | `downloadMemoryJSON` | 保存完整分享包 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:25 | `downloadMemoryMarkdown` | 保存阅读文件 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:29 | `generateShareSummary` | 生成阅读索引 | 明确调用模型；需本库有效模型及启用条件 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:29 | `configureShareModel` | 设置整理模型 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:31 | `refreshMemoryShare` | 刷新范围 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:69 | `confirmMemoryShareImport` | 创建独立新存档 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:73 | `inheritLibraryBtn` | 连接新窗口 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:73 | `shareLibraryBtn` | 导出分享 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:73 | `importMemoryShareBtn` | 导入分享包 | 个人资料复制/导出；保留目标与必要同意 | 统一文字导航/添加/显示菜单；保留原节点与handler | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| memory-portability-ui.js:74 | `backupShareEntry` | 导出当前存档 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:74 | `backupImportEntry` | 导入分享包 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| memory-portability-ui.js:11 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| organizer-model-ui.js:9 | `organizerReadModels` | 读取可用模型 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| organizer-rules-ui.js:8 | `organizerRulesBtn` | 整理准则 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| organizer-rules-ui.js:10 | `(动态:close)` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:31 | `saveAndEnableOrganizer` | 保存并开启自动整理 | 当前库写入；忙碌/只读/库切换时禁用 | 兼容ID保留隐藏；统一启用开关＋保存设置 | 静态源码＋workspace-shell DOM回归；像素/滚动仍需真实UI |
| persona-growth-ui.js:35 | `quickOrganizePersona` | 快速整理人格 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:36 | `personaOrganizerSettings` | 整理 API 设置 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:36 | `personaFormationProgress` | 整理进度 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:84 | `(逐条动态按钮)` | 查看来源记忆 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:112 | `closePersonaFormation` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:117 | `confirmPersonaFormation` | 开始整理人格 | 明确调用模型；需本库有效模型及启用条件 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:117 | `configurePersonaFormationAPI` | 配置整理 API | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:117 | `openPersonaLearningSettings` | 查看人格开关 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:117 | `refreshPersonaFormation` | 重新预览 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:158 | `dismissPersonaImportPrompt` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:160 | `organizeImportedPersona` | 快速整理人格 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:160 | `configureImportedPersonaAPI` | 配置整理 API | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| persona-growth-ui.js:11 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| retention-ui.js:13 | `memoryRetentionBtn` | 记忆规律 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| retention-ui.js:18 | `closeMemoryRetention` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| retention-ui.js:31 | `reloadMemoryRetention` | 重新读取 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| retention-ui.js:31 | `cancelMemoryRetention` | 关闭 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| retention-ui.js:31 | `saveMemoryRetention` | 保存规律 | 当前库写入；忙碌/只读/库切换时禁用 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| retention-ui.js:12 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| update-checker-ui.js:14 | `checkForUpdates` | 检查更新 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| update-checker-ui.js:20 | `closeUpdateAvailable` | 关闭 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| update-checker-ui.js:23 | `deferUpdateAvailable` | 稍后 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| window-handoff-ui.js:9 | `windowHandoffBtn` | 复制新窗口记忆包 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| window-handoff-ui.js:12 | `(动态:close)` | × | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| window-handoff-ui.js:15 | `(动态:b)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| window-handoff-ui.js:19 | `copyWindowHandoff` | 复制记忆包 | 个人资料复制/导出；保留目标与必要同意 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| window-handoff-ui.js:19 | `(动态:connect)` | 连接新窗口 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| workspace-shell.js:105 | `(动态:trigger)` | 按状态/记录生成 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |
| workspace-shell.js:110 | `(动态:close)` | 关闭 | 本地只读/导航/显示；不因查看扩大授权 | 保留；同一意图共用现有业务处理 | 静态源码；真实UI状态待逐流程验收 |

## 动态记录族的额外验收要求

- 节点/邻居行：名称安全渲染、选择当前库节点、列表与画布选择一致、已隐藏/忘记资料不复现。
- 连接卡：继续配置、暂停/恢复、断开、改模型、换绑窗口；只能作用选中的连接，查看库不会改写归属。
- 来源卡：按真实宿主固定标识与会话登记；撤销/配置导出不得凭昵称猜身份。
- 整理批次：查看原文、重试；候选采用/拒绝；重复来源折叠/取消；不把重复发生的事件当同轮。
- 人格候选/形成特征：原话依据、采用/拒绝、移除与回滚；尊重人格和学习开关，删除不自动复活。
- 备份/回收站：预览恢复、新身份恢复、撤销库删除；失败保留已有库及备份，不自动连接。
- 经历卡：原文依据、定位、刷新、更多；原因与结果不足时保留未知，显示数量不冒充全库。

## 本轮新增导航与交互回归

| 控件或操作族 | 作用与兼容性 | 已有证据 | 待补证据 |
| --- | --- | --- | --- |
| `workspaceDisplayButton` / `workspaceDisplayMenu` | 汇总原显示动作，实际移动原节点，不复制handler | DOM：互斥开关、Esc、外部点击、disabled不执行、焦点返回 | 320/474/820/1280实际截图、Tab顺序 |
| `workspaceAddButton` / `workspaceAddMenu` | 统一手动添加/笔记/聊天/完整存档导入；类型与预览分别保留 | DOM：原ID唯一、节点与onclick恒等、原动作仅执行一次 | 实际选文件、取消与完成后的焦点 |
| `workspaceRecallAdvanced` / `workspaceGraphAbout` | 数学参数与资源说明渐进展开 | DOM：字段移动后仍可访问原节点；不保存或调用API | 键盘展开及窄屏滚动 |
| `workspaceMemoryAdvanced` | 添加表单的情绪、时间、来源及标签折叠为可选项 | 原输入与表单保留，提交handler不变 | 完整表单保存/错误/取消实际流程 |
| 原 `saveOrganizerSettings` / `saveAndEnableOrganizer` | 一个保存主动作；启用checkbox决定状态；旧save-enable ID隐藏兼容 | DOM：单主保存、初始化未触发写入；原organizer配置回归通过 | UI勾选/保存/重新读取与错误状态 |
| `.workspace-detail-advanced` / `.workspace-detail-danger` | 编辑/强化/定位与常用纠正停用区分；永久忘记仍独立预览确认 | DOM：原处理器保留、危险区默认收起、同节点重绘保留展开、换节点重置 | 真实更正/停用/忘记预览、无障碍焦点 |
| `personaOrganizerSettings` 等模型设置入口 | 不再跳焦点到密钥输入框；标题与整体状态可见 | 导航只读；异步页内转跳仍由原业务处理 | 实际滚动、标题焦点、跨库旧响应 |

已执行回归：workspace-shell 7项DOM用例、button-hints 7项DOM用例；experience、persona-growth、organizer-configuration 等原UI逻辑回归，以及可视化装配/分享/模型UI的Python回归通过。上述回归验证作用与状态，不冒充所有控件已在真实系统点击。

## 经历与记忆统一窗口新增控件

这批控件复用原 `experienceTimelineDialog`。“DOM”表示执行生产模块与真实更正提交处理器的隔离回归，不替代原生窗口实测。打开、刷新、切换标签和查看来源不会调用模型或扩大窗口范围。

| 标识或生成族 | 意图与必要性 | 写入和状态边界 | 现有证据 |
| --- | --- | --- | --- |
| `memoryWorkspaceTab-experiences` | 保留原经历、原话原因和结果卡 | 只读；不足的原因和结果仍未知 | 原经历14项DOM与统一窗口切换 |
| `memoryWorkspaceTab-commitments` | 约定及结清历史 | 默认待跟进，已完成和取消单独查看 | 分页与显式状态更新DOM |
| `memoryWorkspaceTab-connections` | 窗口、库及来源/归档/整理/提供阶段 | 只称已提供；零命中明确显示；回执故障局部提示 | 范围、零命中、侧表故障DOM |
| `memoryWorkspaceTab-corrections` | 本人纠正与平台发言待核对 | 不自动选目标或改写事实 | 一手原话、外部认领、不自动写入DOM |
| `connectionMemoryWorkspaceBtn` | 从连接页进入统一窗口 | 上下文快捷入口，不再增加顶部图标 | 调用同一公开open函数 |
| `memoryCommitmentFilter` | 待跟进、已完成或取消筛选 | 只读，不会重新启用约定 | 分页与选库请求DOM |
| `memoryCommitmentQuery` / `searchMemoryCommitments` | 按名称或内容查找约定 | 先改草稿，提交才读取 | 实际模块与API选库参数 |
| `refreshMemoryWorkspace` / `moreMemoryWorkspace` | 刷新视图、读取下一页 | cursor与当前库和筛选绑定 | 下一页、旧响应、关闭后响应DOM |
| `viewTimeline-{id}` | 查看当前库原条目 | 只读定位；未载入时明确提示 | 原节点定位公共路径 |
| `completeCommitment-{id}` | 用户确认完成 | POST done，保留历史，不发消息 | 点击前无写入、完成后默认列表移除DOM |
| `cancelCommitment-{id}` | 用户不再跟进 | POST cancelled，保留历史且可重开 | 同一状态服务与后端约定验收 |
| `reopenCommitment-{id}` | 用户重新跟进 | POST open，不安排消息 | 同一状态服务和owner guard |
| `confirmHelpful-{connection}-{memory}` | 用户确认某条资料有帮助 | 固定本次delivery和窗口；强化关闭时保留错误 | 明确请求、拒绝可见、去重状态DOM |
| `correctionTarget-{candidate}` | 选择要更正的旧资料 | 一手来源限定候选；外部来源认领后手选 | 默认不选、选定后才启用下一步DOM |
| `claimCorrectionSource-{candidate}` | 用户认领平台里的本人更正 | 仅显式动作传self-confirmed标记 | 外部默认不可改、认领和空白事实编辑DOM |
| `manualCorrectionQuery-{candidate}` | 认领后查找本库旧事实 | 只选当前可用事实/偏好/约定；50项仅为匹配展示数量 | 生产模块手选范围DOM |
| `reviewCorrection-{candidate}` | 核对旧条目并打开原更正表单 | 正确事实初始留空，由用户编辑确认 | 实际openMemoryCorrection执行DOM |
| `viewCorrectionSource-{candidate}` | 查看原始发言来源 | 只定位当前库资料，文本不执行 | 未信任标记安全渲染DOM |
| `correctMemoryNotice` | 来源、保存和独立核验状态 | 保存失败、核验失败、图谱刷新失败分别显示 | 实际submit的成功、失败、旧owner、矛盾核验DOM |
| `memoryCorrectionVerifiedAt` / `memoryCorrectionVerificationState` | 核验记录时间和当前状态投影 | 停用、更正、遗忘、失效或未载入时不把旧成功当现状；历史折叠；不自动核验 | 状态变化、恢复后仍需重验、核验中变化三项DOM |
| `memoryCorrectionVerifyQuery` | 按原主题重验 | 改问题不改已保存事实 | 初始使用旧标题，避免只用新正文自证 |
| `verifyLatestCorrection` | 独立重验新旧资料选择 | 只读POST，不再保存更正，不证明模型采用 | 失败可重试、解除忙碌后恢复按钮DOM |

新增 `memory-workspace.test.cjs` 16项通过，整理的待处理、实际运行和等待重试分别显示；连同导航、原经历、人格、整理配置、提示组件、普通记事和空闲回顾共91项JS回归通过。连接卡的五阶段概览保持紧凑，详细流程与最近提供条目默认折叠；具名操作不自动弹出鼠标提示，复杂图标与禁用原因仍有帮助。约定变更保留明确回执并还焦到状态筛选；任意原生对话框打开时，页面全局快捷键不操作背景，单次 Escape 交由对话框取消与还焦处理。真实系统的文件交互、画面尺寸、完整点击与键盘流程由本轮界面验收记录补足。

## 整理面板的空闲回顾与普通记事

`idle-review-ui.js` 在原整理面板中增加默认折叠的区域，复用原整理模型，不增加顶部入口、对话框或第二套密钥。这里的 DOM 证据执行生产模块；真实模型结果和原生系统操作须分别验收。

| 标识或生成族 | 意图与必要性 | 写入和状态边界 | 现有证据 |
| --- | --- | --- | --- |
| `idleReviewSection` | 在整理流程内查看回顾状态 | 默认折叠；展开仅 GET；关闭和换库丢弃旧响应 | 默认不读取、库/epoch/关闭旧响应DOM |
| `idleReviewEnabled` | 用户选择空闲自动回顾 | 默认关闭；勾选不直接写入，需保存 | 未保存草稿与轮询保留DOM |
| `idleReviewAdvanced` | 按需调整调度 | 空闲秒数及每批来源数；分批并非容量或每日额度 | 与服务校验范围同步、无每日预算输入 |
| `saveIdleReviewSettings` | 保存本库回顾设置 | 管理权限、示例只读、busy互斥；不立即运行模型 | 显式请求、禁用和输入错误DOM |
| `previewIdleReview` | 只读预览覆盖进度和提案 | 必须有只读、未调用模型回执；不启用或强化 | 实际请求、伪回执拒绝DOM |
| `moreIdleReviewProposals` | 继续查看后续提案 | 同库只读GET；失效分页重新第一页；无库存数量上限 | 真实api helper、追加去重、展开保持、分页变化和断网DOM |
| `runIdleReview` | 用户明确启动后台回顾 | queued回执后仅GET状态；自动开关不因此打开 | 点击前无调用、queued与只读轮询DOM |
| `idleReviewCounts` / `idleReviewStatus` | 合格、待处理、已处理、提案和错误 | 故障不冒充完成；已确认操作与刷新失败区分 | 错误、空库存、busy及刷新失败DOM |
| `idleReview-accept-{id}` | 采纳低优先经验材料 | 仅待审反思；不是用户事实或真实经历；效果未验证 | reflection可采纳，simulation/strategy无入口DOM |
| `idleReview-reject-{id}` | 拒绝待审提案 | 明确管理动作；回执须对应本库和所选提案 | busy不称成功、错误回执及显式请求DOM |
| `idleReview-rollback-{id}` | 撤回已采纳反思 | 仅停用；不能恢复已遗忘原文 | 采纳→刷新→撤回及请求内容DOM |
| `viewIdleReviewSource-{proposal}-{id}` | 按需查看原始证据 | 只定位本库仍有效条目；证据文本不执行 | 标记安全显示、失效来源可见错误DOM |
| `newKind` / `openAdd` | 普通记事默认经历 | 新建表单设episode；高级仍可选concept；既有节点和保护核心不变 | 实际openAdd及submit三项DOM |
| `newMemoryAdvancedNote` | 会话/情感说明随高级字段展开 | 主说明先呈现目标记忆库与普通记事规律 | source与导航DOM；实际尺寸由系统验收补足 |

空闲回顾20项专项DOM通过，普通记事3项实际处理器回归通过。未保存的回顾设置在读取状态或审阅提案时保留；操作回执不完整或刷新失败时须重新只读预览，避免重复写入。显式操作busy失焦后仅在同库同epoch、区域仍开且用户没有转移焦点时还焦；自动读取不请求焦点，完成后已禁用或消失的控件接续到可见按钮。服务自己的来源核验、授权事务、后台恢复及API模型行为由后端专项验收，不能以这些UI测试替代。

## 原生窗口与平台操作

| 平台/入口 | 处理器 | 取舍与验收 |
| --- | --- | --- |
| macOS 关于爱之屋 | `AtlasApp.swift` → `orderFrontStandardAboutPanel` | 保留平台惯例。 |
| macOS 检查更新 | `checkForUpdates` | 与页面更新复用同一服务；菜单属于合理平台快捷入口。 |
| macOS 退出 | `terminate` | 保留；退出后后端停止、写入队列处理与清理分别核验。 |
| macOS 编辑菜单 | undo/redo/cut/copy/paste/selectAll | 保留标准键盘编辑行为，不能把粘贴内容当指令执行。 |
| macOS 刷新图谱 | `refreshView` | 保留原生快捷入口，当前库刷新不改连接。 |
| macOS 返回全图 | `fitGraph` | 与画布适应动作复用，是平台快捷方式。 |
| macOS 打开知识库文件夹 | `openData` | 保留高级诊断入口，不能自动分享目录。 |
| macOS 最小化/缩放 | `miniaturize`/`zoom` | 保留窗口惯例。 |
| Windows 标准标题栏 | 最小化/最大化/关闭 | 保留平台惯例；独立检查关闭后服务清理。 |
| 两端导入/保存文件对话框 | 原生选取/保存回调 | 只使用用户所选路径；取消无写入；导出结果不能仅凭点击声称成功。 |
| 启动失败重新启动/运行日志 | 原生故障视图 | 保留恢复能力；日志与设置错误区别显示，不能出现假成功。 |

## 状态与可访问性验收矩阵

每个可写流程至少核对：正常、空库、示例只读库、离线快照、服务不可用、处理中、输入错误、取消、跨库切换后的旧响应、键盘 Tab/Enter/Escape、320/474/820/1280 像素窗口，以及系统减少动态效果。模型配置额外核对凭据不回显、未知能力保持服务默认、草稿/保存/启用状态分离。

本清单不把静态扫描等同于全系统无障碍认证；真实厂商账户、真实 QQ 长期运行及操作系统文件授权需分别记录实测范围。
