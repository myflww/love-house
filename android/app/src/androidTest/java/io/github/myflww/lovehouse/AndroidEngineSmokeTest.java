package io.github.myflww.lovehouse;

import static org.junit.Assert.*;

import android.content.Context;
import android.net.Uri;
import android.os.SystemClock;
import android.security.NetworkSecurityPolicy;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** The actual packaged Python runtime + engine + WebView, with synthetic data only.
 * No model credentials are read and these tests never request a paid model operation.
 */
@RunWith(AndroidJUnit4.class)
public final class AndroidEngineSmokeTest {
    private ActivityScenario<EngineActivity> scenario;
    private String url, cookie;

    @Before public void launch() throws Exception {
        scenario = ActivityScenario.launch(EngineActivity.class);
        long deadline = SystemClock.uptimeMillis() + 120000;
        do {
            AtomicReference<String> readyUrl = new AtomicReference<>();
            scenario.onActivity(activity -> {
                readyUrl.set(activity.engineUrlForTest());
                if (activity.engineManagementCookieForTest() != null) cookie = activity.engineManagementCookieForTest();
            });
            if (readyUrl.get() != null) { url = readyUrl.get(); break; }
            SystemClock.sleep(100);
        } while (SystemClock.uptimeMillis() < deadline);
        assertNotNull("Packaged Python memory engine did not start", url);
        // Only the native bootstrap supplies management authority. Keep it
        // inside this test client, never in a URL, result file or assertion body.
        assertNotNull("Native management session unavailable", cookie);
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(10000); connection.setReadTimeout(15000);
        connection.setRequestProperty("Cookie", cookie);
        try {
            assertEquals(200, connection.getResponseCode());
            try (InputStream body = connection.getInputStream()) {
                byte[] discard = new byte[8192]; while (body.read(discard) != -1) { /* consume root response */ }
            }
            // The page may refresh the existing session, never create a new
            // management grant merely because a loopback client opened it.
        } finally { connection.disconnect(); }
        request("/api/updates/settings", new JSONObject().put("auto_check", false), null, null);
        waitFor("full engine UI", "typeof S!=='undefined' && S.mode==='serve' && !!window.LoveHouseEngineFiles");
    }

    @After public void close() { if (scenario != null) scenario.close(); }

    @Test public void bundledEngineRunsSameCoreAndWarmUiWithStrictLocalOrigin() throws Exception {
        JSONObject health = request("/api/health", null, null, null);
        assertTrue(health.getBoolean("ok"));
        assertEquals("0.4.0", health.getString("protocol_version"));
        HttpURLConnection anonymous = (HttpURLConnection) new URL(url + "api/graph").openConnection();
        try {
            anonymous.setConnectTimeout(10000); anonymous.setReadTimeout(15000);
            assertEquals("Another Android app must not read memory using only the loopback URL", 401, anonymous.getResponseCode());
        } finally { anonymous.disconnect(); }
        assertEquals(BuildConfig.VERSION_NAME, health.getString("version"));
        assertTrue(NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted("127.0.0.1"));
        assertFalse(NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted("example.invalid"));
        scenario.onActivity(activity -> {
            assertTrue(activity.isEngineUri(Uri.parse(url)));
            Uri own = Uri.parse(url);
            int other = own.getPort() == 65535 ? 65534 : own.getPort() + 1;
            for (String blocked : new String[] {
                "http://127.0.0.1:" + other + "/", "http://localhost:" + own.getPort() + "/",
                "https://127.0.0.1:" + own.getPort() + "/", "http://127.0.0.1.evil.invalid:" + own.getPort() + "/",
                "http://bad@127.0.0.1:" + own.getPort() + "/", "file:///sdcard/memory.json", "content://documents/private"
            }) assertFalse("WebView must reject another origin", activity.isEngineUri(Uri.parse(blocked)));
            assertFalse(activity.webViewForTest().getSettings().getAllowFileAccess());
            assertFalse(activity.webViewForTest().getSettings().getAllowUniversalAccessFromFileURLs());
        });
        assertEquals("android", evaluate("window.LoveHouseEnginePlatform"));
        assertEquals(Boolean.TRUE, evaluate("!!window.webkit.messageHandlers.saveMemoryFile && !!window.webkit.messageHandlers.exportAstrBotAdapter"));
        // Only the graph's palette changes; the existing pixel toolbar does not.
        Object before = evaluate("getComputedStyle(document.querySelector('.topbar')||document.querySelector('header')).backgroundColor");
        evaluate("document.getElementById('themeBtn').click()");
        assertEquals(before, evaluate("getComputedStyle(document.querySelector('.topbar')||document.querySelector('header')).backgroundColor"));
        assertEquals(Boolean.TRUE, evaluate("!!document.getElementById('viewBtn')"));
        assertEquals(Boolean.TRUE, evaluate("window.LoveHouseAndroid===true && !!document.getElementById('agentSourcesBtn') && !document.getElementById('agentSourcesDialog')"));
        assertEquals(Boolean.FALSE, evaluate("!!document.querySelector('.atlas-view-tabs')"));
    }

    @Test public void personaChoicesCorrectionIsolationAndActivityRestartPersist() throws Exception {
        String first = createLibrary("Android core " + UUID.randomUUID());
        String other = createLibrary("Android separate " + UUID.randomUUID());
        JSONObject persona = request("/api/persona", null, first, null);
        assertTrue(persona.getBoolean("enabled"));
        assertTrue(persona.getBoolean("learning_enabled"));
        request("/api/persona/enabled", new JSONObject().put("enabled", false).put("learning_enabled", false), first, null);
        JSONObject remembered = request("/api/ai/remember", new JSONObject().put("text", "我现在喜欢少糖红茶，合成验收资料。")
            .put("kind", "preference").put("important", true), first, null);
        String previous = remembered.getString("id");
        JSONObject corrected = request("/api/memories/" + previous + "/correct", new JSONObject()
            .put("text", "我现在喜欢无糖红茶，合成验收资料。").put("label", "红茶甜度"), first, null);
        assertTrue(corrected.getBoolean("saved"));
        assertTrue(corrected.getJSONObject("change_scope").getBoolean("original_preserved"));
        assertFalse(previous.equals(corrected.getString("id")));
        JSONArray original = request("/api/graph", null, first, null).getJSONArray("nodes");
        assertTrue(original.toString().contains("少糖红茶"));
        assertTrue(original.toString().contains("无糖红茶"));
        assertEquals(0, request("/api/graph", null, other, null).getJSONArray("nodes").length());
        request("/api/library/select", new JSONObject().put("library_id", first), null, null);
        scenario.recreate();
        waitFor("recreated full engine UI", "typeof S!=='undefined' && S.mode==='serve'");
        JSONObject after = request("/api/persona", null, first, null);
        assertFalse(after.getBoolean("enabled")); assertFalse(after.getBoolean("learning_enabled"));
        assertEquals(first, request("/api/libraries", null, null, null).getString("selected_id"));
        assertEquals(original.length(), request("/api/graph", null, first, null).getJSONArray("nodes").length());
        waitFor("nonempty corrected synthetic graph", "S.libraryId===" + JSONObject.quote(first) + " && S.nodes.length>=2");
        evaluate("(function(){window.__engineCaptureReady=false;Object.keys(PANELS).forEach(function(id){setPanelOpen(id,false,{focus:false});});"
            + "S.paused=true;renderPause();if(window.LoveHouseAppearance)window.LoveHouseAppearance.setTheme('dark',true);fit();schedule();"
            + "requestAnimationFrame(function(){requestAnimationFrame(function(){window.__engineCaptureReady=true;});});return true;})()");
        waitFor("painted synthetic graph", "window.__engineCaptureReady===true");
        saveEngineScreenshot();
        assertEquals(0, request("/api/graph", null, other, null).getJSONArray("nodes").length());
        assertFalse(request("/api/organizer", null, first, null).getJSONObject("configuration").getBoolean("configured"));
        JSONObject configuration = request("/api/connections", new JSONObject().put("name", "Synthetic Android scoped agent")
            .put("host", "agent").put("library_id", first), first, null);
        String connection = configuration.getJSONObject("connection").getString("id");
        // Only this synthetic connection's returned memory capability is used.
        // Provider/model credentials are never inspected.
        JSONObject remote = configuration.getJSONObject("remote_config");
        assertEquals(url + "mcp/" + connection, remote.getString("url"));
        String authorization = remote.getJSONObject("headers").getString("Authorization");
        assertTrue(authorization.startsWith("Bearer "));
        String token = authorization.substring(7);
        String path = "/api/connections/" + connection + "/tool";
        JSONObject boot = request(path, new JSONObject().put("name", "memory_bootstrap").put("arguments", new JSONObject()), first, token);
        assertEquals(first, boot.getJSONObject("identity").getString("library_id"));
        assertFalse(boot.toString().contains(other));
        JSONObject rpc = request("/mcp/" + connection, new JSONObject().put("jsonrpc", "2.0").put("id", 1)
            .put("method", "tools/call").put("params", new JSONObject().put("name", "memory_bootstrap").put("arguments", new JSONObject())), first, token);
        assertEquals(first, rpc.getJSONObject("result").getJSONObject("structuredContent").getJSONObject("identity").getString("library_id"));
        // A memory bearer cannot become management or select another library.
        assertEquals(403, status(path, new JSONObject().put("name", "memory_bootstrap").put("arguments", new JSONObject()), other, token));
        // A memory bearer is not the native-only UI management session.
        // Android requires that session before it even enumerates libraries.
        assertEquals(401, status("/api/libraries", null, first, token));
    }

    @Test public void androidKeystorePersistsOnlyEncryptedScopedCredentials() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        String account = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        String second = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        String synthetic = "SYNTHETIC_ANDROID_CREDENTIAL_" + UUID.randomUUID();
        AndroidCredentialVault vault = new AndroidCredentialVault(context);
        try {
            assertTrue(new JSONObject(vault.call("set", account, synthetic)).getBoolean("ok"));
            assertEquals(synthetic, new JSONObject(new AndroidCredentialVault(context).call("get", account, null)).getString("value"));
            assertEquals("", new JSONObject(vault.call("get", second, null)).getString("value"));
            String stored = context.getSharedPreferences("lovehouse-encrypted-credentials-v1", Context.MODE_PRIVATE).getString(account, "");
            assertFalse(stored.contains(synthetic));
            assertTrue(new JSONObject(stored).has("iv")); assertTrue(new JSONObject(stored).has("data"));
            assertFalse(new JSONObject(vault.call("set", account, "bad\nvalue")).getBoolean("ok"));
            assertEquals(synthetic, new JSONObject(vault.call("get", account, null)).getString("value"));
            // A record copied under a different scope fails GCM AAD validation.
            context.getSharedPreferences("lovehouse-encrypted-credentials-v1", Context.MODE_PRIVATE).edit().putString(second, stored).commit();
            assertFalse(new JSONObject(vault.call("get", second, null)).getBoolean("ok"));
        } finally {
            assertTrue(new JSONObject(vault.call("delete", account, null)).getBoolean("ok"));
            assertTrue(new JSONObject(vault.call("delete", second, null)).getBoolean("ok"));
        }
        assertEquals("", new JSONObject(vault.call("get", account, null)).getString("value"));
    }

    private void saveEngineScreenshot() throws Exception {
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();
        android.graphics.Bitmap image = InstrumentationRegistry.getInstrumentation().getUiAutomation().takeScreenshot();
        assertNotNull("Synthetic engine screenshot unavailable", image);
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        java.io.File output = new java.io.File(context.getFilesDir(), "android-engine-smoke.png");
        try (java.io.FileOutputStream file = new java.io.FileOutputStream(output)) {
            assertTrue(image.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, file));
        } finally { image.recycle(); }
    }

    private String createLibrary(String name) throws Exception {
        return request("/api/libraries", new JSONObject().put("name", name), null, null).getJSONObject("library").getString("id");
    }

    private JSONObject request(String path, JSONObject body, String library, String bearer) throws Exception {
        HttpURLConnection connection = connection(path, body, library, bearer);
        try {
            assertEquals("Local engine HTTP request failed: " + path, 200, connection.getResponseCode());
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192]; int count;
                while ((count = input.read(buffer)) != -1) bytes.write(buffer, 0, count);
                return new JSONObject(bytes.toString("UTF-8"));
            }
        } finally { connection.disconnect(); }
    }

    private int status(String path, JSONObject body, String library, String bearer) throws Exception {
        HttpURLConnection connection = connection(path, body, library, bearer);
        try { return connection.getResponseCode(); } finally { connection.disconnect(); }
    }

    private HttpURLConnection connection(String path, JSONObject body, String library, String bearer) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url + path.substring(1)).openConnection();
        connection.setConnectTimeout(10000); connection.setReadTimeout(20000); connection.setInstanceFollowRedirects(false);
        if (path.startsWith("/mcp/")) {
            connection.setRequestProperty("Accept", "application/json, text/event-stream");
            connection.setRequestProperty("MCP-Protocol-Version", "2025-11-25");
        }
        if (bearer == null) connection.setRequestProperty("Cookie", cookie);
        else connection.setRequestProperty("Authorization", "Bearer " + bearer);
        if (library != null) connection.setRequestProperty("X-NKB-Library", library);
        if (body != null) {
            connection.setRequestMethod("POST"); connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream out = connection.getOutputStream()) { out.write(bytes); }
        }
        return connection;
    }

    private Object evaluate(String expression) throws Exception {
        CountDownLatch latch = new CountDownLatch(1); AtomicReference<String> value = new AtomicReference<>();
        scenario.onActivity(activity -> {
            if (activity.webViewForTest() == null) { value.set("null"); latch.countDown(); return; }
            activity.webViewForTest().evaluateJavascript("(function(){try{return (" + expression + ");}catch(e){return null;}})()", result -> {
                value.set(result); latch.countDown();
            });
        });
        assertTrue("Engine WebView callback timed out", latch.await(15, TimeUnit.SECONDS));
        return new JSONArray("[" + value.get() + "]").get(0);
    }

    private void waitFor(String caption, String expression) throws Exception {
        long deadline = SystemClock.uptimeMillis() + 60000;
        do {
            if (Boolean.TRUE.equals(evaluate("Boolean(" + expression + ")"))) return;
            SystemClock.sleep(100);
        } while (SystemClock.uptimeMillis() < deadline);
        fail("Timed out waiting for " + caption);
    }
}
