# 在原密钥电脑签署 Android 0.8 升级包

原私钥留在已有签名电脑。带过去的是经过本轮 CI 验证的 unsigned APK、仓库这份脚本及 `scripts/verify_android_release.py`；不需要把私钥或密码发回聊天、搬进仓库或上传 GitHub。

固定升级身份：

- applicationId：`io.github.myflww.lovehouse.preview`
- versionName：`0.8.0rc1`
- versionCode：`2`，高于旧版的 `1`
- 原证书 SHA-256：`ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc`

签名电脑需要已有 Python 3.11+、Java 17+ 和 Android SDK Build-Tools 36.0.0。脚本调用其中的 `aapt`、`zipalign` 和 `lib/apksigner.jar`，不会下载或安装软件。使用本轮成功 Android CI 的 unsigned artifact；从同一 artifact 的 `SHA256SUMS.txt` 取得 unsigned APK 的摘要，不能用旧的 0.1 包代替。

在 PowerShell 的仓库目录运行（把路径、摘要和已有 alias 替换为该电脑的真实信息；命令中不填写密码）：

```powershell
python scripts/sign_android_upgrade.py `
  --unsigned-apk "C:\Signing\LoveHouse-0.8.0rc1-Android-unsigned.apk" `
  --expected-sha256 "这里填写本轮CI提供的64位SHA256" `
  --build-tools "C:\Android\Sdk\build-tools\36.0.0" `
  --java "C:\Tools\Java17\bin\java.exe" `
  --keystore "D:\PrivateSigning\原来的发行密钥.jks" `
  --alias "原来的密钥别名" `
  --output-apk "C:\Signing\LoveHouse-0.8.0rc1-Android.apk"
```

macOS/Linux 使用同一参数，在普通交互式终端把换行符改为 `\`，并填写该机工具路径。脚本接下来分别隐藏询问 keystore 密码和 key 密码；第二项直接回车表示与第一项相同。无法隐藏输入时会停止。不要把密码写到命令、环境变量或文本文件。

脚本先验证输入 SHA-256、APK 包名/版本、SDK 元数据和对齐，再签署到临时文件。签署后再次核验签名、上述原证书指纹和包身份，全部通过才写出新 APK 与 `*.apk.verification.json`。选错密钥、错误密码或证书不匹配均不会交付升级包；已有输出也不会被覆盖。

这是**本机签名与包身份验证**，不是模拟器或手机的覆盖升级验收。它不创建密钥、不换包名、不轮换证书、不改 `android/release-candidate.json`，也不自动发布。把得到的 APK、公开 SHA-256 和验证 JSON 带回后，仍需让最终签名包在既定测试流程中验证；对已有 0.1 用户的数据保留，应在装有旧版及测试存档的设备使用覆盖安装（例如 `adb install -r`），确认旧存档仍可读取。不要先卸载旧应用。

实现依据：[Android 官方 apksigner 说明](https://developer.android.com/tools/apksigner)。`--ks-pass stdin` 与 `--key-pass stdin` 按顺序读取两行密码；脚本使用该方式，原始工具输出不会回显到错误日志。
