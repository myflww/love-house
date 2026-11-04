#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_REMOTE_FIXTURE_ROOT:?The isolated native fixture root is required}"
: "${ANDROID_REMOTE_API_LEVEL:?The actual matrix API level is required}"
qa_project='android/app/src/androidTest/remote-gateway'
origin=$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["origin"])' "$ANDROID_REMOTE_FIXTURE_ROOT/ready.json")
port=$(python -c 'import sys,urllib.parse;print(urllib.parse.urlsplit(sys.argv[1]).port)' "$origin")
adb reverse "tcp:$port" "tcp:$port"
adb shell rm -rf /data/local/tmp/love-house-remote-qa
set +e
gradle -p "$qa_project" --no-daemon --stacktrace connectedDebugAndroidTest \
  "-Pandroid.testInstrumentationRunnerArguments.gatewayOrigin=$origin"
instrumentation_exit=$?
set -e
mkdir -p build/android-remote
# AGP removes the testOnly APK at suite cleanup. The instrumentation exports
# its synthetic evidence before then using UiAutomation, without adding any
# production or QA storage permission. Preserve diagnostics even on failure.
adb pull /data/local/tmp/love-house-remote-qa build/android-remote/native-output || true
if [[ -f "$ANDROID_REMOTE_FIXTURE_ROOT/origin-diagnostics.jsonl" ]]; then
  cp "$ANDROID_REMOTE_FIXTURE_ROOT/origin-diagnostics.jsonl" build/android-remote/
fi
if [[ $instrumentation_exit -ne 0 ]]; then exit "$instrumentation_exit"; fi
python scripts/check_android_test_results.py --reports "$qa_project/build/outputs/androidTest-results/connected"
for file in android-remote-gateway.json android-tls-rejection.json android-remote-gateway.png; do
  cp "build/android-remote/native-output/$file" "build/android-remote/$file"
  test -s "build/android-remote/$file"
done
python - "$ANDROID_REMOTE_FIXTURE_ROOT/service-state.json" <<'PY'
from pathlib import Path
import json,sys,time
source=Path(sys.argv[1])
for _ in range(40):
    if source.exists():
        data=json.loads(source.read_text())
        if data.get('original_user_saved') is True and data.get('original_assistant_saved') is True:break
    time.sleep(.25)
else:raise SystemExit('Actual backend did not finalize the synthetic Android dialogue')
Path('build/android-remote/service-state.json').write_text(json.dumps(data,indent=2)+'\n')
PY
python scripts/check_android_remote_reports.py --directory build/android-remote --api-level "$ANDROID_REMOTE_API_LEVEL"
adb reverse --remove "tcp:$port"
