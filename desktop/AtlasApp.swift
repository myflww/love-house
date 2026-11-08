import AppKit
import WebKit
import Darwin
import UniformTypeIdentifiers

@MainActor
final class AtlasDelegate: NSObject, NSApplicationDelegate, NSToolbarDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var loading: NSStackView!
    private var statusLabel: NSTextField!
    private var process: Process?
    private var logHandle: FileHandle?
    private var readyURL: URL?
    private var serviceURL: URL?
    private var pollTimer: Timer?
    private var pollInFlight = false
    private var deadline = Date()
    private var quitting = false
    private var generation = UUID()
    private let smokeMode = CommandLine.arguments.contains("--smoke-test")
    private var smokeStage = 0
    private var smokeExitCode: Int32 = 1
    private var smokeTimer: Timer?
    private var smokeExpectedIDs: Set<String> = []
    private var smokeLibraryA = ""
    private var smokeLibraryB = ""
    private var smokeConnectionID = ""
    private var smokeConnectionToken = ""
    private var smokeControllerPort: Int?
    private var smokeVersion = ""
    private var smokeSteps: [String] = []
    private var smokeFailure = ""
    private var smokeHostReducedMotion: Bool?
    private var smokeTestedMotionStates: [String] = []
    private let smokeSession = URLSession(configuration: .ephemeral)
    private var smokeReportURL: URL? {
        guard let index = CommandLine.arguments.firstIndex(of: "--smoke-report"), index + 1 < CommandLine.arguments.count else { return nil }
        return URL(fileURLWithPath: CommandLine.arguments[index + 1])
    }
    private let files = FileManager.default
    private let appName = "爱之屋"
    private lazy var smokeDirectory = files.temporaryDirectory.appendingPathComponent("neural-atlas-native-" + UUID().uuidString)
    private lazy var dataURL: URL = {
        if smokeMode { return smokeDirectory.appendingPathComponent("data") }
        return files.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("NeuralKnowledge", isDirectory: true)
    }()
    private lazy var logURL: URL = {
        if smokeMode { return smokeDirectory.appendingPathComponent("app.log") }
        return files.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/NeuralKnowledge/app.log")
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        if smokeMode {
            // Only public update fixtures are intercepted. Memory/model API
            // requests still use the real isolated local Controller.
            let productVersion = Bundle.main.object(forInfoDictionaryKey: "LoveHouseProductVersion") as? String ?? "0.0.0"
            let fixture = Self.smokeUpdateFixture.replacingOccurrences(of: "__NATIVE_PRODUCT_VERSION__", with: productVersion)
            configuration.userContentController.addUserScript(WKUserScript(source: fixture,
                injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        configuration.userContentController.add(self, name: "saveMemoryFile")
        configuration.userContentController.add(self, name: "exportAstrBotAdapter")
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1390, height: 870),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = appName
        window.titleVisibility = .hidden
        window.minSize = NSSize(width: 900, height: 650)
        if !smokeMode { window.setFrameAutosaveName("NeuralKnowledgeMainWindow") }
        window.center()
        window.contentView = webView
        window.toolbarStyle = .unifiedCompact
        let toolbar = NSToolbar(identifier: "NeuralKnowledgeToolbar")
        toolbar.delegate = self
        toolbar.displayMode = .iconOnly
        toolbar.sizeMode = .small
        window.toolbar = toolbar

        statusLabel = NSTextField(wrappingLabelWithString: "正在启动本地知识图谱…")
        statusLabel.alignment = .center
        statusLabel.font = .systemFont(ofSize: 16, weight: .medium)
        statusLabel.maximumNumberOfLines = 8
        statusLabel.preferredMaxLayoutWidth = 650
        let retry = NSButton(title: "重新启动", target: self, action: #selector(retryServer))
        let logs = NSButton(title: "打开运行日志", target: self, action: #selector(openLogs))
        let buttons = NSStackView(views: [retry, logs])
        buttons.orientation = .horizontal
        buttons.spacing = 12
        loading = NSStackView(views: [statusLabel, buttons])
        loading.orientation = .vertical
        loading.spacing = 20
        loading.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(loading)
        NSLayoutConstraint.activate([
            loading.centerXAnchor.constraint(equalTo: webView.centerXAnchor),
            loading.centerYAnchor.constraint(equalTo: webView.centerYAnchor),
            loading.widthAnchor.constraint(lessThanOrEqualToConstant: 700),
            loading.leadingAnchor.constraint(greaterThanOrEqualTo: webView.leadingAnchor, constant: 30),
            loading.trailingAnchor.constraint(lessThanOrEqualTo: webView.trailingAnchor, constant: -30)
        ])
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startServer()
        if smokeMode {
            DispatchQueue.main.asyncAfter(deadline: .now() + 120) { [weak self] in
                guard let self = self else { return }
                print("Native WKWebView self-test timed out: \(self.statusLabel.stringValue)")
                if let log = try? String(contentsOf: self.logURL, encoding: .utf8) { print(log) }
                NSApp.terminate(nil)
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        smokeTimer?.invalidate()
        stopServer()
        if smokeMode {
            try? files.removeItem(at: smokeDirectory)
            writeSmokeReport()
            print("Native cleanup: backend stopped and temporary data removed")
            fflush(stdout)
            exit(smokeExitCode)
        }
    }

    private func buildMenu() {
        let menu = NSMenu()
        let app = NSMenuItem()
        menu.addItem(app)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于爱之屋", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        let update = appMenu.addItem(withTitle: "检查更新…", action: #selector(checkForUpdates), keyEquivalent: "")
        update.target = self
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出爱之屋", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = appMenu
        let edit = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"),
                                       ("拷贝", "copy:", "c"), ("粘贴", "paste:", "v"),
                                       ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        edit.submenu = editMenu
        menu.addItem(edit)
        let view = NSMenuItem()
        let viewMenu = NSMenu(title: "显示")
        let refresh = viewMenu.addItem(withTitle: "刷新图谱", action: #selector(refreshView), keyEquivalent: "r")
        refresh.target = self
        let fit = viewMenu.addItem(withTitle: "返回全图", action: #selector(fitGraph), keyEquivalent: "0")
        fit.target = self
        let data = viewMenu.addItem(withTitle: "打开知识库文件夹", action: #selector(openData), keyEquivalent: "")
        data.target = self
        view.submenu = viewMenu
        menu.addItem(view)
        let windows = NSMenuItem()
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(withTitle: "最小化", action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "缩放", action: #selector(NSWindow.zoom(_:)), keyEquivalent: "")
        windows.submenu = windowMenu
        menu.addItem(windows)
        NSApp.mainMenu = menu
        NSApp.windowsMenu = windowMenu
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        toolbarDefaultItemIdentifiers(toolbar)
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.flexibleSpace, .init("fit"), .init("refresh"), .init("files")]
    }

    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier identifier: NSToolbarItem.Identifier,
                 willBeInsertedIntoToolbar flag: Bool) -> NSToolbarItem? {
        let item = NSToolbarItem(itemIdentifier: identifier)
        let actions: [String: (String, String, Selector)] = [
            "fit": ("返回全图", "scope", #selector(fitGraph)),
            "refresh": ("刷新", "arrow.clockwise", #selector(refreshView)),
            "files": ("知识库文件", "folder", #selector(openData))
        ]
        guard let (label, symbol, action) = actions[identifier.rawValue] else { return nil }
        item.label = label
        item.toolTip = ["fit": "返回全图：缩放到可以看见所有可见记忆节点。", "refresh": "刷新：重新读取本地记忆与连接状态。", "files": "知识库文件：在 Finder 中打开记忆、档案与备份所在目录。"][identifier.rawValue] ?? label
        item.image = pixelToolbarImage(identifier: identifier.rawValue, fallback: symbol, label: label)
        item.target = self
        item.action = action
        return item
    }

    private func pixelToolbarImage(identifier: String, fallback symbol: String, label: String) -> NSImage? {
        guard let url = Bundle.main.url(forResource: identifier, withExtension: "png", subdirectory: "ToolbarIcons"),
              let source = NSImage(contentsOf: url) else {
            return NSImage(systemSymbolName: symbol, accessibilityDescription: label)
        }
        // Generated raster art stays colored and uses nearest-neighbor sampling,
        // so a small toolbar does not blur its deliberately stepped pixel edges.
        let icon = NSImage(size: NSSize(width: 24, height: 24), flipped: false) { bounds in
            NSGraphicsContext.saveGraphicsState()
            defer { NSGraphicsContext.restoreGraphicsState() }
            NSGraphicsContext.current?.imageInterpolation = .none
            source.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1)
            return true
        }
        icon.isTemplate = false
        return icon
    }

    @objc private func retryServer() { startServer() }
    @objc private func refreshView() {
        if let url = serviceURL { webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)) }
        else { startServer() }
    }

    @objc private func checkForUpdates() {
        webView.evaluateJavaScript("window.LoveHouseUpdates?.check()")
    }
    @objc private func fitGraph() {
        webView.evaluateJavaScript("document.getElementById('clearFocus')?.click(); document.getElementById('fitBtn')?.click();", completionHandler: nil)
    }
    @objc private func openData() { NSWorkspace.shared.open(dataURL) }
    @objc private func openLogs() { NSWorkspace.shared.open(logURL) }

    private func showStatus(_ message: String) {
        statusLabel.stringValue = message
        loading.isHidden = false
        webView.isHidden = false
    }

    private func startServer() {
        stopServer()
        generation = UUID()
        let currentGeneration = generation
        serviceURL = nil
        webView.loadHTMLString("<!doctype html><html><body style='background:#f6f8f3'></body></html>", baseURL: nil)
        showStatus("正在启动本地记忆服务…\n每个记忆库独立保存；在画面内选择库，连接的归属不会随画面切换。")
        guard let resources = Bundle.main.resourceURL else {
            showStatus("找不到应用资源，请重新构建应用。")
            return
        }
        do {
            try files.createDirectory(at: dataURL, withIntermediateDirectories: true,
                                      attributes: [.posixPermissions: 0o700])
            if smokeMode {
                // Native acceptance never calls GitHub, a model or real user data.
                let updatePreferences = dataURL.appendingPathComponent("updates.json")
                if !files.fileExists(atPath: updatePreferences.path) {
                    try Data("{\"auto_check\":false,\"channel\":\"stable\"}".utf8).write(to: updatePreferences, options: .atomic)
                }
            }
            let runtime = dataURL.appendingPathComponent(".runtime", isDirectory: true)
            try files.createDirectory(at: runtime, withIntermediateDirectories: true,
                                      attributes: [.posixPermissions: 0o700])
            readyURL = runtime.appendingPathComponent(UUID().uuidString + ".json")
            try files.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            if !files.fileExists(atPath: logURL.path) { files.createFile(atPath: logURL.path, contents: nil) }
            logHandle = try FileHandle(forWritingTo: logURL)
            try logHandle?.seekToEnd()
            let marker = "\n[\(Date())] Starting multi-library Controller\n"
            try logHandle?.write(contentsOf: Data(marker.utf8))
            let pythonHome = resources.appendingPathComponent("python", isDirectory: true)
            let backend = resources.appendingPathComponent("backend", isDirectory: true)
            let child = Process()
            child.executableURL = pythonHome.appendingPathComponent("bin/python3.12")
            child.arguments = ["-s", "-u", backend.appendingPathComponent("desktop_server.py").path,
                               "--data-dir", dataURL.path, "--ready-file", readyURL!.path,
                               "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
            child.currentDirectoryURL = backend
            var environment = ProcessInfo.processInfo.environment
            for key in ["PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "DYLD_LIBRARY_PATH"] {
                environment.removeValue(forKey: key)
            }
            environment["PYTHONHOME"] = pythonHome.path
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONNOUSERSITE"] = "1"
            child.environment = environment
            child.standardOutput = logHandle
            child.standardError = logHandle
            child.terminationHandler = { [weak self] stopped in
                DispatchQueue.main.async {
                    guard let self = self, self.process === stopped,
                          self.generation == currentGeneration, !self.quitting else { return }
                    self.pollTimer?.invalidate()
                    self.showStatus("本地服务已停止（状态 \(stopped.terminationStatus)）。\n请重新启动，或打开运行日志查看原因。")
                }
            }
            process = child
            try child.run()
            deadline = Date().addingTimeInterval(30)
            pollInFlight = false
            pollTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated { self?.checkReady(currentGeneration) }
            }
        } catch {
            stopServer()
            showStatus("无法启动本地服务：\(error.localizedDescription)\n请打开运行日志，或重新构建应用。")
        }
    }

    private func checkReady(_ token: UUID) {
        guard generation == token, let child = process, child.isRunning else { return }
        if Date() > deadline {
            stopServer()
            showStatus("本地服务启动超时。\n请重新启动，或打开日志检查资源是否完整。")
            return
        }
        guard !pollInFlight, let readyURL = readyURL,
              let data = try? Data(contentsOf: readyURL),
              let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pid = state["pid"] as? Int, pid == Int(child.processIdentifier),
              let port = (state["controller_port"] ?? state["port"]) as? Int, (1...65535).contains(port),
              let url = URL(string: "http://127.0.0.1:\(port)/") else { return }
        pollInFlight = true
        var request = URLRequest(url: url.appendingPathComponent("api/health"))
        request.timeoutInterval = 2
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            DispatchQueue.main.async {
                guard let self = self, self.generation == token else { return }
                self.pollInFlight = false
                guard let response = response as? HTTPURLResponse, response.statusCode == 200,
                      let data = data,
                      let health = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      health["ok"] as? Bool == true else { return }
                self.pollTimer?.invalidate()
                self.pollTimer = nil
                self.serviceURL = url
                if self.smokeMode { self.smokeVersion = health["version"] as? String ?? "" }
                self.webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
            }
        }.resume()
    }

    private func stopServer() {
        pollTimer?.invalidate()
        pollTimer = nil
        let old = process
        process = nil
        if let old = old, old.isRunning {
            old.terminate()
            let timeout = Date().addingTimeInterval(3)
            while old.isRunning && Date() < timeout { Thread.sleep(forTimeInterval: 0.03) }
            if old.isRunning { kill(old.processIdentifier, SIGKILL) }
            old.waitUntilExit()
        }
        if let readyURL = readyURL { try? files.removeItem(at: readyURL) }
        readyURL = nil
        try? logHandle?.close()
        logHandle = nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if webView.url?.host == "127.0.0.1" {
            loading.isHidden = true
            if smokeMode {
                smokeTimer?.invalidate()
                smokeTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
                    MainActor.assumeIsolated { self?.checkNativePage() }
                }
            }
        }
    }

    private func checkNativePage() {
        let script = "(() => { const c=document.getElementById('cv'); return {width:c?.width||0, nodes:typeof S!=='undefined'?S.nodes.length:-1, library:typeof S!=='undefined'?S.libraryId:'', changing:typeof S!=='undefined'&&S.libraryChanging, viewMode:c?.dataset.viewMode}; })()"
        webView.evaluateJavaScript(script) { [weak self] result, _ in
            guard let self = self, let page = result as? [String: Any],
                  let width = page["width"] as? Int, width > 0,
                  let nodes = page["nodes"] as? Int,
                  page["changing"] as? Bool != true else { return }
            let libraryID = page["library"] as? String ?? ""
            if self.smokeStage == 0 && nodes == 0 && libraryID == "default" && page["viewMode"] as? String == "auto" {
                self.smokeTimer?.invalidate()
                self.smokeStage = 1
                print("Native first launch: default library empty; automatic viewport; no example or connection auto-selected")
                self.exerciseController()
            } else if self.smokeStage == 2 && nodes == 0 && libraryID == self.smokeLibraryB {
                self.smokeTimer?.invalidate()
                self.smokeStage = 3
                self.verifyFixedConnection()
            } else if self.smokeStage == 4 && nodes == 4 && libraryID == self.smokeLibraryA {
                self.smokeTimer?.invalidate()
                self.smokeStage = 7
                self.verifyViewportAndRestart()
            } else if self.smokeStage == 5 && nodes == 4 && libraryID == self.smokeLibraryA {
                self.smokeTimer?.invalidate()
                self.smokeStage = 6
                self.verifyControllerRestart()
            }
        }
    }

    private func smokeRequest(_ path: String, method: String = "GET", payload: [String: Any]? = nil,
                              libraryID: String? = nil, token: String? = nil, timeout: TimeInterval = 10) async throws -> [String: Any] {
        guard let base = serviceURL, let url = URL(string: path, relativeTo: base) else {
            throw NSError(domain: "NeuralAtlasSmoke", code: 1, userInfo: [NSLocalizedDescriptionKey: "Missing Controller URL"])
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let id = libraryID { request.setValue(id, forHTTPHeaderField: "X-NKB-Library") }
        if let token = token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let payload = payload {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        }
        let (data, response) = try await smokeData(request, management: token == nil)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "NeuralAtlasSmoke", code: (response as? HTTPURLResponse)?.statusCode ?? 0,
                          userInfo: [NSLocalizedDescriptionKey: "Controller request failed: \(path)"])
        }
        return object
    }

    private func smokeData(_ original: URLRequest, management: Bool = true) async throws -> (Data, URLResponse) {
        guard let base = serviceURL, let url = original.url, url.scheme == "http",
              url.host == "127.0.0.1", url.port == base.port else {
            throw NSError(domain: "NeuralAtlasSmoke", code: 3, userInfo: [NSLocalizedDescriptionKey: "Native request escaped the isolated Controller"])
        }
        var request = original
        request.setValue(base.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")), forHTTPHeaderField: "Origin")
        if management {
            let cookies: [HTTPCookie] = await withCheckedContinuation { continuation in
                webView.configuration.websiteDataStore.httpCookieStore.getAllCookies { continuation.resume(returning: $0) }
            }
            let session = cookies.filter { $0.name == "LoveHouseUI" && $0.domain == "127.0.0.1" }
            try requireSmoke(!session.isEmpty, "WKWebView management session was not established")
            for (key, value) in HTTPCookie.requestHeaderFields(with: session) { request.setValue(value, forHTTPHeaderField: key) }
        }
        return try await smokeSession.data(for: request)
    }

    private func writeSmokeReport() {
        guard let destination = smokeReportURL else { return }
        let cleaned = !files.fileExists(atPath: smokeDirectory.path)
        let report: [String: Any] = ["ok": smokeExitCode == 0 && cleaned, "version": smokeVersion,
            "process_complete": process == nil, "stage": smokeStage, "steps": smokeSteps, "failure": smokeFailure,
            "actual_host_reduce_motion": smokeHostReducedMotion.map { $0 as Any } ?? NSNull(),
            "tested_synthetic_motion_states": smokeTestedMotionStates,
            "isolation": ["temporary_data": true, "data_removed": cleaned, "uses_user_data": false,
                          "real_provider_calls": false, "release_network": false],
            "startup_update_source": "synthetic_public_release_fixture"]
        do {
            try files.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys, .prettyPrinted]).write(to: destination, options: .atomic)
        } catch { print("Native smoke report could not be written") }
    }

    private static let smokeUpdateFixture = #"""
    (()=>{
      const original=window.fetch.bind(window),state={calls:[],checked:false};window.__nativeSmokeUpdates=state;
      window.fetch=async(input,options={})=>{
        const url=new URL(typeof input==='string'?input:input.url,location.href);
        if(url.origin===location.origin&&['/api/updates','/api/updates/check'].includes(url.pathname)){
          state.calls.push(url.pathname);if(url.pathname.endsWith('/check'))state.checked=true;
          const release={version:'99.0.0',tag:'v99.0.0',notes:'Synthetic native startup update notice.',prerelease:false,
            url:'https://github.com/myflww/love-house/releases/tag/v99.0.0',
            asset_url:'https://github.com/myflww/love-house/releases/download/v99.0.0/LoveHouse-macOS-arm64.zip'};
          return new Response(JSON.stringify({current_version:'__NATIVE_PRODUCT_VERSION__',platform:'macos',architecture:'arm64',
            settings:{auto_check:true,channel:'stable'},status:state.checked?'available':'not_checked',checking:false,
            available:state.checked,checked_at:state.checked?1700000000:null,release:state.checked?release:null,retry_after:0}),
            {status:200,headers:{'Content-Type':'application/json'}});
        }
        return original(input,options);
      };
    })();
    """#

    private func requireSmoke(_ condition: Bool, _ message: String) throws {
        if !condition { throw NSError(domain: "NeuralAtlasSmoke", code: 2, userInfo: [NSLocalizedDescriptionKey: message]) }
    }

    private func failSmoke(_ error: Error) {
        print("Native desktop self-test failed: \(error.localizedDescription)")
        let details = error as NSError
        // WKError otherwise replaces our fixed acceptance failures with the
        // generic "A JavaScript exception occurred". Only isolated synthetic
        // smoke probes use this path; no provider text or cookie is reported.
        if let message = details.userInfo["WKJavaScriptExceptionMessage"] as? String {
            smokeFailure = String(message.prefix(500))
            print("Native JavaScript failure: \(smokeFailure)")
        } else {
            smokeFailure = String(error.localizedDescription.prefix(500))
        }
        NSApp.terminate(nil)
    }

    private func setSmokeLibrary(_ id: String, alreadySelected: Bool = false) async throws {
        _ = try await webView.callAsyncJavaScript(
            "await refreshLibraries(); await selectMemoryLibrary(id,{alreadySelected}); return true;",
            arguments: ["id": id, "alreadySelected": alreadySelected], in: nil, contentWorld: .page)
        smokeTimer?.invalidate()
        smokeTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.checkNativePage() }
        }
    }

    @discardableResult
    private func captureSmokeTurn(_ id: String, user: String) async throws -> [String: Any] {
        let payload: [String: Any] = ["session_id": "native-session", "event_id": id, "event_type": "turn/end",
            "record": ["schema": "deepseek-harness-event/v1",
                       "raw_event": ["type": "turn/end", "attachments": [["id": "native-temporary-attachment"]]],
                       "normalized": ["type": "turn", "status": "complete", "turn_id": id,
                                      "user": user, "assistant": "原始助手回复（临时测试）"]]]
        let result = try await smokeRequest("api/connections/\(smokeConnectionID)/events", method: "POST",
                                            payload: payload, token: smokeConnectionToken)
        try requireSmoke(result["accepted"] as? Bool == true, "Completed host event was not accepted")
        return result
    }

    private func exerciseController() {
        Task {
            do {
                let libraries = try await smokeRequest("api/libraries")
                try requireSmoke(libraries["selected_id"] as? String == "default", "First GUI selection was not default")
                let organizerUI = try await webView.callAsyncJavaScript(
                    "setPanelOpen('organizerPanel',true,{focus:false}); await refreshOrganizer(); const panel=document.getElementById('organizerPanel'); const enabled=document.getElementById('organizerEnabled'); const options=window.LoveHouseOrganizerModels?.settingsPayload(); const result={open:!!panel&&!panel.hidden, enabled:enabled?.checked===true, preview:!!document.getElementById('previewOrganizer'), models:!!document.getElementById('organizerReadModels'), defaults:options?.max_input_chars===0&&options?.context_window===0&&options?.max_output_tokens===0&&options?.reasoning_effort==='auto', noDailyLimit:!document.getElementById('organizerCallLimit')&&!document.getElementById('organizerCharLimit')}; setPanelOpen('organizerPanel',false,{restore:false}); return result;",
                    arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                try requireSmoke(organizerUI?["open"] as? Bool == true && organizerUI?["enabled"] as? Bool == false && organizerUI?["preview"] as? Bool == true, "Organizer panel was unavailable or unexpectedly enabled")
                try requireSmoke(organizerUI?["models"] as? Bool == true && organizerUI?["defaults"] as? Bool == true && organizerUI?["noDailyLimit"] as? Bool == true, "Organizer did not expose automatic model capabilities without daily ceilings")
                let organizerPreview = try await smokeRequest("api/organizer/preview", method: "POST", payload: [:])
                try requireSmoke(organizerPreview["will_call_model"] as? Bool == false, "Organizer preview attempted a model call")
                print("Native organizer: real panel opens, starts disabled, preview performs no model call")
                smokeSteps.append("organizer_auto_capabilities_no_model_call")
                let newUI = try await webView.callAsyncJavaScript(
                    "return {importChat:!!document.getElementById('dialogueImportBtn'),handoff:!!document.getElementById('windowHandoffBtn'),updates:!!document.getElementById('checkForUpdates'),retention:!!document.getElementById('memoryRetentionBtn'),rules:!!document.getElementById('organizerRulesBtn')};",
                    arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                try requireSmoke(newUI?["importChat"] as? Bool == true && newUI?["handoff"] as? Bool == true && newUI?["updates"] as? Bool == true, "New desktop controls are missing")
                try requireSmoke(newUI?["retention"] as? Bool == true && newUI?["rules"] as? Bool == true, "Adaptive memory controls are missing")
                let retention = try await smokeRequest("api/retention")
                try requireSmoke(retention["node_limit"] is NSNull && retention["count_eviction"] as? Bool == false && retention["automatic_deletion"] as? Bool == false, "Personal library still has count eviction or timed deletion")
                let ruleView = try await webView.callAsyncJavaScript(
                    "await window.LoveHouseOrganizerRules.open(); const d=document.getElementById('organizerRulesDialog'); const text=document.getElementById('organizerFullGuide').textContent; const result={open:d.open,guide:text.includes('统一保存期限')&&text.includes('逐字')}; d.close(); return result;",
                    arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                try requireSmoke(ruleView?["open"] as? Bool == true && ruleView?["guide"] as? Bool == true, "Organizer guide is not readable in the actual native UI")
                print("Native 0.7: unlimited personal archive, no TTL, adaptive settings and exact organizer guide verified without model calls")
                smokeSteps.append("adaptive_retention_and_read_only_rules")
                let lifeUI = try await webView.callAsyncJavaScript(
                    "return {sources:!!document.getElementById('agentSourcesBtn'),experiences:!!document.getElementById('experienceLibraryBtn'),plugin:!!document.getElementById('exportAstrBotPlugin')};",
                    arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                try requireSmoke(lifeUI?["sources"] as? Bool == true && lifeUI?["experiences"] as? Bool == true && lifeUI?["plugin"] as? Bool == true, "Experience/source controls are missing")
                let life = try await smokeRequest("api/experiences")
                try requireSmoke(life["read_only"] as? Bool == true && life["will_call_model"] as? Bool == false, "Experience view is not read-only")
                let source = try await smokeRequest("api/agent/sources", method:"POST", payload:["name":"原生合成来源","adapter":"sdk","runtime_agent_id":"SYNTHETIC-NATIVE-FISH","platforms":["qq","browser"]])
                try requireSmoke(source["config_ready"] as? Bool == true && (source["source"] as? [String:Any])?["full_activity_coverage_verified"] as? Bool == false, "Source configuration claimed unsupported coverage")
                let packageURL = serviceURL!.appendingPathComponent("api/adapters/astrbot/package")
                let (pluginData, pluginResponse) = try await smokeData(URLRequest(url: packageURL))
                let bundled = try Data(contentsOf:Bundle.main.resourceURL!.appendingPathComponent("Adapters/LoveHouse-AstrBot-0.3.0-experimental.zip"))
                try requireSmoke((pluginResponse as? HTTPURLResponse)?.statusCode == 200 && pluginData == bundled && pluginData.prefix(2) == Data([0x50,0x4b]), "Experimental adapter export bytes differ from the bundled source package")
                print("Native 0.8: human experience/source controls, fixed-source registration and exact experimental plugin ZIP verified; no external Agent or model used")
                smokeSteps.append("management_session_source_registration_astrbot_030_export")
                let updates = try await smokeRequest("api/updates")
                try requireSmoke(updates["auto_install"] as? Bool == false && (updates["settings"] as? [String: Any])?["auto_check"] as? Bool == false, "Isolated update preferences did not prevent network checks")
                let startup = try await webView.callAsyncJavaScript("""
                    const end=performance.now()+10000;
                    while(!document.getElementById('updateAvailableDialog')?.open){if(performance.now()>end)throw new Error('Native startup update notice missing');await new Promise(r=>setTimeout(r,40));}
                    const d=document.getElementById('updateAvailableDialog'),fixture=window.__nativeSmokeUpdates;
                    const result={opened:d.open,checks:fixture.calls.filter(path=>path==='/api/updates/check').length,
                      text:document.getElementById('updateAvailableVersions').textContent.includes('99.0.0'),
                      link:document.getElementById('updateAvailableDownload').href.endsWith('/LoveHouse-macOS-arm64.zip')};
                    document.getElementById('deferUpdateAvailable').click();return {...result,closed:!d.open};
                    """, arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                try requireSmoke(startup?["opened"] as? Bool == true && startup?["checks"] as? Int == 1 && startup?["text"] as? Bool == true && startup?["link"] as? Bool == true && startup?["closed"] as? Bool == true, "Startup update fixture did not complete the real native notice flow")
                smokeSteps.append("startup_fresh_check_and_update_notice_fixture")
                let rescue = try await smokeRequest("api/libraries", method: "POST", payload: ["name":"原生聊天导入自检库"])
                let rescueID = (rescue["library"] as? [String: Any])?["id"] as? String ?? ""
                try requireSmoke(!rescueID.isEmpty, "Historical import test library missing")
                let oldChat = "[{\"role\":\"user\",\"content\":\"旧窗口的测试约定\"},{\"role\":\"assistant\",\"content\":\"保留这段测试原文\"}]"
                let chatPreview = try await smokeRequest("api/dialogue-import/preview", method: "POST", payload: ["content": oldChat], libraryID: rescueID)
                try requireSmoke(chatPreview["read_only"] as? Bool == true && chatPreview["added"] as? Int == 1, "Historical chat preview failed")
                let chatImport = try await smokeRequest("api/dialogue-import/apply", method: "POST", payload: ["content": oldChat, "confirm": true, "expected_fingerprint": chatPreview["fingerprint"] as? String ?? ""], libraryID: rescueID)
                try requireSmoke(chatImport["saved"] as? Bool == true && chatImport["added"] as? Int == 1, "Historical chat was not saved")
                let handoff = try await smokeRequest("api/memory/handoff", method: "POST", payload: ["profile":"S"], libraryID: rescueID)
                try requireSmoke(handoff["read_only"] as? Bool == true && handoff["automatic_recording"] as? Bool == false && (handoff["text"] as? String ?? "").contains("旧窗口的测试约定"), "Bounded new-window packet failed")
                print("Native 0.6: historical chat preview/import, scoped handoff and update controls verified; no model or release-network calls")
                smokeSteps.append("historical_role_import_and_scoped_handoff")
                let a = try await smokeRequest("api/libraries", method: "POST", payload: ["name": "原生自检库甲"])
                let b = try await smokeRequest("api/libraries", method: "POST", payload: ["name": "原生自检库乙"])
                smokeLibraryA = (a["library"] as? [String: Any])?["id"] as? String ?? ""
                smokeLibraryB = (b["library"] as? [String: Any])?["id"] as? String ?? ""
                try requireSmoke(!smokeLibraryA.isEmpty && !smokeLibraryB.isEmpty, "Library registry did not return IDs")
                let created = try await smokeRequest("api/connections", method: "POST", payload: [
                    "name": "原生自动存档测试", "host": "harness", "library_id": smokeLibraryA, "session_scope": "connection"])
                smokeConnectionID = (created["connection"] as? [String: Any])?["id"] as? String ?? ""
                smokeConnectionToken = (created["config"] as? [String: Any])?["connectionToken"] as? String ?? ""
                try requireSmoke(!smokeConnectionToken.isEmpty, "Connection token missing")
                let initialPersona = try await smokeRequest("api/persona", libraryID: smokeLibraryA)
                try requireSmoke(initialPersona["enabled"] as? Bool == true && initialPersona["learning_enabled"] as? Bool == true && (initialPersona["manual"] as? String ?? "").isEmpty, "New personal library did not start with enabled empty persona learning")
                try await captureSmokeTurn("persona", user: "这是普通合成聊天资料，今天一起看看星空。")
                try await captureSmokeTurn("style-1", user: "这个窗口保存第一条合成约定。")
                try await captureSmokeTurn("style-2", user: "这个窗口保存第二条合成约定。")
                let persona = try await smokeRequest("api/persona", libraryID: smokeLibraryA)
                try requireSmoke((persona["manual"] as? String ?? "").isEmpty && (persona["learned"] as? [String: Any] ?? [:]).isEmpty && (persona["formed_traits"] as? [[String: Any]] ?? []).isEmpty, "Chat material fabricated manual or model-learned persona without a model")
                let importedPersona = try await smokeRequest("api/persona/import", method: "POST", payload: ["text":"原生测试明确人格原文", "source":["origin":"native_smoke_explicit_import"], "enabled":true, "expected_revision":persona["revision"] as? Int ?? 0], libraryID:smokeLibraryA)
                try requireSmoke((importedPersona["manual"] as? String ?? "") == "原生测试明确人格原文", "Explicit persona API import was not retained")
                smokeSteps.append("persona_defaults_roles_and_explicit_import_boundary")
                smokeStage = 2
                try await setSmokeLibrary(smokeLibraryB, alreadySelected: true)
            } catch { failSmoke(error) }
        }
    }

    private func verifyFixedConnection() {
        Task {
            do {
                let oldPID = process?.processIdentifier
                let captured = try await captureSmokeTurn("after-gui-switch", user: "切换画面后仍归属甲库的原文")
                // accepted acknowledges the durable receipt, not necessarily
                // graph application: a concurrent retry may hold _apply_lock.
                // Wait for exactly the original four IDs without weakening the
                // isolation assertions or accepting an extra node.
                let receiptStates: Set<String> = ["pending", "retry", "saved", "archived", "forgotten"]
                let acknowledgement = captured["status"] as? String ?? "unknown"
                let ackStatus = receiptStates.contains(acknowledgement) ? acknowledgement : "unknown"
                let deadline = ProcessInfo.processInfo.systemUptime + 10
                var a = try await smokeRequest("api/graph", libraryID: smokeLibraryA, timeout: max(0.1, deadline - ProcessInfo.processInfo.systemUptime))
                while true {
                    let count = Set((a["nodes"] as? [[String: Any]] ?? []).compactMap { $0["id"] as? String }).count
                    try requireSmoke(count <= 4, "Connection did not stay bound to library A (expected 4 unique IDs, observed \(count); receipt acknowledgement \(ackStatus))")
                    if count == 4 { break }
                    if ProcessInfo.processInfo.systemUptime >= deadline {
                        let activity = try? await smokeRequest("api/activity", libraryID: smokeLibraryA, timeout: 1)
                        let events = activity?["events"] as? [[String: Any]] ?? []
                        let receiptID = captured["receipt_id"] as? String ?? ""
                        let status = events.first { $0["id"] as? String == receiptID }?["status"] as? String ?? "unavailable"
                        let durableStatus = receiptStates.contains(status) ? status : "unavailable"
                        try requireSmoke(count == 4, "Connection did not stay bound to library A (expected 4 unique IDs, observed \(count) after 10s; receipt acknowledgement \(ackStatus), durable receipt \(durableStatus))")
                    }
                    try await Task.sleep(nanoseconds: 100_000_000)
                    a = try await smokeRequest("api/graph", libraryID: smokeLibraryA, timeout: max(0.1, deadline - ProcessInfo.processInfo.systemUptime))
                }
                let b = try await smokeRequest("api/graph", libraryID: smokeLibraryB)
                let fallback = try await smokeRequest("api/graph")
                smokeExpectedIDs = Set((a["nodes"] as? [[String: Any]] ?? []).compactMap { $0["id"] as? String })
                try requireSmoke(smokeExpectedIDs.count == 4, "Connection did not stay bound to library A")
                try requireSmoke((b["nodes"] as? [[String: Any]] ?? []).isEmpty, "GUI library B was contaminated")
                try requireSmoke((fallback["nodes"] as? [[String: Any]] ?? []).isEmpty, "Unscoped API stopped defaulting to default")
                try requireSmoke(oldPID == process?.processIdentifier, "GUI selection restarted the backend")
                print("Native Controller: registry two libraries; completed events; GUI switch keeps connection binding; persona import/learning OK")
                smokeSteps.append("fixed_connection_window_and_library_isolation")
                smokeStage = 4
                try await setSmokeLibrary(smokeLibraryA)
            } catch { failSmoke(error) }
        }
    }

    private static let smokeControlHelper = #"""
    const nativeVisible=e=>!!e&&!e.hidden&&!e.closest('[hidden]')&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'&&e.getClientRects().length>0;
    const nativeClick=async id=>{
     const e=document.getElementById(id);if(!e)throw Error('workspace_control');
     if(!nativeVisible(e)){
      const menu=e.closest('#workspaceDisplayMenu,#workspaceAddMenu');
      if(menu){const trigger=document.getElementById(menu.id==='workspaceDisplayMenu'?'workspaceDisplayButton':'workspaceAddButton');if(!nativeVisible(trigger))throw Error('workspace_control');trigger.click();}
      else if(e.closest('#sidebar')){const trigger=document.getElementById('menuBtn');if(!nativeVisible(trigger))throw Error('workspace_control');trigger.click();}
     }
     e.scrollIntoView({block:'nearest'});
     const r=e.getBoundingClientRect();if(!nativeVisible(e)||e.disabled||r.right<=0||r.left>=innerWidth||r.bottom<=0||r.top>=innerHeight)throw Error('workspace_control');
     e.click();await new Promise(resolve=>setTimeout(resolve,0));
    };
    """#

    private func verifyGuidedWorkspace() async throws {
        guard let resource = Bundle.main.url(forResource: "NativeWorkspaceSmoke", withExtension: "js") else {
            throw NSError(domain: "NeuralAtlasSmoke", code: 4, userInfo: [NSLocalizedDescriptionKey: "Shared native workspace probe is missing"])
        }
        let script = try String(contentsOf: resource, encoding: .utf8)
        let result = try await webView.callAsyncJavaScript(script, arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
        let checks = ["navigation", "no_overflow", "add_and_import_menu", "escape_focus_restored", "add_cancel_read_only",
                      "display_menu", "experience_scope", "commitment_scope", "connection_scope", "model_adoption_not_claimed",
                      "idle_review_opt_in", "idle_review_preview_read_only", "statement_history_read_only", "source_directory_read_only", "read_only"]
        for key in checks {
            try requireSmoke(result?[key] as? Bool == true, "Native workspace check failed: \(key)")
        }
        try requireSmoke(result?["model_calls"] as? Int == 0, "Native workspace probe attempted a model call")
        smokeSteps.append("guided_workspace_visible_navigation_menus_focus_and_scoped_views")
        smokeSteps.append("idle_review_default_opt_in_and_preview_no_model")
        smokeSteps.append("statement_history_and_source_directory_read_only")
        print("Native workspace: labelled navigation, visible menus, Escape focus, read-only experiences and connection status verified")
    }

    private func verifyViewportAndRestart() {
        Task {
            do {
                try await verifyGuidedWorkspace()
                smokeSteps.append("viewport_probe_started")
                let result = try await webView.callAsyncJavaScript(Self.smokeControlHelper + """
                    try {
                    const c=document.getElementById('cv');
                    const wait=async(predicate)=>{const end=performance.now()+6000;while(!predicate()){if(performance.now()>end)throw new Error('Native viewport did not settle '+JSON.stringify({mode:S.view.mode,sim:S.sim,visible:S.visible.length,hidden:document.hidden,target:!!S.view.target,k:S.cam.k,targetK:S.view.target?.k}));await new Promise(r=>setTimeout(r,30));}};
                    const paint=async()=>{schedule();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));};
                    await wait(()=>S.view.mode==='auto'&&S.sim===0&&S.view.target&&Math.abs(Math.log(S.cam.k/S.view.target.k))<.01);
                    await paint();
                    const initial={mode:c.dataset.viewMode,scale:Number(c.dataset.viewScale),count:Number(c.dataset.viewCount),core:Number(c.dataset.nodeCoreMin),art:S.art,labels:c.dataset.labelMode};
                    document.getElementById('zoomIn').click();await paint();
                    const manual={mode:c.dataset.viewMode,x:S.cam.x,y:S.cam.y,k:S.cam.k};
                    await reload();await paint();
                    const preserved=c.dataset.viewMode==='manual'&&Math.abs(S.cam.k-manual.k)<.000001&&Math.abs(S.cam.x-manual.x)<.000001&&Math.abs(S.cam.y-manual.y)<.000001;
                    document.getElementById('labelToggle').click();await paint();
                    const labelsOn=c.dataset.labelMode==='auto';
                    document.getElementById('labelToggle').click();await paint();
                    const labelsOff=c.dataset.labelMode==='focus';
                    document.getElementById('fitBtn').click();await paint();
                    await wait(()=>S.view.mode==='auto'&&c.dataset.viewMode==='auto'&&!!S.view.target);
                    return {initial,manualMode:manual.mode,preserved,restored:c.dataset.viewMode,labelsOn,labelsOff};
                    } catch(error) { return {nativeProbeFailure:String(error?.message||error),probe:'viewport'}; }
                    """, arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                try requireSmoke(result?["nativeProbeFailure"] == nil, "Native viewport JavaScript: \(result?["nativeProbeFailure"] as? String ?? "unknown")")
                let initial = result?["initial"] as? [String: Any]
                try requireSmoke(initial?["mode"] as? String == "auto" && initial?["count"] as? Int == 4,
                                 "Four-node graph did not start in automatic viewport")
                try requireSmoke((initial?["scale"] as? Double ?? 0) > 0.8, "Sparse graph remained too far away")
                if initial?["art"] as? Bool == true {
                    try requireSmoke((initial?["core"] as? Double ?? 0) >= 9, "Sparse WebGL nodes were not clearly sized")
                }
                try requireSmoke(initial?["labels"] as? String == "focus" && result?["labelsOn"] as? Bool == true && result?["labelsOff"] as? Bool == true,
                                 "Node labels did not default to focus or toggle reliably")
                try requireSmoke(result?["manualMode"] as? String == "manual" && result?["preserved"] as? Bool == true,
                                 "Zoom button failed to lock the manual viewport across graph refresh")
                try requireSmoke(result?["restored"] as? String == "auto", "Fit button did not restore automatic viewport")
                smokeSteps.append("viewport_zoom_reload_labels_fit_verified")
                print("Native viewport controls: automatic view, manual zoom/reload, labels and fit verified")
                let rotation = try await webView.callAsyncJavaScript(Self.smokeControlHelper + """
                    const c=document.getElementById('cv'),art=document.getElementById('artCanvas');
                    const originalMatchMedia=globalThis.matchMedia,motionQuery='(prefers-reduced-motion: reduce)';
                    const actualHostReducedMotion=!!originalMatchMedia.call(globalThis,motionQuery).matches;
                    const testedSyntheticMotionStates=[],oldPaused=S.paused,oldSelected=S.selected,oldHover=S.hover;
                    try {
                    if(!S.art||!artRenderer?.painter)throw new Error('Approved native atlas is unavailable');
                    const wait=async(predicate)=>{const end=performance.now()+5000;while(!predicate()){if(performance.now()>end)throw new Error('Native atlas rotation did not settle '+JSON.stringify({reason:art.dataset.autoRotateReason,art:S.art,mode:S.graphMode,paused:S.paused,hidden:document.hidden}));await new Promise(r=>setTimeout(r,30));}};
                    const pause=()=>new Promise(r=>setTimeout(r,350));S.paused=false;select(null);S.hover=null;schedule();
                    await wait(()=>art.dataset.autoRotateReason===(actualHostReducedMotion?'reduced-motion':'rotating'));
                    const hostYaw=Number(art.dataset.autoRotateYaw);await pause();
                    const hostPreferenceRespected=actualHostReducedMotion?Number(art.dataset.autoRotateYaw)===hostYaw:Number(art.dataset.autoRotateYaw)>hostYaw;
                    if(!hostPreferenceRespected)throw new Error('Native system motion preference was not respected');
                    // CI desktops may request reduced motion. Only this disposable
                    // smoke probe controls this one media query; the real renderer,
                    // frames and DOM handlers still exercise both preference states.
                    let reduced=false;
                    globalThis.matchMedia=function(query){
                      const result=originalMatchMedia.apply(globalThis,arguments);
                      return query===motionQuery?new Proxy(result,{get(target,key){const value=key==='matches'?reduced:Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;}}):result;
                    };
                    S.hover=S.nodes[0].id;
                    c.dispatchEvent(new PointerEvent('pointerenter',{pointerId:919,pointerType:'mouse',clientX:c.getBoundingClientRect().left+10,clientY:c.getBoundingClientRect().top+10}));schedule();
                    await wait(()=>art.dataset.autoRotateReason==='rotating');const before=Number(art.dataset.autoRotateYaw);await pause();
                    const hoverRotates=Number(art.dataset.autoRotateYaw)>before&&art.dataset.autoRotateHovered==='true';
                    const row=document.querySelector('#nodeList .node-row');if(!row)throw new Error('Native node row missing');if(!nativeVisible(row))await nativeClick('menuBtn');row.scrollIntoView({block:'nearest'});if(!nativeVisible(row))throw new Error('Native node row is hidden');
                    row.click();await wait(()=>!!S.selected&&art.dataset.autoRotateReason==='selected');const held=Number(art.dataset.autoRotateYaw);await pause();
                    const selectionStops=Math.abs(Number(art.dataset.autoRotateYaw)-held)<.000001;
                    select(null);await wait(()=>art.dataset.autoRotateReason==='rotating');const resume=Number(art.dataset.autoRotateYaw);await pause();
                    const resumes=Number(art.dataset.autoRotateYaw)>resume;
                    if(!hoverRotates||!selectionStops||!resumes)throw new Error('Native hover, node selection or resume behavior failed');
                    testedSyntheticMotionStates.push('no-preference');
                    reduced=true;schedule();await wait(()=>art.dataset.autoRotateReason==='reduced-motion'&&art.dataset.autoRotate==='false');
                    const reducedYaw=Number(art.dataset.autoRotateYaw);await pause();
                    const reducedMotionRespected=Number(art.dataset.autoRotateYaw)===reducedYaw;
                    if(!reducedMotionRespected)throw new Error('Native reduced-motion preference failed to stop rotation');
                    testedSyntheticMotionStates.push('reduce');
                    return {painter:art.dataset.painter,actualHostReducedMotion,hostPreferenceRespected,testedSyntheticMotionStates,hoverRotates,selectionStops,resumes,reducedMotionRespected};
                    } catch(error) { return {nativeProbeFailure:String(error?.message||error),probe:'rotation',actualHostReducedMotion,testedSyntheticMotionStates}; }
                    finally { globalThis.matchMedia=originalMatchMedia;select(oldSelected);c.dispatchEvent(new PointerEvent('pointerleave',{pointerId:919,pointerType:'mouse'}));S.hover=oldHover;S.paused=oldPaused;schedule(); }
                    """, arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                smokeHostReducedMotion = rotation?["actualHostReducedMotion"] as? Bool
                smokeTestedMotionStates = rotation?["testedSyntheticMotionStates"] as? [String] ?? []
                try requireSmoke(rotation?["nativeProbeFailure"] == nil, "Native rotation JavaScript: \(rotation?["nativeProbeFailure"] as? String ?? "unknown")")
                try requireSmoke(rotation?["painter"] as? String == "approved-canvas" && rotation?["hoverRotates"] as? Bool == true && rotation?["selectionStops"] as? Bool == true && rotation?["resumes"] as? Bool == true, "Native atlas did not rotate on hover, suspend on selection and resume after deselection")
                try requireSmoke(rotation?["hostPreferenceRespected"] as? Bool == true && rotation?["reducedMotionRespected"] as? Bool == true && smokeTestedMotionStates == ["no-preference", "reduce"], "Native system and synthetic motion preferences were not both verified")
                print("Native viewport: sparse four-node close view; manual zoom survives real graph reload; fit restores auto; node labels toggle without writes")
                smokeSteps.append("approved_atlas_rotation_selection_hover_and_viewport")
                smokeStage = 5
                smokeControllerPort = serviceURL?.port
                startServer()
            } catch { failSmoke(error) }
        }
    }

    private func verifyControllerRestart() {
        Task {
            do {
                try requireSmoke(smokeControllerPort == serviceURL?.port, "Controller URL changed across clean restart")
                let graph = try await smokeRequest("api/graph", libraryID: smokeLibraryA)
                let nodes = graph["nodes"] as? [[String: Any]] ?? []
                try requireSmoke(Set(nodes.compactMap { $0["id"] as? String }) == smokeExpectedIDs, "Raw turn IDs did not survive restart")
                try requireSmoke(nodes.allSatisfy { ($0["meta"] as? [String: Any])?["assistant_reply"] as? String == "原始助手回复（临时测试）" }, "Assistant originals missing")
                let activity = try await smokeRequest("api/activity", libraryID: smokeLibraryA)
                try requireSmoke((activity["events"] as? [[String: Any]] ?? []).count == 4, "Durable activity journal missing")
                let connections = try await smokeRequest("api/connections")
                let connection = (connections["connections"] as? [[String: Any]] ?? []).first { $0["id"] as? String == smokeConnectionID }
                try requireSmoke(connection?["library_id"] as? String == smokeLibraryA, "Persisted binding changed")
                let persona = try await smokeRequest("api/persona", libraryID: smokeLibraryA)
                try requireSmoke((persona["manual"] as? String ?? "") == "原生测试明确人格原文" && persona["enabled"] as? Bool == true, "Explicit persona did not survive native restart")
                print("Native restart: stable Controller port, isolated graph, original dialogue and activity restored")
                smokeSteps.append("clean_restart_originals_binding_and_persona")
                smokeExitCode = 0
                NSApp.terminate(nil)
            } catch { failSmoke(error) }
        }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        guard frame.request.url?.host == "127.0.0.1", frame.request.url?.port == serviceURL?.port else {
            completionHandler(nil)
            return
        }
        let panel = NSOpenPanel()
        panel.title = "选择聊天记录、笔记或记忆分享包"
        panel.message = "只读取你在此明确选择的文件，不扫描其他文件或文件夹。"
        panel.prompt = "选择文件"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.allowedContentTypes = ["md", "markdown", "txt", "rst", "json"].compactMap {
            UTType(filenameExtension: $0, conformingTo: .text)
        }
        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    // Only the app's own main frame may request a local, user-selected export.
    // The page never supplies an absolute destination or obtains filesystem access.
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "exportAstrBotAdapter" {
            exportAstrBotAdapter(message)
            return
        }
        guard message.name == "saveMemoryFile", message.frameInfo.isMainFrame,
              let origin = message.frameInfo.request.url, origin.scheme == "http",
              origin.host == "127.0.0.1", origin.port == serviceURL?.port,
              let body = message.body as? [String: Any],
              let requestID = body["request_id"] as? String,
              requestID.range(of: "^[a-zA-Z0-9_-]{1,80}$", options: .regularExpression) != nil,
              let name = body["filename"] as? String, name.count <= 180,
              !name.contains("/"), !name.contains("\\"),
              (name.hasSuffix(".json") || name.hasSuffix(".md")),
              let content = body["content"] as? String,
              let bytes = content.data(using: .utf8), bytes.count <= 256 * 1024 * 1024 else { return }
        let panel = NSSavePanel()
        panel.title = "保存这个记忆库的分享文件"
        panel.message = "文件包含该库的个人记忆。保存后由你决定分享给谁；不会自动上传。"
        panel.nameFieldStringValue = name
        panel.allowedContentTypes = name.hasSuffix(".json") ? [.json] : [UTType(filenameExtension: "md") ?? .plainText]
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            var result: [String: Any] = ["request_id": requestID, "saved": false, "cancelled": response != .OK]
            if response == .OK, let url = panel.url {
                do { try bytes.write(to: url, options: .atomic); result["saved"] = true }
                catch { result["error"] = "文件未能保存，请检查目标文件夹与可用空间。" }
            }
            guard let json = try? JSONSerialization.data(withJSONObject: result),
                  let literal = String(data: json, encoding: .utf8) else { return }
            self.webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('lovehouse-file-saved',{detail:\(literal)}));", completionHandler: nil)
        }
    }

    private func exportAstrBotAdapter(_ message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame,
              let origin = message.frameInfo.request.url, origin.scheme == "http",
              origin.host == "127.0.0.1", origin.port == serviceURL?.port,
              let body = message.body as? [String: Any],
              let requestID = body["request_id"] as? String,
              requestID.range(of: "^[a-zA-Z0-9_-]{1,80}$", options: .regularExpression) != nil,
              let resource = Bundle.main.resourceURL?.appendingPathComponent("Adapters/LoveHouse-AstrBot-0.3.0-experimental.zip"),
              let data = try? Data(contentsOf: resource), data.count <= 4 * 1024 * 1024 else { return }
        let panel = NSSavePanel()
        panel.title = "导出 AstrBot 实验插件"
        panel.message = "插件不包含个人记忆或绑定凭证。请按包内 README 安装，并在实际宿主核验。"
        panel.nameFieldStringValue = "LoveHouse-AstrBot-0.3.0-experimental.zip"
        panel.allowedContentTypes = [.zip]
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            var result: [String: Any] = ["request_id":requestID,"saved":false,"cancelled":response != .OK]
            if response == .OK, let url = panel.url {
                do { try data.write(to:url,options:.atomic); result["saved"] = true }
                catch { result["error"] = "插件未能保存，请检查目标文件夹。" }
            }
            guard let json = try? JSONSerialization.data(withJSONObject:result),
                  let literal = String(data:json,encoding:.utf8) else { return }
            self.webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('lovehouse-adapter-exported',{detail:\(literal)}));",completionHandler:nil)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        guard (error as NSError).code != NSURLErrorCancelled else { return }
        showStatus("图谱加载失败：\(error.localizedDescription)\n可使用工具栏刷新或重新启动。")
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        showStatus("图谱显示进程已停止。\n可使用工具栏刷新恢复，知识库文件仍保存在本机。")
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || (url.host == "127.0.0.1" && url.port == serviceURL?.port && url.scheme == "http") {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
            if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") {
                NSWorkspace.shared.open(url)
            }
        }
    }
}

@main
struct AtlasMain {
    @MainActor
    static func main() {
        let application = NSApplication.shared
        let delegate = AtlasDelegate()
        application.setActivationPolicy(.regular)
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }
}
