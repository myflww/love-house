# 0.10：直接采用已批准的隔离星云代码

动态星云和平面引力图直接复用已经批准的隔离演示代码。本次不再使用先前的 Three.js 丝带近似画法；实际注册为 `createApprovedAtlasRenderer(NeuralArt)`，由 Canvas 2D 执行原绘制函数。Three.js 仅保留产品已有相机数学与 OrbitControls 输入。

## 原代码与可独立核验的证明

未执行的完整原文件归档在 `tests/fixtures/approved-neural-atlas-demo.source.txt`，共 29,023 字节，SHA-256 为 `dd31e23f5834b83bdf0c1b881bf2302852747d927834b326a9014fc2b9740090`。它只用于核验，不在运行时加载，也不注册成真实记忆库。

`approved-atlas-painter.js` 逐字包含原来的九个函数块：`edgeStyle`、`curveFor`、`pointAt`、`path`、`drawFlatGuide`、`drawCloud`、`drawEdges`、`drawNodes`、`drawPulses`。原有 950/38 粒子分布、贝塞尔连线、伴随细纤维、沿线装饰粒子、核心和卫星、平面引力环均沿用原代码。

`approved-atlas-data.js` 逐字保留原 `flatPosition()` 与星云节点位置语句、原六组锚点。真实类别、真实 ID 和实际关联拓扑只负责映射原代码的输入索引；显示位置不会再被旧力导向布局覆盖。

`docs/APPROVED-ATLAS-PROVENANCE.json` 记录原文件和各函数的 SHA-256、逐字相同结论及适配边界。公开克隆中的 `tests/js/approved-atlas-painter.test.mjs` 从仓库内归档重新核对原文件和函数，不依赖开发者电脑或父目录输出。

## 最小接入范围

- 实际记忆 ID 对应内部绘制索引；只有真实关联才形成神经线。装饰粒子不是新增记忆。
- `effective_w` 为主要关联强度，实际零值不会回退为其他权重。累计 `recalls` 归一化后输入原代码的活跃度范围，不冒称“次／月”。
- 原版默认强调的核心映射到实际可见的高连接度枢纽，仅影响绘图；不修改产品选中记录、不增加调用次数、不触发真实召回。
- 原始显式传导脉冲只接收实际 `trail` 与 `lit` 路径。原版微弱装饰流动仅为视觉。
- 产品现有名称开关、详情、命中、缩放、自动视距、手动视距和缩略导航通过薄适配连接。实际节点坐标、关联和调用数据不因切换而改写。
- 仅使用爱之屋已有的顶栏星星像素按钮切换原版两种视图；不新增图内按钮排。
- 图主题仍使用 `nkb-theme` 的 dark/light。一处旧像素主题按钮负责黑色／白色画布；原顶栏、面板、弹窗、按钮、图标、提示框均保持原配色。旧 cream/blossom 偏好只用于恢复原界面外观，不再提供该配色切换入口，也不会被图主题修改。
- 稀疏 0/1/2 节点保留真实数量；少量节点遵循产品已有可读核心要求。粒子预算只约束装饰数量，关联不因性能预算被删减。

## 实际运行入口

- `approved-atlas-renderer.js`：相机、产品状态、Canvas 生命周期与原代码桥接。没有第二个动画循环，也不构造原 WebGL renderer。
- `approved-atlas-painter.js`：原绘制函数与真实数据薄桥。
- `approved-atlas-data.js`：原星云和平面位置代码与真实数据索引。
- `neural-art.js` 与重建的 `neural-art.bundle.js`：产品现有离线单文件入口。

接口沿用 `resize/setGraph/render/projectNode/projectedBounds/syncTransform/panCamera/centerNode/captureScreenPoint/restoreScreenPoint/resetView/dispose`，另外提供 `displayPosition()`、`isTransitioning()`、`drawPlaneGuide()`。运行时 `artCanvas.dataset.painter` 必须为 `approved-canvas`，并可读取真实关联数、可见关联数、模式、过渡进度、动画时间和装饰粒子数，避免把旧近似 renderer 当成实际交付。

## 验证范围

原代码一致性、0/1/2 节点、90/225 节点的有限绘图坐标、真实边与 ID 保留、装饰预算、生命周期、真实轨迹、暂停、已有视图按钮往返切换，以及相机／缩放／点击／定位／缩略图／释放均有独立可执行测试。原版节点大小和视距测试继续保留。

实际产品页使用隔离合成样本进行 90 节点／184 边、225 节点／455 边的两种视图和黑白画布对照；不使用真实用户存档。原始 UI 的配色与素材通过源码字节及切换前后 computed styles 检查。画面验收需要打开截图与批准原图对照，不能用无控制台错误代替。

本次旧 Three.js 丝带近似实现的性能结论不代表当前原版 Canvas 的性能。Windows 须在自己的 WebView2、字体和高 DPI 环境重新进行原生验收；本机浏览器与 Mac 安装结果不能代替 Windows 二进制验证。正式构建、原生验收、备份、安装及发布由统一发布流程收口。
