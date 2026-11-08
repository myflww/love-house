# Developer-only upgrade UI probe

This separate APK instruments only its own package. It starts the actual installed Love House App and reads/writes the visible WebView through Android UiAutomation accessibility actions. It has no private app file access, JavaScript injection, network permission or dependency on the original signing key.

Only disposable API 28 / 36 emulators with `ro.kernel.qemu=1` are accepted. Both modes verify the installed target's original public certificate. `seed` requires the original `0.1.0-preview1` / versionCode 1, adds one fixed synthetic original/reply/tags record through the editor, and opens its detail to read it back. `verify` requires `0.8.0rc1` / versionCode 2 and reopens that same record after the outer CI wrapper has force-stopped and covered the old App with `adb install -r`.

```sh
gradle -p qa/android-upgrade --no-daemon :app:assembleDebug
adb install -t qa/android-upgrade/app/build/outputs/apk/debug/app-debug.apk
adb shell am instrument -w -r -e mode seed io.github.myflww.lovehouse.upgradeqa/io.github.myflww.lovehouse.upgradeqa.UpgradeProbeInstrumentation
# Force stop the target, then adb install -r the final signed new App. Do not uninstall.
adb shell am instrument -w -r -e mode verify io.github.myflww.lovehouse.upgradeqa/io.github.myflww.lovehouse.upgradeqa.UpgradeProbeInstrumentation
```

Success ends with `INSTRUMENTATION_CODE: -1`, `ok=true` and matching `mode=seed/verify`. Failure uses code 1 and a fixed stage without echoing memory bodies. The outer wrapper must require both successful phases and verify the exact installed APK hashes. Do not ship this QA APK as the public application or run it on a user's physical device.
