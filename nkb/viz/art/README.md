# Digital-Brain 神经美术适配

神经美术实际采用 [SahilK-027/Digital-Brain](https://github.com/SahilK-027/Digital-Brain) 的程序丝线和 GLSL 造型，固定 commit `366cf81dad855ea238dec170fcc65579d6d9ba4b`。原项目 MIT，版权 © 2026 Sahil K。完整许可在 `LICENSE.digital-brain`，并随离线 bundle 头部一起分发。

`digital-brain-adapted.js` 包含可追溯的源码适配：

- `NeuralThreads.class.js` 的 `createSingleThread`：正交基、双正弦/余弦波和 `CatmullRomCurve3`。修改为真实边的两端，增加端点包络以固定节点，不运行原随机簇生成器。
- `ThreadParticles.class.js` 与 `Shaders/threads/thread.vert.glsl`、`thread.frag.glsl`：沿路径采样，原呼吸闪烁、紫/粉渐变和尾部淡出。增加真实召回 trail 过滤、图谱世界尺度、显式可见性；纹理改为本地程序生成。
- `Shaders/brain/brain.frag.glsl`：原 Fresnel、镜面光、AO 和三轴电流高光公式，应用于每个真实记忆神经元的球面点材质。

原模型、纹理、音乐与随机节点未引入。原大脑模型另有 CC BY 4.0 许可，此适配不包含该资产。上游参考版本和对应文件见 `docs/开源视觉来源.md`；公开包保留 `LICENSE.digital-brain`，不附带参考仓库快照。

`neural-art.js` 连接现有知识能力：一个真实记忆对应一个可点的神经元，现有真实边对应三维丝线，只有实际召回结果的 trail 会产生传导光脉冲；装饰高光不增加节点或边。`OrbitControls` 提供拖动旋转与 Shift 平移，`projectNode` 统一标签、悬停、命中与列表定位。时间、情绪、恢复窗口等状态仍由原记忆引擎返回。

`neural-art.bundle.js` 是可直接内联的离线 IIFE，附 Digital-Brain 和 Three.js MIT 许可证。`build.mjs` 以精确锁定依赖重建：`npm ci && npm run build`。HTML 中唯一 `/*__NKB_THREE__*/` 占位由 Python builder 内联。无需 CDN、API 密钥或网络资源。

神经点与丝线批量绘制；超过 1500 节点减少丝线采样。艺术渲染上限约 30 fps，后台标签页不持续重绘。布局使用有界空间网格后停止。暂停按钮及系统减少动态效果偏好会冻结动效。初始化失败、WebGL 上下文丢失或 bundle 缺失时，保留完整 Canvas 2D 分析能力。
