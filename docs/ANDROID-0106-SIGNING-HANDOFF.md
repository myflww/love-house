# Android 0.10.6rc1 原发行签名与覆盖升级交接

本交接供持有爱之屋**原发行私钥**的电脑使用。输入是开发产物和冻结源码，不是面向用户的安装包；当前尚未证明已完成原签名、覆盖升级或公开发布。不要将 unsigned APK 改名后上传，也不要把测试 APK 放进推荐下载。

## 交接内容

交接包由构建端冻结后准备，至少包含：

- `Android-0106-signing-input.json`：固定源码提交、版本、原证书指纹，以及两个 APK 和源码 ZIP 的相对路径、字节数与 SHA-256。
- 未签名的主 release APK，以及独立的 instrumentation APK；后者可能带开发签名，只用于升级后的实际仪器测试。
- 与构建来源核对过的源码 ZIP、许可和已有构建/测试证据。
- `scripts/sign_android_0106.py`、`scripts/verify_android_release.py` 及本次 Windows / macOS 包装脚本。

构建端须在交接记录中填写**实际源码 commit 和输入哈希**。未填写或仍是占位符时不签名。签名端先对照 GitHub 对应提交和构建来源，核对源码 ZIP，再把确认的完整 commit 传给工具。脚本核对的是这些开发者交接记录及本地输入指纹，不冒充独立重建或第三方来源证明。

固定的发行身份：

| 项目 | 值 |
|---|---|
| 主包名 | `io.github.myflww.lovehouse.preview` |
| 主版本 | `0.10.6rc1`，`versionCode 4` |
| SDK | 最低 26，目标 36 |
| 原证书 SHA-256 | `ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc` |
| 仪器测试包名 | `io.github.myflww.lovehouse.preview.test` |
| 仪器 runner | `androidx.test.runner.AndroidJUnitRunner`，目标为上面的主包 |

实际 Gradle 测试包未声明 `versionCode` 与 `versionName`，aapt 输出这两项为空；不能把测试包当作主包 code 4，也不能据此省略 runner / targetPackage 检查。

## 需要准备的本机工具

使用 Python 3.11+、Java 17+ 和官方 Android SDK Build-Tools 36.0.0；签名工具直接调用 SDK 的 `lib/apksigner.jar`、`aapt` 和 `zipalign`。不需要复制私钥到交接目录，也不生成新 Key。`--keystore` 只指向签名电脑上原来保存的文件，`--alias` 使用原有别名。

口令由 Python 在终端隐藏输入，第二个“Key password”留空表示沿用 keystore 口令。不要把口令放到聊天、脚本、命令参数、环境变量、manifest 或 GitHub。若终端不支持隐藏输入，工具会失败，不能改成明文口令参数继续。

## 一次执行两个 APK 的签名

解压到可读写目录，在交接包根目录打开终端。下列值都是示意名称，应替换成签名电脑自己的工具路径、原 Key 路径与已确认 commit；没有内嵌开发电脑的路径或凭据。

Windows PowerShell：

```powershell
.\scripts\sign-android-0106.ps1 `
  -ExpectedSourceCommit '<已核对的40位源码commit>' `
  -BuildTools '<SDK中的build-tools\36.0.0目录>' `
  -Keystore '<原持久keystore的本机路径>' `
  -Alias '<原Key别名>'
```

macOS / Linux：

```bash
bash scripts/sign-android-0106.sh \
  --expected-source-commit '<已核对的40位源码commit>' \
  --build-tools '<SDK中的build-tools/36.0.0目录>' \
  --keystore '<原持久keystore的本机路径>' \
  --alias '<原Key别名>'
```

可用 Windows `-Python`、`-Java` 或 shell `--python`、`--java` 指定现有可执行文件。默认从 PATH 找 Python 与 Java。若缺少所需工具，先由操作者安装官方工具，脚本不会自行下载运行时或接受许可。

默认读取交接包根目录的 `Android-0106-signing-input.json`，写入全新的 `signed-0106` 目录。也可显式传入其他 manifest 和全新的输出目录；工具不覆盖已有文件或目录。不要为了重试而删除旧的验收结果，选另一个新目录即可。

一次签名会先核对所有输入文件的字节数、SHA-256、ZIP 结构、主包身份与测试 runner。签名后再核对原证书、SDK / 版本、16 KiB 对齐，以及除签名文件外全部 ZIP 有效载荷没有变化。两个 APK 都通过后才交付结果；第二个失败时不留下半份已验证的发行交接。

成功目录包含：

- `LoveHouse-0.10.6rc1-Android.apk`：原签名主程序，仍需完成设备升级验收。
- `LoveHouse-0.10.6rc1-Android-QA-ONLY.apk`：与主程序同原签名的测试包，**仅供 QA，不公开下载**。
- `Android-0106-original-signing-verification.json`：输入指纹、源提交核对方式、签后指纹、证书、payload 比较等公开报告，不含私钥、别名、口令或本机 Key 路径。

报告中的 `device_upgrade_verified:false`、`published:false` 是签名阶段的真实状态。不能因为签名通过就改为已经保留旧数据或已经发布。

## 必须完成的原签名覆盖升级验收

优先在独立模拟器或可清理的测试设备完成。不要拿用户唯一一份正式记忆做破坏性实验。必须使用原签名公开旧包与本次签名后主包，不能用 debug 主包替代：

1. 从公开的 `v0.8.0rc2` 下载 `LoveHouse-0.8.0rc2-Android.apk`，核对公开 SHA-256 和同一原证书。安装后创建至少两个独立旧库，写入可逐字比对的合成原话、回复与标签，并导出 JSON。
2. 使用系统覆盖安装或 `adb install -r` 安装本次原签名主包。**不先卸载、不清数据，也不使用 `-d` 降级选项。** 确认最终主包为 code 4 / 0.10.6rc1。
3. 打开原离线入口，逐库核对名称、原话、回复、标签和数量；完全关闭并重新启动后再核对一次。原来的 WebView 来源与数据空间必须仍可读取。
4. 选择其中一个库，先备份，再明确执行“迁移当前旧库”。在完整记忆中核对导入结果及库隔离，另一个旧库没有被默默迁移；原库没有被删除。重复同份迁移不应制造相同副本。
5. 关闭完整界面，重新进入并重启应用，核对完整库持久化、旧库仍在；实际执行完整引擎的 JSON 导出、导入恢复和系统文件保存，不能只检查按钮存在。
6. 安装 QA-only 仪器测试包，运行本次交接的实际 Android 测试，记录设备 API、测试数量、成功/失败、运行日志与截图。需要 Key 的真实模型测试另行得到授权，不自动消费任何软件中已有凭据。
7. 核对 Keystore 的合成凭据保存/读取/重启/删除结果、连接到错误库或未经授权来源被拒绝；报告不能输出模型 Key 或用户记忆。

对于 Android 9 / API 28 和 Android 16 / API 36 应分别记录实际测试；某个 API 尚未执行或失败时，保留未通过状态，不复用另一台设备的报告。模拟器通过也不能写成所有真实手机已验收。

## 什么时候才能上传 GitHub

只有两份 APK 的原证书及 payload 验证通过、真实旧版覆盖升级保留、明确迁移后重启及实际仪器测试通过，才能新增公开的**主程序 APK**。QA-only 包、unsigned APK、私钥与口令不进入公开下载。

上传主程序时同时提供实际 SHA-256、证书指纹和验收报告，重新从公开发布页下载后比对同一文件的哈希。随后再将 README、下载表和手机版说明从 0.8.0rc2 更新到新包；发布页不能只写“与电脑版相同”而隐藏手机的架构、关闭界面会停止接收、跨设备服务等边界。

这份交接不执行上传、安装或修改历史发布。可以将两个签名后 APK 和不含秘密的报告通过受控方式交回开发验收；公开发布只选主 APK 和可公开报告。项目遵守 [PolyForm Noncommercial 1.0.0](../LICENSE)，保留 myflww 署名与第三方许可。
