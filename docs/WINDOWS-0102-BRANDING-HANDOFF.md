# Windows后续同步：Mac 0.10.2品牌与展示

Mac在0.10.1基线上移植Windows 0.10.2rc1交回的AstrBot0.3快速配置、分库整理API状态与原版相机自旋；原Mac Keychain与原生入口保持。Windows本身已经完成这些共享功能，不要用Mac全工程覆盖Windows0.10.2rc1原生修复。

本轮需Windows维护者选择性同步的是品牌与首页：assets/branding/love-house-icon.png为新透明像素心母版，index.html houseBrandIcon内嵌图与其字节完全相同，空白页继续克隆。bannerSVG直接内嵌同PNG，versioned project-banner-0102.svg用于避免旧缓存。实际prompt/provenance及scripts/check_branding.py随源码发布；母版SHA d102ba407cb2201d89b867e303867dde171da4dfa13d41e679863c8f71c48bc1。

重建Windows ICO、安装器图标与原生展示，确认不是只换Web标志。脚本默认仍从同一主PNG生成，保留Windows运行时/安装/路径/导出/保护修复。无需重画按钮atlas、字体或星云；本轮原画笔和布局函数保持，只有已移植的相机行为增量。

新版首页用三张真实UI高清PNG（合成资料，无Key/用户聊天），全宽并可点原图。不要再把JPEG内容命名.png，也不要把旧UI图伪装成新版本。保留Windows0102rc1下载与验证入口、手机080rc2入口、许可和myflww署名。Main经PR更新，完整树和manifest逐项核对，不覆盖其它平台代码。

Mac已完成951项目回归（2外部源码项跳过）和19桌面适配，以及本机官方AstrBot4293的43项离线适配器契约。0.3插件ZIP与Windows同SHA；无新增真实QQ/模型端到端测试。Windows新品牌包仍需本机原生、ICO多尺寸、安装／便携、覆盖升级、原数据和凭据元数据保留及公开下载复核后发布。Mac包验证不能代替Windows二进制通过。
