# Android third-party notices

The Android application uses AndroidX WebKit 1.18.0 and its AndroidX runtime
dependencies, copyright The Android Open Source Project, under the Apache
License 2.0. The complete licence text is preserved in
`LICENSE.androidx-Apache-2.0.txt` and copied into the application's local assets.

Upstream: https://developer.android.com/jetpack/androidx/releases/webkit

AndroidX Test Runner/Core 1.7.0 and JUnit extension 1.3.0 are used only in the
instrumentation test APK, not the distributed release application. They are
also supplied under the Apache License 2.0.

Gradle, Android Gradle Plugin, the Android SDK and JDK are developer build tools.
They are not embedded in the distributed application APK. The separate CI
developer artifact may contain the Android SDK's `apksigner.jar` for local
signing; it is not part of the application and its upstream notices are retained.

Love House source retains its own PolyForm Noncommercial 1.0.0 terms and the
myflww notice. AndroidX licences are not changed by the application's terms.
