# 0.10.7rc1 Android 原签名收尾任务

此文供**持有爱之屋原发行私钥的另一台设备上的开发代理**执行。用户已授权完成
Android 更新并补充上传 GitHub。无需重新询问是否发布；私钥口令必须留在本机隐藏终端输入，
不能发到聊天、日志、提交或 GitHub。当前设备完成构建与交接，**尚未完成本版本原签名、
签名包覆盖升级验收或 Android APK 发布**。Windows、macOS 有各自验收，不代表 Android 已通过。

## 唯一目标和固定身份

将同一份已冻结、通过 Android API 28 / 36 测试的 0.10.7rc1 源码与 APK 输入，使用原密钥
签名，覆盖公开 0.10.6rc1 Android 版，验证记忆保留，再将**主 APK**追加到
[v0.10.7rc1 发行页](https://github.com/myflww/love-house/releases/tag/v0.10.7rc1)。

| 项目 | 固定值 |
| --- | --- |
| 仓库 | `myflww/love-house` |
| 新版本 | `0.10.7rc1`，`versionCode 5` |
| 包名 | `io.github.myflww.lovehouse.preview` |
| 原证书 SHA-256 | `ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc` |
| 公开旧版 | `0.10.6rc1`，`versionCode 4` |
| 旧版 APK 大小 | `48430105` 字节 |
| 旧版 APK SHA-256 | `4d27f0a732c6edc53fbfcdcaac43f573b91327b703e10396e5d0c8435390f018` |

禁止新建替代密钥、使用 debug 密钥、修改包名、卸载旧版或清空数据来规避覆盖安装问题。
不修改已发布 Windows/macOS 安装包，不替换这些平台的验收文件，不覆盖 0.10.6rc1 资产。

## 先核对交接与来源

1. 从发行页下载名称含 `Android-Original-Signer-Handoff` 的 ZIP。它是开发交接，不能直接安装。
   外层 ZIP 大小与 SHA-256 以发行资产和本次公开下载核验记录为准。核对之后解压到新目录。
2. 读取 `Android-signing-input.json`。记录其 `source_commit`、版本 0.10.7rc1/code 5、原证书，
   以及 `apk`、`test_apk`、`source_archive` 的**实际**相对路径、字节数、SHA-256。
   使用 `SHA256SUMS.txt` 逐项复核。不要将文档里的示例提交当成真实源码提交。
3. 保存 `Android-handoff-verification.json` 和两个 API 的实际 CI 报告。
   在 GitHub Actions 确认产生输入的工作流成功、源码 SHA 与 manifest 完全一致。
   API 28 旧 WebView 可能只执行 legacy/provider 范围；API 36 必须完成 full engine 范围。
   记录 runner 的实际 WebView、测试数与 `full_engine_verified`，不把部分验收写成全功能通过。
4. 源码 ZIP 是本次交接的完整冻结源。若另行 clone 仓库，checkout manifest 的准确提交；
   不在签名前顺手合并新代码或重新打包。先审阅签名脚本再执行。

输入 manifest、源码 ZIP、APK 与报告携带本次准确源码和哈希，不能用上次 0.10.6 的通过报告替代。

## 原密钥签名

已有 Java 17+ 与官方 Android SDK Build-Tools 36.0.0。原密钥留在原设备，**不要复制到 CI**。
交接根目录的签名脚本可直接运行；将 `FULL_COMMIT_FROM_MANIFEST` 替换为刚核对的 40 位提交。

```sh
python scripts/sign_android_release.py \
  --manifest Android-signing-input.json \
  --expected-source-commit FULL_COMMIT_FROM_MANIFEST \
  --expected-version-name 0.10.7rc1 --expected-version-code 5 \
  --build-tools /path/to/Android/sdk/build-tools/36.0.0 \
  --keystore /private/path/EXISTING_ORIGINAL_KEY.jks \
  --alias EXISTING_ORIGINAL_ALIAS \
  --output-dir signed-0107
```

在 Windows 上可使用 `py -3.13 -X utf8`，将参数改成实际 Windows 路径并按 PowerShell 语法换行。
工具核对 manifest 和三个输入后才请求隐藏口令。签名后验证原证书、版本、runner、16KB
对齐与所有非签名 payload 字节，并输出：

- `LoveHouse-0.10.7rc1-Android.apk`：待验收主程序。
- `LoveHouse-0.10.7rc1-Android-QA-ONLY.apk`：开发测试包，不公开。
- `Android-original-signing-verification.json`：公开签名收据，仍不代表设备覆盖升级已通过。

第二份签名失败、证书不符或 payload 变化时工具不会交付半份结果。重试用新目录。

## 公开旧版覆盖升级：API 28 / 36

在 Linux/macOS 的**两个全新一次性 Android 模拟器**分别执行，不能连接物理设备。
使用冻结源码中的 `android/upgrade-qa` 构建独立 UI 探针；它不进入主 APK，不需要原发行签名。
Gradle 8.13、Android SDK platform 36 / build-tools 36.0.0：

```sh
gradle -p android/upgrade-qa --no-daemon :app:assembleDebug
python -m unittest tests.test_android_signed_upgrade tests.test_android_release_signing -v
```

每次只启动一个 API 28 或 API 36 的一次性模拟器，分别用全新输出目录运行：

```sh
python scripts/verify_android_signed_upgrade.py \
  --manifest /handoff/Android-signing-input.json \
  --signed-dir /handoff/signed-0107 \
  --expected-source-commit FULL_COMMIT_FROM_MANIFEST \
  --expected-version-name 0.10.7rc1 --expected-version-code 5 \
  --sdk /path/to/Android/sdk \
  --probe-apk android/upgrade-qa/app/build/outputs/apk/debug/app-debug.apk \
  --api-level 28 --output-dir build/signed-0107-api28
```

另一次换 `--api-level 36 --output-dir build/signed-0107-api36`。脚本匿名下载固定公开旧 APK，
验签并核对上述 SHA，进入旧版真实界面写入合成原文/回复/标签，通过 `adb install -r` 覆盖新包，
验证原数据和再次进程重启后的保留，再安装原签名 QA 包执行实际仪器测试。保存原始日志与 JSON。
API 28 旧 WebView 的完整引擎限制必须如实保留，API 36 必须为 full engine。

额外检查新版里原有多个独立记忆库、真实共享引擎库的原文/来源/角色、连接授权、模型配置、
加密凭据删除和进程重启持久化。如需为这些补充探针，只改开发 QA，保持已签主 APK payload 不变。
不能从 legacy 原文保留结果推断所有引擎库与凭据已完成跨版本验证。

## 追加发布并匿名复核

两个 API 验收都通过后，生成 `Android-0107-verification.json`，包括本次源码 SHA、原签名主 APK
大小/SHA、原证书、两个 API 的原始报告/日志 SHA、旧版 SHA、实际测试范围与限制；全部材料不含私钥和口令。
需要补测的项目应明确列出，不能把计划写成完成。

先检查发行页是否已存在同名 APK：完全相同则核对后复用；不同则停止并查明，不能自动覆盖。
只追加主 APK 与 Android 专属验收/校验和材料；不上传 QA-only APK、unsigned APK、密钥或口令。
更新说明中的 Android 状态为已完成，并保持 Windows/macOS 原文件不变。

最后退出认证或使用无凭据 HTTP 客户端，匿名下载公开 APK，逐字节核对大小和 SHA-256。
核对 tag、目标提交、更新检测器只推荐主 APK。记录公开 URL 与匿名复核结果，再向用户汇报。
如果原密钥、口令、网络或任何验收仍有问题，就明确报告具体缺口，保留已生成的材料，不发布未经验证的 APK。
