# Python runtime license bundle

These 20 unmodified license texts come from the official python-build-standalone 20260825 full distribution for CPython 3.12.14 / aarch64-apple-darwin: 19 texts from its licenses directory plus the installed interpreter license. The archive SHA-256 was checked against upstream SHA256SUMS. Exact source URLs, checks and file hashes are in `provenance.json`.

The macOS desktop app uses the corresponding managed install runtime. Love House does not change Python features; packaging may add code signatures. The full archive executable is not claimed byte-identical to an install-only/stripped runtime. The installed Python license text, release BUILD, interpreter version and target match. Keep the original notices within the runtime itself, including pip and its vendored dependencies.

The upstream license collection includes notices for optional/platform-specific components; having a license text here does not assert that every component is linked. In particular, macOS uses libedit rather than GNU readline and has no GDBM dependency. `PYTHON.json` mentions a zlib-ng alternative license that is absent from the official full archive: this target links system zlib (tested 1.2.12), not a redistributed zlib-ng library. The shipped zlib notice is preserved.

The app’s PolyForm license does not replace these third-party licenses.
