#!/usr/bin/env bash
# Real iOS Simulator WKWebView + native TLS trust; never deploys a service publicly.
set -euo pipefail
project_root=$(cd "$(dirname "$0")/.." && pwd)
backend_root=${1:?Pass the checkout containing the real RemoteGateway backend}
qa_root=${2:-"$project_root/build/ios-portal"}
mkdir -p "$qa_root/reports" "$qa_root/app/LoveHousePortalQA.app"
qa_root=$(cd "$qa_root" && pwd)
fixture_pid=''
simulator_id=''
cleanup() {
  if [[ -n "$simulator_id" ]]; then xcrun simctl shutdown "$simulator_id" >/dev/null 2>&1 || true; xcrun simctl delete "$simulator_id" >/dev/null 2>&1 || true; fi
  if [[ -n "$fixture_pid" ]]; then kill "$fixture_pid" 2>/dev/null || true; wait "$fixture_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
export PYTHONUTF8=1
rm -f "$qa_root/fixture/ready.json" "$qa_root/fixture/service-state.json"
PYTHONPATH="$backend_root" python3 "$project_root/ios-smoke/fixture_server.py" --root "$qa_root/fixture" >"$qa_root/reports/fixture.log" 2>&1 &
fixture_pid=$!
for ((attempt=0; attempt<100; attempt++)); do
  [[ -f "$qa_root/fixture/ready.json" ]] && break
  kill -0 "$fixture_pid" 2>/dev/null || { cat "$qa_root/reports/fixture.log"; exit 1; }
  sleep .2
done
test -f "$qa_root/fixture/ready.json"
origin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["origin"])' "$qa_root/fixture/ready.json")
root_ca=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_ca"])' "$qa_root/fixture/ready.json")
xcodebuild -version > "$qa_root/reports/xcode-version.txt"
xcrun simctl list runtimes --json > "$qa_root/reports/simulator-runtimes.json"
simulator_runtime=$(python3 -c 'import json,sys; rs=[r for r in json.load(open(sys.argv[1]))["runtimes"] if r.get("isAvailable") and "iOS" in r.get("name","")]; assert rs,"No installed iOS Simulator runtime"; print(sorted(rs,key=lambda r:tuple(int(p) for p in r["version"].split(".")),reverse=True)[0]["identifier"])' "$qa_root/reports/simulator-runtimes.json")
simulator_id=$(xcrun simctl create 'LoveHouse native iOS Portal QA' com.apple.CoreSimulator.SimDeviceType.iPhone-16 "$simulator_runtime")
xcrun simctl boot "$simulator_id"
xcrun simctl bootstatus "$simulator_id" -b
app="$qa_root/app/LoveHousePortalQA.app"
cat > "$app/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>io.github.myflww.lovehouse.iosportalqa</string>
<key>CFBundleExecutable</key><string>LoveHousePortalQA</string>
<key>CFBundleName</key><string>LoveHouse Portal QA</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>CFBundleShortVersionString</key><string>0.8.0</string>
<key>CFBundleSupportedPlatforms</key><array><string>iPhoneSimulator</string></array>
<key>LSRequiresIPhoneOS</key><true/>
<key>MinimumOSVersion</key><string>15.4</string>
<key>UIDeviceFamily</key><array><integer>1</integer><integer>2</integer></array>
<key>UILaunchScreen</key><dict/>
<key>UIApplicationSceneManifest</key><dict><key>UIApplicationSupportsMultipleScenes</key><false/></dict>
</dict></plist>
PLIST
architecture=$(uname -m)
[[ "$architecture" == arm64 || "$architecture" == x86_64 ]]
xcrun --sdk iphonesimulator swiftc -swift-version 5 -parse-as-library -target "$architecture-apple-ios15.4-simulator" -sdk "$(xcrun --sdk iphonesimulator --show-sdk-path)" -framework UIKit -framework WebKit "$project_root/ios-smoke/PortalSmoke.swift" -o "$app/LoveHousePortalQA"
codesign --force --sign - --timestamp=none "$app"
xcrun simctl install "$simulator_id" "$app"
data=$(xcrun simctl get_app_container "$simulator_id" io.github.myflww.lovehouse.iosportalqa data)
wait_report() {
  local name=$1
  for ((attempt=0; attempt<200; attempt++)); do
    if [[ -s "$data/Documents/$name" ]]; then cp "$data/Documents/$name" "$qa_root/reports/$name"; return 0; fi
    sleep .5
  done
  xcrun simctl io "$simulator_id" screenshot "$qa_root/reports/timeout.png" || true
  echo "Native iOS report was not finalized: $name" >&2
  return 1
}
# Control: prove that the native engine refuses this CA before trust installation.
xcrun simctl launch --terminate-running-process "$simulator_id" io.github.myflww.lovehouse.iosportalqa --origin "$origin" --mode reject
wait_report tls-rejection.json
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert r.get("ok") is True and r.get("tls_rejected") is True and r.get("process_complete") is True,r' "$qa_root/reports/tls-rejection.json"
# Install the isolated CA into the simulator trust store; there is no URLSession/WKWebView TLS override.
xcrun simctl terminate "$simulator_id" io.github.myflww.lovehouse.iosportalqa || true
xcrun simctl keychain "$simulator_id" add-root-cert "$root_ca"
xcrun simctl launch --terminate-running-process "$simulator_id" io.github.myflww.lovehouse.iosportalqa --origin "$origin" --mode portal
wait_report ios-portal-smoke.json
xcrun simctl io "$simulator_id" screenshot "$qa_root/reports/ios-portal-connected.png"
for ((attempt=0; attempt<40; attempt++)); do
  if python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if r.get("original_user_saved") is True and r.get("original_assistant_saved") is True else 1)' "$qa_root/fixture/service-state.json" 2>/dev/null; then break; fi
  sleep .25
done
cp "$qa_root/fixture/service-state.json" "$qa_root/reports/service-state.json"
cp "$qa_root/fixture/ready.json" "$qa_root/reports/fixture-ready.json"
git -C "$backend_root" rev-parse HEAD > "$qa_root/reports/backend-commit.txt"
python3 "$project_root/ios-smoke/check_reports.py" "$qa_root/reports"
