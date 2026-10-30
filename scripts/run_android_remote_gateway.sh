#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_REMOTE_FIXTURE_ROOT:?The isolated native fixture root is required}"
: "${ANDROID_REMOTE_API_LEVEL:?The actual matrix API level is required}"
qa_project='android/app/src/androidTest/remote-gateway'
origin=$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["origin"])' "$ANDROID_REMOTE_FIXTURE_ROOT/ready.json")
port=$(python -c 'import sys,urllib.parse;print(urllib.parse.urlsplit(sys.argv[1]).port)' "$origin")
adb reverse "tcp:$port" "tcp:$port"
gradle -p "$qa_project" --no-daemon --stacktrace connectedDebugAndroidTest \
  "-Pandroid.testInstrumentationRunnerArguments.gatewayOrigin=$origin"
python scripts/check_android_test_results.py --reports "$qa_project/build/outputs/androidTest-results/connected"
mkdir -p build/android-remote
for file in android-remote-gateway.json android-tls-rejection.json android-remote-gateway.png; do
  adb exec-out run-as io.github.myflww.lovehouse.remoteqa cat "files/$file" > "build/android-remote/$file"
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
