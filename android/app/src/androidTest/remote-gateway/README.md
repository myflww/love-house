# Instrumentation-only HTTPS gateway host

This standalone Gradle project lives entirely below the production project's
`androidTest` tree. It has a different application ID, `android:testOnly=true`,
its own Activity, INTERNET permission and a 127.0.0.1-only generated test CA.
Nothing in this project is included by the production app's source sets.

The independent `android-remote-gateway.yml` workflow builds and runs this host
on API 28 and 36 against the real Python `RemoteGateway`/`MemoryHost` from a second
checkout. `adb reverse` maps the fixture's loopback port; TLS verification uses a generated CA
and SAN-correct leaf certificate, never an SSL-error bypass. The private keys
remain in the disposable runner's temporary directory, not an APK or artifact.

The generated `src/main/res/raw/remote_test_ca.pem` is not committed. Start
`scripts/android_remote_fixture_server.py --root <fresh temporary directory>`
with `PYTHONPATH` pointing at the separately checked out real backend, then run
`scripts/prepare_android_remote_fixture.py --fixture-ready <directory>/ready.json
--output build/android-remote/fixture.json` before building. Pass `--qa-project`
explicitly if this project is moved. The shared native fixture generates the CA;
only its public certificate enters this independent APK. The localhost negative
test uses the SAN-correct server certificate outside the CA's allowed domain and
must receive a real Android SSL error, which the Activity always cancels.
The QA APK is developer test material and must never be published as the app.
