# Android 原签名交接

持续使用既有发行密钥，保留包名 `io.github.myflww.lovehouse.preview` 与原证书
`ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc`。
每个版本重新构建、签名、覆盖升级验收；不能复用旧版的通过记录。

CI 在 API 28 / 36 的一次性模拟器上测试之后生成 `Original-Signer-Handoff`。
其中 APK 尚未签名，QA 包仅用于开发验收，均不能作为公开安装包。
源码 ZIP、两个 APK 与 `Android-signing-input.json` 固定源码提交、版本、大小和 SHA-256。
主 APK 版本读取 Gradle，并强制与共享记忆引擎一致，避免升级时遗漏某个平台。

在已持有原密钥的电脑上运行以下命令。将提交、版本和递增版本号替换成已核对的
交接值。口令只通过隐藏终端输入和 apksigner 标准输入传递；不要发到聊天、GitHub
或命令行参数中。工具不会生成新密钥、覆盖旧目录、上传或安装。

```sh
python scripts/sign_android_release.py \
  --manifest Android-signing-input.json \
  --expected-source-commit FULL_REVIEWED_COMMIT \
  --expected-version-name 0.10.7rc1 --expected-version-code 5 \
  --build-tools /path/to/Android/sdk/build-tools/36.0.0 \
  --keystore /private/path/original-keystore.jks --alias EXISTING_ALIAS \
  --output-dir signed-release
```

只有 `LoveHouse-VERSION-Android.apk` 是待验收的主程序。
`LoveHouse-VERSION-Android-QA-ONLY.apk` 不进入公开下载。
原证书、签名前后 payload、APK 身份和输入哈希验证通过后，仍需使用**这份签名主包**
覆盖安装公开旧版并检查原文、回复、独立记忆库和重启持久化，才能发布。

缺少原密钥时，保留交接材料并如实说明 Android 尚未完成签名发布。
不能改用 debug 密钥、生成替代密钥或修改包名，让用户卸载后重装。
