#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
adb shell rm -rf /data/local/tmp/love-house-offline-qa
gradle -p android --no-daemon --stacktrace :app:connectedDebugAndroidTest
python scripts/check_android_test_results.py
mkdir -p build/android
adb exec-out cat /data/local/tmp/love-house-offline-qa/android-smoke.png > build/android/android-smoke.png
python - <<'PY'
from pathlib import Path
import hashlib,json,struct
path=Path('build/android/android-smoke.png');data=path.read_bytes()
if (len(data)<33 or data[:8]!=b'\x89PNG\r\n\x1a\n' or data[12:16]!=b'IHDR'
        or data[-8:-4]!=b'IEND'):
    raise SystemExit('Android screenshot is missing, truncated, or is text rather than PNG evidence')
width,height=struct.unpack('>II',data[16:24])
if not 1<=width<=16384 or not 1<=height<=16384:raise SystemExit('Android PNG dimensions are invalid')
report={'schema':'love-house-android-screenshot/v1','png_verified':True,'width':width,'height':height,
        'sha256':hashlib.sha256(data).hexdigest(),'source':'instrumentation_before_target_cleanup'}
Path('build/android/screenshot-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
PY
