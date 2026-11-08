# Android third-party notices

Love House Android 0.10.6rc1 embeds the same Python memory engine as the desktop
application through **Chaquopy 17.2.0 and CPython 3.12.15**. The distributed APK
contains the `arm64-v8a` and `x86_64` runtimes; these are Android builds, not copies
of the macOS Python runtime. The fixed upstream texts and their SHA-256 provenance
are preserved in [`licenses/`](licenses/). They are also copied byte for byte into
both the offline application's `android-licenses/` assets and the embedded engine's
licence directory when the APK is built.

| Embedded component | Terms and complete notices |
| --- | --- |
| Chaquopy 17.2.0 Java/Python/native runtime | MIT; `licenses/LICENSE.chaquopy-17.2.0.txt` |
| CPython 3.12.15, including the standard library | PSF 2 and historical terms; `licenses/LICENSE.cpython-3.12.15.txt`; complete upstream third-party notices in `licenses/LICENSE.cpython-third-party-3.12.15.txt` |
| OpenSSL 3.5.9 | Apache 2.0; `licenses/LICENSE.openssl-3.5.9-Apache-2.0.txt`; upstream author acknowledgements retained separately |
| SQLite 3.53.4 | Public-domain dedication/blessing copied from the actual Android runtime header, `licenses/LICENSE.sqlite-3.53.4.txt` |
| bzip2 1.0.8 | bzip2 BSD-style terms; `licenses/LICENSE.bzip2-1.0.8.txt` |
| libffi 3.4.4 | MIT; `licenses/LICENSE.libffi-3.4.4.txt` |
| XZ Utils / liblzma 5.4.6 | The embedded **liblzma** is public domain under upstream `licenses/LICENSE.xz-5.4.6.txt`. The XZ CLI tools, gzip-derived scripts, GNU getopt and build system discussed in that upstream notice are not distributed here. |
| Expat 2.8.5, vendored in CPython | MIT; complete upstream `licenses/LICENSE.expat-2.8.5.txt` |
| HACL* hash implementations, vendored in CPython | MIT; original source-file notices in `licenses/LICENSE.HACL-Python-3.12.15.txt` |
| BLAKE2 reference implementation, vendored in CPython | CC0; original notice and full dedication in `licenses/NOTICE.BLAKE2-Python-3.12.15.txt` and `licenses/LICENSE.CC0-1.0.txt` |
| Unicode 15.0.0 data in CPython | Unicode data-file terms; `licenses/NOTICE.Unicode-15.0.0.txt` and `licenses/LICENSE.Unicode-DFS-2016.txt` |
| Mozilla CA bundle from certifi 2026.10.23 | MPL 2.0 applies to that file, not the whole application; full terms in `licenses/LICENSE.MPL-2.0.txt` and source notice in `licenses/LICENSE.certifi-2026.10.23.txt`. The source URL and checksum of the byte-identical embedded CA bundle are in `licenses/provenance.json`. |

Other standard-library component notices, including libmpdec, historical zlib
notices, hash implementations, asyncio and audioop acknowledgements, remain intact
in the complete CPython upstream notice document. The Android platform supplies
its own system libraries; no macOS or Windows system binaries are bundled.

## AndroidX

The application uses AndroidX WebKit 1.18.0 and its AndroidX runtime dependencies,
copyright The Android Open Source Project, under Apache License 2.0. The complete
text is retained in `LICENSE.androidx-Apache-2.0.txt` and copied into local assets.
Upstream: <https://developer.android.com/jetpack/androidx/releases/webkit>.

AndroidX Test Runner/Core 1.7.0 and JUnit extension 1.3.0 are used only in the
instrumentation test APK, not the distributed release application. They are also
supplied under Apache License 2.0.

## Build tools and application terms

Gradle, Android Gradle Plugin, Android SDK and JDK are developer build tools, not
embedded SDK installations. A separate signing handoff may contain the Android
SDK's `apksigner.jar`; its upstream notices are retained with that tool.

Love House's own source retains **PolyForm Noncommercial 1.0.0** and the **myflww**
required author notice. Those terms do not replace or restrict the upstream
third-party licences listed above. The approved Ark Pixel font, neural atlas code
and other shared product assets retain the notices in the project's root
`THIRD_PARTY_NOTICES.md` and their original licence files.
