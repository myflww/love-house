# Native iOS Simulator service-connection verification

This is a disposable QA app, not an installable iPhone release or a claim of physical-device acceptance. It executes the real `/mobile/` portal inside UIKit's WKWebView on an iOS Simulator runtime. DOM form actions are driven through WebKit's native JavaScript testing API; the HTTP, cookies, TLS, page modules, rendering and transport run in the iOS engine.

The backend is a separate checkout containing the real `MemoryHost` and `RemoteGateway`; the fixture does not imitate their endpoints. A short-lived CA signs the loopback server certificate. The first native load must reject that untrusted CA. Only then is the CA added through `simctl keychain add-root-cert`, and the normal WebKit trust path must accept it. No certificate challenge delegate or insecure HTTPS exception is installed.

The positive run verifies management login, creation of HTTPS MCP configuration without local executable paths, actual MCP status/bootstrap calls, the distinction between tools-only and automatic capture, an actual synthetic host-hook POST, exact original-text readback, rejection of another window and rejection of an Agent bearer at administrator APIs. It confirms the same saved record independently on the actual backend. It uses a known synthetic administrator value and synthetic original wording; it never reads a model key, user's library or cloud account.

Run on a Mac with Xcode and an installed iOS Simulator runtime:

```sh
bash ios-smoke/run_ios_portal_smoke.sh /absolute/path/to/real-backend-checkout /absolute/path/to/qa-output
```

The workflow's `backend_ref` must point to the actual backend changes being reviewed. The evidence records the resolved commit, Xcode, simulator runtime, JSON assertions and a native screenshot. Private CA keys and the synthetic database are excluded from uploaded evidence. A passed simulator run does not establish iPhone Safari home-screen installation, real-device networking, or compatibility with arbitrary third-party Agent clients.
