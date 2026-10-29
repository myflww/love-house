#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
gradle -p android --no-daemon --stacktrace :app:connectedDebugAndroidTest
python scripts/check_android_test_results.py
mkdir -p build/android
adb exec-out run-as io.github.myflww.lovehouse.preview cat files/android-smoke.png > build/android/android-smoke.png
test -s build/android/android-smoke.png
