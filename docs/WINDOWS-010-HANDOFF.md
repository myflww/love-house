# Windows 后续同步：macOS 0.10.0

Mac 0.10.0/build15已完成完整包内检查、原生WKWebView检查和本机覆盖安装，现有存档及设置保留。本轮将人格形成与原版神经星图一起交付。Windows请从已经发布的Windows 0.9.1rc1原生工程继续开发，选择性移植共享功能，保留WebView2离线修复、中文路径、诊断、更新与完整导出的Windows修复。不要用Mac工程整体覆盖Windows项目。

## 需要同步的共享实现

- nkb/companion/persona.py及memory、structured、catalog、handoff：默认人格／学习开、显式opt-out保留、手动核心优先、独立formed_traits、逐字助手依据、来源版本和失效检查、移除阻止加回。新库不预填人格。
- nkb/organizer/{state,rules,model,engine}.py：普通整理同一次调用可选persona_traits；快速purpose=persona只整理人格，不重做事实或改变普通items。单条批次可补一条旧助手依据，事实不得引用。目的列为增量迁移，旧缓存普通规则版本保持兼容。
- nkb/service/host.py、sharing.py：只读人格预览、确认后一次预算排队、特征移除；新管理接口要求UI会话，来源Bearer不得越权。分享重绑有效证据与明确关闭状态；Key、连接凭据不随分享导出。
- viz/web/persona-growth-ui.js及builder、dialogue-import、memory-portability、memory-organizer：形成层优先、固定设定折叠、导入后快捷入口、强烈API建议、费用与原文无需Key说明，明确“保存并开启”。轮询／迟到响应与跨库归属保护保留。
- viz/art/approved-atlas-{painter,renderer,data}.js、neural-art.js注册入口、synapse-dynamics.js与重建bundle；index图显示部分、warm-theme：直接采用已批准隔离版绘制代码、原粒子云与纤维、弱边摆动、nebula／flat切换、节点／标签／命中／小地图共用显示坐标。累计recalls不是月频率，不将浏览计作召回。原奶油／樱花像素UI及彩色按钮保持不动，主题仅切换图画布，不对界面做灰阶或黑白反转。具体最终renderer文件与复用证明见NEURAL-ATLAS-010.md。

## 必须直接沿用已批准的星图代码

用户明确要求直接采用已经隔离制作好的代码，不允许再重画一套相似效果。两种模式共用已经抽取的原版绘制函数；docs/APPROVED-ATLAS-PROVENANCE.json和tests/fixtures/approved-neural-atlas-demo.source.txt提供原文件及函数校验。原始合成演示仅作不执行的来源归档，不能加载成用户记忆。实际绘制诊断应为approved-canvas，不是旧的shader近似层。

主题按钮只控制图画布背景、粒子、节点、纤维及图内必要对比；原顶栏、浮窗、输入框、提示、像素按钮与图标的配色／底图／字体都保持原样。旧配色按钮的操作目标改为星图黑／白，不再提供奶油／樱花切换入口。两种图模式共享同一黑白状态。不要新增动态／平面的分段按钮，只用爱之屋原有星星像素viewBtn切换，两种模式本体与布局函数保持原版。

## Windows 必须真实验证

1. 新库默认两个开关开启且固定设定为空、收起；旧库显式关闭仍关闭。导入后预览不付费，无Key无法开始，有Key未开整理时明确提示。
2. 假传输验证快速仅一次请求、不改变普通队列；普通批次同一次调用形成人格。当前库至少两条独立助手证据、跨库／工具／用户／重复副本／未来资料／更正遗忘／模型指令拒绝；手动核心保留，移除、关闭、撤回与重启持久。
3. 明确授权后用独立合成测试库完成模型验收，失败算一次预算，不自动重试，不读取AstrBot或其他软件的Key。
4. 打开、切库、导入、黑白主题、0／1／2节点、平面与星云切换、自动视距、手动视距、标签、详情、小地图和暂停；对比正式边数、节点坐标、recalls不变。Windows WebView2的GPU／字体／高DPI必须原生核验，Mac浏览器成绩不能代替。
5. 保留0.9.1rc1完整JSON／Markdown不依赖整理状态的拒绝／等待检查；安装／便携、普通用户、中文空格路径、无开发环境PATH、重启、固定窗口隔离、原有库和Key元数据均需验收。

运行：python -m unittest discover -s tests；前端开发测试先按已锁定的package-lock执行 npm ci --prefix nkb/viz/art，再运行 node --test tests/js/*.test.cjs tests/js/*.test.mjs。新的tests/test_persona_formation.py、test_persona_organizer.py、test_persona_growth_ui.py、test_neural_atlas.py及对应JS测试必须带上。Mac desktop/AtlasApp.swift新增的隔离原生检查可作为Windows场景清单，不是Windows运行代码。

## 迁移和发布要求

jobs表增加purpose列，旧版位置式INSERT不兼容新表；升级先停止写入、备份完整数据目录。回退旧Windows应用也须恢复配套升级前数据库，不能只回退EXE。

版本号、Windows构建／安装脚本由Windows维护者按实际验收更新。保留PolyForm Noncommercial 1.0.0、myflww署名及第三方许可。公开包不含真实存档、用户路径、连接配置、Key或临时验收脚本。

发布后同步Main首页README和下载与系统支持，保留Mac与手机入口；标签指向真实核验源码提交。公开下载重新校验SHA256、安装和启动后才标注完成。源码来自macOS v0.10.0标签；正式安装与模型验证范围见MACOS-010-PERSONA.md，视觉细节见NEURAL-ATLAS-010.md。
