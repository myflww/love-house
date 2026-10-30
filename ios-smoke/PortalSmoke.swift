import UIKit
import WebKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    func application(_ application: UIApplication, configurationForConnecting session: UISceneSession, options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let configuration = UISceneConfiguration(name:"Portal QA",sessionRole:session.role)
        configuration.delegateClass = SceneDelegate.self
        return configuration
    }
}

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let scene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene:scene)
        window.rootViewController = PortalController()
        window.makeKeyAndVisible()
        self.window = window
    }
}

final class PortalController: UIViewController, WKNavigationDelegate {
    private var web: WKWebView!
    private var continuation: CheckedContinuation<Void, Error>?
    private var report: [String: Any] = ["schema":"love-house-ios-wkwebview-smoke/v1", "engine":"iOS Simulator WKWebView", "physical_device":false, "tls_bypass":false]
    private var finished = false
    private var navigationCount = 0
    private let admin = "IOS-SIMULATOR-SYNTHETIC-ADMIN-ONLY-000000000000"
    private var mode: String { argument("--mode") ?? "portal" }
    private func argument(_ name: String) -> String? {
        let args = ProcessInfo.processInfo.arguments
        guard let index = args.firstIndex(of: name), index+1 < args.count else { return nil }
        return args[index+1]
    }
    override func viewDidLoad() {
        super.viewDidLoad()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        web.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(web)
        NSLayoutConstraint.activate([web.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor), web.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor), web.leadingAnchor.constraint(equalTo: view.leadingAnchor), web.trailingAnchor.constraint(equalTo: view.trailingAnchor)])
        view.backgroundColor = .systemBackground
        Task { await run() }
        Task { try? await Task.sleep(nanoseconds: 90_000_000_000); if !finished { finish(false, error:"Native iOS portal test exceeded 90 seconds") } }
    }
    private func navigate(_ url: URL) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            self.continuation = continuation
            web.load(URLRequest(url: url))
        }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { navigationCount += 1; continuation?.resume(); continuation = nil }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { continuation?.resume(throwing:error); continuation = nil }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { continuation?.resume(throwing:error); continuation = nil }
    // Intentionally no authentication-challenge handler: iOS performs normal TLS and root trust validation.
    private func js(_ script: String, _ arguments: [String:Any] = [:]) async throws -> Any {
        try await withCheckedThrowingContinuation { continuation in
            web.callAsyncJavaScript(script, arguments:arguments, in:nil, in:.page) { result in continuation.resume(with:result) }
        }
    }
    private func wait(_ expression: String) async throws {
        for _ in 0..<160 {
            if (try? await js("return Boolean("+expression+");")) as? Bool == true { return }
            try await Task.sleep(nanoseconds: 200_000_000)
        }
        throw NSError(domain:"LoveHouseIOSSmoke",code:1,userInfo:[NSLocalizedDescriptionKey:"Portal condition did not complete: "+expression])
    }
    private func run() async {
        do {
            guard let origin = argument("--origin"), let url = URL(string:origin+"/mobile/") else { throw NSError(domain:"LoveHouseIOSSmoke",code:2,userInfo:[NSLocalizedDescriptionKey:"Missing local HTTPS fixture origin"]) }
            report["ios_version"] = UIDevice.current.systemVersion
            report["simulator_device"] = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] ?? "unknown"
            report["origin"] = origin
            if mode == "reject" {
                do { try await navigate(url); finish(false,error:"Untrusted local CA was accepted") }
                catch { let e=error as NSError; report["error_domain"]=e.domain; report["error_code"]=e.code; report["tls_rejected"] = e.domain == NSURLErrorDomain && [-1200,-1202,-1203].contains(e.code); finish(report["tls_rejected"] as? Bool == true) }
                return
            }
            try await navigate(url)
            report["trusted_https_loaded"] = true
            try await wait("document.getElementById('loginForm') && typeof document.getElementById('loginForm').onsubmit==='function' && !document.getElementById('loginButton').disabled")
            _ = try await js("document.getElementById('adminToken').value=admin;document.getElementById('loginButton').click();return true;",["admin":admin])
            try await wait("!document.getElementById('workspace').hidden && document.getElementById('librarySelect').options.length>0")
            report["login_passed"] = true
            report["admin_input_cleared"] = try await js("return document.getElementById('adminToken').value==='';")
            _ = try await js("document.getElementById('connectionName').value='iOS Simulator synthetic Agent';document.getElementById('createConnection').click();return true;")
            try await wait("!document.getElementById('configPanel').hidden && document.getElementById('mcpConfig').value.includes('mcpServers')")
            let config = try await js("""
                const config=JSON.parse(document.getElementById('mcpConfig').value);
                const server=Object.values(config.mcpServers)[0];const hook=JSON.parse(document.getElementById('hookConfig').value);
                if(!server||new URL(server.url).protocol!=='https:'||new URL(server.url).origin!==location.origin||server.command||server.args)throw Error('Remote MCP config must use same-origin HTTPS and no local command');
                window.__qaServer=server;window.__qaHook=hook;
                return {https_only:true,no_local_command:true,stored_credentials:Object.values(localStorage).some(v=>v.includes(server.headers.Authorization)||v.includes(admin)),http_only_admin_cookie_hidden:!document.cookie.includes('LoveHouseAdmin')};
                """,["admin":admin])
            report["configuration"] = config
            let transport = try await js("""
                const server=window.__qaServer;
                async function rpc(id,method,params={}) {const response=await fetch(server.url,{method:'POST',headers:{...server.headers,'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'},body:JSON.stringify({jsonrpc:'2.0',id,method,params})});const value=await response.json();if(!response.ok||value.error||value.result?.isError)throw Error('Native iOS MCP request failed: '+method);return value.result;}
                window.__qaRpc=rpc;
                const initialized=await rpc(1,'initialize',{protocolVersion:'2025-11-25',capabilities:{},clientInfo:{name:'LoveHouseNativeIOSQA',version:'1'}});
                const tools=await rpc(2,'tools/list');if(!tools.tools.some(t=>t.name==='memory_status'))throw Error('Memory tools missing');
                await rpc(3,'tools/call',{name:'memory_status',arguments:{}});await rpc(4,'tools/call',{name:'memory_bootstrap',arguments:{}});
                return {protocol:initialized.protocolVersion,tools_count:tools.tools.length,status_and_bootstrap:true};
                """)
            report["mcp"] = transport
            _ = try await js("document.getElementById('checkConnection').click();return true;")
            try await wait("document.getElementById('captureState').textContent==='记忆工具已连接'")
            report["tool_connection_did_not_claim_automatic_capture"] = true
            let hook = try await js("""
                const target=window.__qaHook;const data={session_id:'ios-simulator-real-fixture-window',turn_id:'ios-fixture-turn-1',status:'complete',user:'Synthetic iOS host user: remember the blue compass.',assistant:'Synthetic iOS host assistant: the blue compass is recorded.'};
                const response=await fetch(target.url,{method:'POST',headers:target.headers,body:JSON.stringify(data)});const saved=await response.json();if(!response.ok||saved.accepted!==true||saved.status!=='saved')throw Error('Real HTTPS host hook did not save original dialogue');
                const foreign=await fetch(target.url,{method:'POST',headers:target.headers,body:JSON.stringify({...data,session_id:'outside-ios-fixture-window',turn_id:'outside'})});const rejected=await foreign.json();if(rejected.accepted!==false||rejected.code!=='scope_conflict')throw Error('Other-window hook was not rejected');
                const listing=await window.__qaRpc(5,'tools/call',{name:'memory_list',arguments:{}});const entries=listing.structuredContent.entries;if(entries.length!==1)throw Error('Unexpected saved memory count');
                const read=await window.__qaRpc(6,'tools/call',{name:'memory_read',arguments:{memory_id:entries[0].id}});if(read.structuredContent.text!==data.user)throw Error('Original user wording did not survive remote memory read');
                const denied=await fetch('/api/remote/admin/libraries',{headers:{Authorization:window.__qaServer.headers.Authorization}});if(denied.status!==403)throw Error('Agent capability reached administrator API');
                return {saved:true,foreign_window_excluded:true,original_text_readback:true,agent_admin_isolation:true};
                """)
            report["host_hook"] = hook
            _ = try await js("document.getElementById('checkConnection').click();return true;")
            try await wait("document.getElementById('captureState').textContent==='已验证收到自动记录'")
            report["automatic_archive_ui_verified"] = true
            _ = try await js("document.getElementById('captureState').scrollIntoView({block:'center'});return true;")
            finish(true)
        } catch {
            if let diagnostic = try? await js("return {ready:document.readyState,login_handler_ready:typeof document.getElementById('loginForm')?.onsubmit==='function',login_disabled:document.getElementById('loginButton')?.disabled,workspace_hidden:document.getElementById('workspace')?.hidden,library_options:document.getElementById('librarySelect')?.options.length,notice:document.getElementById('notice')?.textContent,path:location.pathname};") { report["page_diagnostic"] = diagnostic }
            finish(false,error:(error as NSError).localizedDescription)
        }
    }
    private func finish(_ ok: Bool, error: String? = nil) {
        guard !finished else { return };finished=true;report["ok"]=ok;report["process_complete"]=true;report["navigation_count"]=navigationCount
        if let error { report["error"]=error }
        let directory=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0]
        let path=directory.appendingPathComponent(mode == "reject" ? "tls-rejection.json" : "ios-portal-smoke.json")
        if let data=try? JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]) { try? data.write(to:path,options:.atomic) }
        print("LoveHouse iOS native WKWebView smoke completed: \(ok ? "passed" : "failed")")
    }
}
