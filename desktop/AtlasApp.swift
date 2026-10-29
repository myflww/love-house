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
        configuration.userContentController.add(self, name: "saveMemoryFile")
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
            DispatchQueue.main.asyncAfter(deadline: .now() + 60) { [weak self] in
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
                              libraryID: String? = nil, token: String? = nil) async throws -> [String: Any] {
        guard let base = serviceURL, let url = URL(string: path, relativeTo: base) else {
            throw NSError(domain: "NeuralAtlasSmoke", code: 1, userInfo: [NSLocalizedDescriptionKey: "Missing Controller URL"])
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 10
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let id = libraryID { request.setValue(id, forHTTPHeaderField: "X-NKB-Library") }
        if let token = token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let payload = payload {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "NeuralAtlasSmoke", code: (response as? HTTPURLResponse)?.statusCode ?? 0,
                          userInfo: [NSLocalizedDescriptionKey: "Controller request failed: \(path)"])
        }
        return object
    }

    private func requireSmoke(_ condition: Bool, _ message: String) throws {
        if !condition { throw NSError(domain: "NeuralAtlasSmoke", code: 2, userInfo: [NSLocalizedDescriptionKey: message]) }
    }

    private func failSmoke(_ error: Error) {
        print("Native desktop self-test failed: \(error.localizedDescription)")
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

    private func captureSmokeTurn(_ id: String, user: String) async throws {
        let payload: [String: Any] = ["session_id": "native-session", "event_id": id, "event_type": "turn/end",
            "record": ["schema": "deepseek-harness-event/v1",
                       "raw_event": ["type": "turn/end", "attachments": [["id": "native-temporary-attachment"]]],
                       "normalized": ["type": "turn", "status": "complete", "turn_id": id,
                                      "user": user, "assistant": "原始助手回复（临时测试）"]]]
        let result = try await smokeRequest("api/connections/\(smokeConnectionID)/events", method: "POST",
                                            payload: payload, token: smokeConnectionToken)
        try requireSmoke(result["accepted"] as? Bool == true, "Completed host event was not accepted")
    }

    private func exerciseController() {
        Task {
            do {
                let libraries = try await smokeRequest("api/libraries")
                try requireSmoke(libraries["selected_id"] as? String == "default", "First GUI selection was not default")
                let organizerUI = try await webView.callAsyncJavaScript(
                    "setPanelOpen('organizerPanel',true,{focus:false}); await refreshOrganizer(); const panel=document.getElementById('organizerPanel'); const enabled=document.getElementById('organizerEnabled'); const result={open:!!panel&&!panel.hidden, enabled:enabled?.checked===true, preview:!!document.getElementById('previewOrganizer')}; setPanelOpen('organizerPanel',false,{restore:false}); return result;",
                    arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
                try requireSmoke(organizerUI?["open"] as? Bool == true && organizerUI?["enabled"] as? Bool == false && organizerUI?["preview"] as? Bool == true, "Organizer panel was unavailable or unexpectedly enabled")
                let organizerPreview = try await smokeRequest("api/organizer/preview", method: "POST", payload: [:])
                try requireSmoke(organizerPreview["will_call_model"] as? Bool == false, "Organizer preview attempted a model call")
                print("Native organizer: real panel opens, starts disabled, preview performs no model call")
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
                try await captureSmokeTurn("persona", user: "导入人格：\n原生测试明确人格原文")
                try await captureSmokeTurn("style-1", user: "我希望你说话幽默一点")
                try await captureSmokeTurn("style-2", user: "以后请你说话幽默一点")
                let persona = try await smokeRequest("api/persona", libraryID: smokeLibraryA)
                try requireSmoke((persona["manual"] as? String ?? "").contains("明确人格原文"), "Connected persona import missing")
                try requireSmoke(!(persona["learned"] as? [String: Any] ?? [:]).isEmpty, "Evidence style learning missing")
                smokeStage = 2
                try await setSmokeLibrary(smokeLibraryB, alreadySelected: true)
            } catch { failSmoke(error) }
        }
    }

    private func verifyFixedConnection() {
        Task {
            do {
                let oldPID = process?.processIdentifier
                try await captureSmokeTurn("after-gui-switch", user: "切换画面后仍归属甲库的原文")
                let a = try await smokeRequest("api/graph", libraryID: smokeLibraryA)
                let b = try await smokeRequest("api/graph", libraryID: smokeLibraryB)
                let fallback = try await smokeRequest("api/graph")
                smokeExpectedIDs = Set((a["nodes"] as? [[String: Any]] ?? []).compactMap { $0["id"] as? String })
                try requireSmoke(smokeExpectedIDs.count == 4, "Connection did not stay bound to library A")
                try requireSmoke((b["nodes"] as? [[String: Any]] ?? []).isEmpty, "GUI library B was contaminated")
                try requireSmoke((fallback["nodes"] as? [[String: Any]] ?? []).isEmpty, "Unscoped API stopped defaulting to default")
                try requireSmoke(oldPID == process?.processIdentifier, "GUI selection restarted the backend")
                print("Native Controller: registry two libraries; completed events; GUI switch keeps connection binding; persona import/learning OK")
                smokeStage = 4
                try await setSmokeLibrary(smokeLibraryA)
            } catch { failSmoke(error) }
        }
    }

    private func verifyViewportAndRestart() {
        Task {
            do {
                let result = try await webView.callAsyncJavaScript("""
                    const c=document.getElementById('cv');
                    const wait=async(predicate)=>{const end=performance.now()+6000;while(!predicate()){if(performance.now()>end)throw new Error('Native viewport did not settle');await new Promise(r=>setTimeout(r,30));}};
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
                    return {initial,manualMode:manual.mode,preserved,restored:c.dataset.viewMode,labelsOn,labelsOff};
                    """, arguments: [:], in: nil, contentWorld: .page) as? [String: Any]
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
                print("Native viewport: sparse four-node close view; manual zoom survives real graph reload; fit restores auto; node labels toggle without writes")
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
                print("Native restart: stable Controller port, isolated graph, original dialogue and activity restored")
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
        panel.title = "选择要导入的笔记或记忆分享包"
        panel.message = "只读取你在此明确选择的文件，不扫描其他文件或文件夹。"
        panel.prompt = "选择笔记"
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
