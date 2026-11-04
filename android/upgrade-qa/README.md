# Developer-only Android upgrade probe

This separate APK instruments its own package and operates the actual installed Love House interface using UiAutomation touch and accessibility. It has no app-private file access, JavaScript injection, network permission or signing key dependency.

Only disposable API 28/36 emulators (`ro.kernel.qemu=1`) are accepted. Pass `-e from_version_code 1` to seed the public `0.1.0-preview1` APK, or `-e from_version_code 2` to seed the public `0.8.0rc1` APK. Both phases check the original certificate. `seed` enters fixed synthetic Unicode original/reply/tags through the real editor. After the wrapper force-stops the app and performs `adb install -r`, `verify` checks versionCode 3 / `0.8.0rc2` and reads back those same fields. Never uninstall the target between phases.

The outer Python verifier requires successful seed and verify transcripts, the exact requested API and starting version, six passing app instrumentation tests without skips, and a CRC-checked actual app screenshot. The workflow covers all four combinations of starting version (1/2) and Android API (28/36).

Do not distribute this QA APK as the application or run it on a physical user device.
