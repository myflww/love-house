package io.github.myflww.lovehouse.remoteqa;

import static org.junit.Assert.*;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.graphics.Bitmap;
import android.os.Build;
import android.os.SystemClock;
import android.webkit.WebView;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Actual Android WebView, normal TLS trust, real isolated Gateway/MemoryHost. */
@RunWith(AndroidJUnit4.class)
public final class RemoteGatewayTest {
    private static final String ADMIN = "ANDROID-WEBVIEW-SYNTHETIC-ADMIN-ONLY-000000000000";
    private static final String USER = "Synthetic Android host user: remember the silver compass.";
    private static final String ASSISTANT = "Synthetic Android host assistant: the silver compass is recorded.";
    private ActivityScenario<RemoteGatewayActivity> scenario;

    private String origin() {
        String value = InstrumentationRegistry.getArguments().getString("gatewayOrigin");
        assertNotNull("The actual HTTPS fixture origin must be supplied by CI", value);
        assertTrue(value.matches("https://127\\.0\\.0\\.1:[0-9]{1,5}"));
        return value;
    }
    private void launch(String url) {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Intent intent = new Intent(context, RemoteGatewayActivity.class);
        intent.putExtra("gatewayOrigin", url);intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        scenario = ActivityScenario.launch(intent);
    }
    @After public void close() { if (scenario != null) scenario.close(); }

    @Test public void normalTlsRejectsTheSameCaOutsideItsOnlyTestDomain() throws Exception {
        // The leaf SAN contains localhost too, but the test CA is trusted only
        // for 127.0.0.1. Hostname validation is valid; root trust must fail.
        launch(origin().replace("127.0.0.1", "localhost"));
        long end = SystemClock.uptimeMillis() + 45000;boolean rejected = false;
        do {
            AtomicReference<Integer> errors = new AtomicReference<>(0);
            scenario.onActivity(activity -> errors.set(activity.sslErrors));
            if (errors.get() > 0) { rejected = true;break; }
            SystemClock.sleep(150);
        } while (SystemClock.uptimeMillis() < end);
        assertTrue("Android accepted an untrusted CA or TLS never reached verification", rejected);
        SystemClock.sleep(500);
        AtomicReference<Integer> httpErrors=new AtomicReference<>(-1);
        scenario.onActivity(activity->httpErrors.set(activity.mainFrameHttpErrors));
        // If SSL were bypassed, the real Gateway would answer the localhost
        // alias with HTTP 403 (its canonical Host is 127.0.0.1). No HTTP response
        // may be reached on this deliberately untrusted TLS navigation.
        assertEquals("TLS error was ignored and reached HTTP",Integer.valueOf(0),httpErrors.get());
        JSONObject report = baseReport();report.put("ok", true);report.put("tls_rejected", true);
        report.put("http_reached_after_tls_error", false);
        report.put("trust_scope", "127.0.0.1 only; localhost uses system roots");
        writeReport("android-tls-rejection.json", report);
    }

    @Test public void realHttpsPortalCreatesAgentThenMcpAndHostHookSaveExactOriginalWords() throws Exception {
        launch(origin());
        waitFor("real portal JavaScript loaded", "document.getElementById('serviceOrigin') && document.getElementById('serviceOrigin').textContent===location.origin && !document.getElementById('loginButton').disabled");
        fill("adminToken", ADMIN);click("loginButton");
        waitFor("cookie authenticated real libraries", "!document.getElementById('workspace').hidden && document.getElementById('librarySelect').options.length>0");
        assertEquals("", evaluate("document.getElementById('adminToken').value"));
        assertEquals(Boolean.FALSE, evaluate("document.cookie.includes('LoveHouseAdmin')"));
        fill("connectionName", "Android API " + Build.VERSION.SDK_INT + " synthetic Agent");click("createConnection");
        waitFor("real server configuration", "!document.getElementById('configPanel').hidden && document.getElementById('mcpConfig').value.includes('mcpServers')");
        assertEquals("等待 Agent 加载配置", evaluate("document.getElementById('captureState').textContent"));
        JSONObject config = (JSONObject) evaluateBody("const config=JSON.parse(document.getElementById('mcpConfig').value);const server=Object.values(config.mcpServers)[0];const hook=JSON.parse(document.getElementById('hookConfig').value);if(new URL(server.url).origin!==location.origin||!server.url.startsWith('https:')||server.command||server.args)throw Error('MCP must use same-origin HTTPS with no local command');window.__qaServer=server;window.__qaHook=hook;return {https_only:true,no_local_command:true,credentials_persisted:Object.values(localStorage).some(v=>v.includes(server.headers.Authorization)||v.includes(" + JSONObject.quote(ADMIN) + "))};");
        assertFalse(config.getBoolean("credentials_persisted"));
        String windowId = "android-actual-fixture-window-api-" + Build.VERSION.SDK_INT;
        String script = """
            const server=window.__qaServer, hook=window.__qaHook;
            async function rpc(id,method,params={},modern=true) {
              const headers={...server.headers,'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':modern?'2026-07-28':'2025-11-25','Mcp-Session-Id':'not-the-real-host-window'};
              if(modern){params={...params,_meta:{'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientInfo':{name:'AndroidNativeWebViewQA',version:'1'},'io.modelcontextprotocol/clientCapabilities':{}}};headers['Mcp-Method']=method;if(method==='tools/call')headers['Mcp-Name']=params.name;}
              const response=await fetch(server.url,{method:'POST',headers,body:JSON.stringify({jsonrpc:'2.0',id,method,params})});const value=await response.json();
              if(!response.ok||value.error||value.result?.isError)throw Error('Actual HTTPS MCP failed: '+method);return value.result;
            }
            const initialized=await rpc(1,'initialize',{protocolVersion:'2025-11-25',capabilities:{},clientInfo:{name:'AndroidNativeWebViewQA',version:'1'}},false);
            if(initialized.protocolVersion!=='2025-11-25')throw Error('Legacy handshake failed');
            const discover=await rpc(2,'server/discover');if(!discover.supportedVersions.includes('2026-07-28'))throw Error('Modern discovery failed');
            const boot=await rpc(3,'tools/call',{name:'memory_bootstrap',arguments:{}});if(boot.structuredContent.identity.library_id!=='default')throw Error('Wrong fixed library');
            const before=await rpc(4,'tools/call',{name:'memory_status',arguments:{}});if(before.structuredContent.automatic_memory!==false)throw Error('Tool load claimed automatic capture');
            const manual=await rpc(5,'tools/call',{name:'memory_record_turn',arguments:{session_id:'manual-must-not-bind',request_id:'manual-one',user:'Synthetic manual words',assistant:'Synthetic manual reply'}});
            if(manual.structuredContent.code!=='awaiting_window_binding')throw Error('Manual tool claimed target window');
            const data={session_id:WINDOW_ID,turn_id:'android-fixture-one',status:'complete',user:USER_WORDS,assistant:ASSISTANT_WORDS};
            const response=await fetch(hook.url,{method:'POST',headers:hook.headers,body:JSON.stringify(data)});const saved=await response.json();
            if(!response.ok||saved.accepted!==true||saved.status!=='saved'||saved.bound_session_id!==data.session_id)throw Error('Actual host hook did not persist or bind the real window');
            const outside=await fetch(hook.url,{method:'POST',headers:hook.headers,body:JSON.stringify({...data,session_id:'outside-android-window',turn_id:'outside'})});const rejected=await outside.json();
            if(rejected.accepted!==false||rejected.code!=='scope_conflict')throw Error('Outside window was not rejected');
            const listing=await rpc(6,'tools/call',{name:'memory_list',arguments:{}});if(listing.structuredContent.entries.length!==1)throw Error('Unexpected memory count');
            const entry=listing.structuredContent.entries[0];const user=await rpc(7,'tools/call',{name:'memory_read',arguments:{memory_id:entry.id}});
            const assistant=await rpc(8,'tools/call',{name:'memory_read',arguments:{memory_id:entry.id,field:'assistant'}});
            if(user.structuredContent.text!==data.user||assistant.structuredContent.text!==data.assistant)throw Error('Original role text did not survive TLS memory readback');
            const status=await rpc(9,'tools/call',{name:'memory_status',arguments:{}});
            if(status.structuredContent.automatic_memory!==true||status.structuredContent.connection.session_scope!==data.session_id)throw Error('Actual automatic archive state was not verified');
            const denied=await fetch('/api/remote/admin/libraries',{headers:{Authorization:server.headers.Authorization}});if(denied.status!==403)throw Error('Agent bearer reached admin');
            return {legacy_protocol:true,modern_protocol:true,bootstrap:true,tools_did_not_claim_auto:true,manual_did_not_claim_window:true,host_hook_saved:true,foreign_window_excluded:true,original_user_readback:true,original_assistant_readback:true,agent_admin_isolation:true,actual_window:data.session_id};
            """.replace("WINDOW_ID", JSONObject.quote(windowId)).replace("USER_WORDS", JSONObject.quote(USER)).replace("ASSISTANT_WORDS", JSONObject.quote(ASSISTANT));
        evaluateBody("window.__qaResult=null;(async()=>{" + script + "})().then(value=>window.__qaResult={ok:true,value},()=>window.__qaResult={ok:false,error:'Actual Android HTTPS MCP or hook assertion failed'});return true;");
        waitFor("actual TLS MCP and hook completion", "window.__qaResult!==null");
        JSONObject result = (JSONObject) evaluate("window.__qaResult");
        assertTrue(result.optString("error"), result.getBoolean("ok"));
        click("checkConnection");
        waitFor("portal confirmed real automatic archive", "document.getElementById('captureState').textContent==='已验证收到自动记录'");
        AtomicReference<Integer> sslErrors = new AtomicReference<>(-1);
        scenario.onActivity(activity -> sslErrors.set(activity.sslErrors));assertEquals(Integer.valueOf(0), sslErrors.get());
        JSONObject report=baseReport();report.put("ok", true);report.put("trusted_https_loaded", true);report.put("portal_login", true);
        report.put("http_only_cookie_hidden", true);report.put("configuration", config);report.put("mcp_and_hook", result.getJSONObject("value"));
        report.put("automatic_archive_ui_verified", true);report.put("ssl_errors", 0);
        writeReport("android-remote-gateway.json", report);
        evaluateBody("document.getElementById('captureState').scrollIntoView({block:'center'});return true;");
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();
        Bitmap screenshot=InstrumentationRegistry.getInstrumentation().getUiAutomation().takeScreenshot();assertNotNull(screenshot);
        File directory=InstrumentationRegistry.getInstrumentation().getTargetContext().getFilesDir();
        try(FileOutputStream stream=new FileOutputStream(new File(directory,"android-remote-gateway.png"))){assertTrue(screenshot.compress(Bitmap.CompressFormat.PNG,100,stream));}
    }

    private JSONObject baseReport() throws Exception {
        JSONObject report=new JSONObject();report.put("schema","love-house-android-native-remote/v1");report.put("engine","Android System WebView");
        report.put("api_level",Build.VERSION.SDK_INT);report.put("physical_device",false);report.put("tls_bypass",false);report.put("production_app_modified",false);
        PackageInfo provider=WebView.getCurrentWebViewPackage();assertNotNull(provider);report.put("webview_package",provider.packageName);report.put("webview_version",provider.versionName);
        return report;
    }
    private void writeReport(String name,JSONObject report)throws Exception{
        File directory=InstrumentationRegistry.getInstrumentation().getTargetContext().getFilesDir();
        try(FileOutputStream stream=new FileOutputStream(new File(directory,name))){stream.write(report.toString(2).getBytes(StandardCharsets.UTF_8));}
    }
    private void click(String id)throws Exception{evaluateBody("const element=document.getElementById("+JSONObject.quote(id)+");if(!element||element.disabled)throw Error('Missing or disabled portal control');element.click();return true;");}
    private void fill(String id,String value)throws Exception{evaluateBody("const element=document.getElementById("+JSONObject.quote(id)+");element.value="+JSONObject.quote(value)+";element.dispatchEvent(new Event('input',{bubbles:true}));return true;");}
    private Object evaluate(String expression)throws Exception{return evaluateBody("return ("+expression+");");}
    private Object evaluateBody(String body)throws Exception{
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String> result=new AtomicReference<>();
        scenario.onActivity(activity->activity.webView().evaluateJavascript("(function(){try{"+body+"}catch(error){return {__qaError:String(error)};}})()",value->{result.set(value);done.countDown();}));
        assertTrue("Android WebView JS callback timed out",done.await(10,TimeUnit.SECONDS));
        Object value=new JSONArray("["+result.get()+"]").get(0);
        if(value instanceof JSONObject && ((JSONObject)value).has("__qaError"))fail(((JSONObject)value).getString("__qaError"));return value;
    }
    private void waitFor(String description,String expression)throws Exception{
        long end=SystemClock.uptimeMillis()+45000;
        do{if(Boolean.TRUE.equals(evaluate("Boolean("+expression+")")))return;SystemClock.sleep(150);}while(SystemClock.uptimeMillis()<end);
        fail("Timed out waiting for "+description+"; "+evaluate("({url:location.href,notice:document.getElementById('notice')?.textContent||'',ready:document.readyState})"));
    }
}
