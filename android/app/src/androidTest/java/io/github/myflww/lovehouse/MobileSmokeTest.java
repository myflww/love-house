package io.github.myflww.lovehouse;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.Manifest;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.SystemClock;
import android.webkit.WebSettings;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.FileOutputStream;
import java.util.Arrays;
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

/** Real packaged WebView, DOM handlers and IndexedDB; only uniquely named synthetic data. */
@RunWith(AndroidJUnit4.class)
public final class MobileSmokeTest {
    private static final long PAGE_TIMEOUT_MS = 30000;
    private ActivityScenario<MainActivity> scenario;

    @Before public void launch() {
        scenario = ActivityScenario.launch(MainActivity.class);
    }

    @After public void close() {
        if (scenario != null) scenario.close();
    }

    @Test public void offlineBoundaryRejectsExternalOriginsAndUnneededPermissions() throws Exception {
        ready();
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        PackageManager manager = context.getPackageManager();
        PackageInfo info = manager.getPackageInfo(context.getPackageName(), PackageManager.GET_PERMISSIONS);
        String[] permissions = info.requestedPermissions == null ? new String[0] : info.requestedPermissions;
        assertFalse(Arrays.asList(permissions).contains(Manifest.permission.INTERNET));
        assertFalse(Arrays.asList(permissions).contains(Manifest.permission.READ_EXTERNAL_STORAGE));
        assertFalse(Arrays.asList(permissions).contains(Manifest.permission.WRITE_EXTERNAL_STORAGE));
        assertFalse(Arrays.asList(permissions).contains(Manifest.permission.RECORD_AUDIO));
        assertFalse(Arrays.asList(permissions).contains(Manifest.permission.CAMERA));
        assertEquals(PackageManager.PERMISSION_DENIED,
            manager.checkPermission(Manifest.permission.INTERNET, context.getPackageName()));
        assertEquals(0, info.applicationInfo.flags & ApplicationInfo.FLAG_USES_CLEARTEXT_TRAFFIC);
        assertTrue(MainActivity.isLocal(Uri.parse(MainActivity.HOME)));
        assertTrue(MainActivity.isLocal(Uri.parse(MainActivity.ORIGIN + "/assets/web/store.js")));
        for (String external : new String[] {
            "https://example.invalid/assets/web/index.html",
            "http://appassets.androidplatform.net/assets/web/index.html",
            "https://appassets.androidplatform.net.evil.invalid/assets/web/index.html",
            "https://evil@appassets.androidplatform.net/assets/web/index.html",
            "https://appassets.androidplatform.net:443/assets/web/index.html",
            "https://appassets.androidplatform.net/other/index.html",
            "https://appassets.androidplatform.net/assets/web-evil/index.html",
            "file:///data/local/tmp/index.html", "content://documents/private", "javascript:alert(1)",
            "http://127.0.0.1:9140/", "https://127.0.0.1/assets/web/index.html"
        }) assertFalse(external, MainActivity.isLocal(Uri.parse(external)));
        scenario.onActivity(activity -> {
            WebSettings settings = activity.webViewForTest().getSettings();
            assertTrue(settings.getJavaScriptEnabled());
            assertTrue(settings.getDomStorageEnabled());
            assertFalse(settings.getAllowFileAccess());
            assertFalse(settings.getAllowFileAccessFromFileURLs());
            assertFalse(settings.getAllowUniversalAccessFromFileURLs());
            assertEquals(WebSettings.MIXED_CONTENT_NEVER_ALLOW, settings.getMixedContentMode());
        });
        assertEquals("indexeddb", ((JSONObject) evaluate("window.LoveHouseMobile.summary()")).getString("storage"));
        assertEquals("android", ((JSONObject) evaluate("window.LoveHouseMobile.summary()")).getString("platform"));
    }

    @Test public void uiCanCreateEditSearchAndOpenTheStarMap() throws Exception {
        ready();
        createLibrary("Smoke UI " + UUID.randomUUID());
        addMemory("一起去海边🙂", "合成原文 e\u0301 / é\n<script>window.smokeExecuted=true</script>", "合成回复❤️", "旅行，共同标签");
        addMemory("又看了一场雨", "这只是 instrumentation 的合成数据。", "", "共同标签");
        waitFor("two memory cards", "document.querySelectorAll('.memory-card').length===2");
        openCard("一起去海边🙂");
        assertEquals("合成原文 e\u0301 / é\n<script>window.smokeExecuted=true</script>", evaluate("document.getElementById('detailText').textContent"));
        assertEquals("合成回复❤️", evaluate("document.getElementById('detailAssistant').textContent"));
        assertEquals(Boolean.TRUE, evaluate("typeof window.smokeExecuted==='undefined'"));
        click("editMemory");
        waitFor("editor opened", "document.getElementById('memoryDialog').open");
        fill("memoryTitle", "海边 · 已补充");
        fill("memoryText", "已补充的完整原文🙂\n第二行 e\u0301 / é");
        submit("memoryForm");
        waitFor("edit committed", "!document.getElementById('memoryDialog').open && Array.from(document.querySelectorAll('.memory-card h3')).some(function(n){return n.textContent==='海边 · 已补充';})");
        search("已补充");
        waitFor("search returns one match", "document.querySelectorAll('.memory-card').length===1 && document.querySelector('.memory-card h3').textContent==='海边 · 已补充'");
        search("没有这个合成关键词");
        waitFor("empty search result", "document.querySelectorAll('.memory-card').length===0 && !document.getElementById('emptyState').hidden");
        search("");
        waitFor("search restored all records", "document.querySelectorAll('.memory-card').length===2");
        click("tab-map");
        waitFor("two stars and one shared-tag edge", "!document.getElementById('view-map').hidden && document.querySelectorAll('#mapWorld [data-node]').length===2 && document.querySelectorAll('#mapWorld line').length===1");
        String originalTransform = String.valueOf(evaluate("document.getElementById('mapWorld').getAttribute('transform')"));
        click("mapZoomIn");
        assertFalse(originalTransform.equals(String.valueOf(evaluate("document.getElementById('mapWorld').getAttribute('transform')"))));
        click("mapLabels");
        waitFor("star labels", "document.querySelectorAll('#mapWorld text').length===2");
        saveScreenshot();
        evaluateBody("document.querySelector('#mapWorld [data-node]').dispatchEvent(new MouseEvent('click',{bubbles:true})); return true;");
        waitFor("star opens original memory", "document.getElementById('detailDialog').open && document.getElementById('detailText').textContent.length>0");
    }

    @Test public void memoryAndSelectedLibrarySurviveActivityRecreationAndRelaunch() throws Exception {
        ready();
        String selected = createLibrary("Smoke persistence " + UUID.randomUUID());
        String original = "重启前的合成原文🙂\nUnicode e\u0301 / é，不能合并或截断。";
        addMemory("重启仍在", original, "回复同样保留❤️", "持久化");
        JSONObject before = exportLibrary(selected);
        String nodeId = before.getJSONObject("memory").getJSONObject("nodes").keys().next();
        scenario.recreate();
        ready();
        waitFor("persisted selected library", "document.getElementById('librarySelect').value===" + quote(selected));
        waitFor("persisted card after recreation", "document.querySelectorAll('.memory-card').length===1");
        openCard("重启仍在");
        assertEquals(original, evaluate("document.getElementById('detailText').textContent"));
        assertEquals("回复同样保留❤️", evaluate("document.getElementById('detailAssistant').textContent"));
        scenario.close();
        scenario = ActivityScenario.launch(MainActivity.class);
        ready();
        assertEquals(selected, evaluate("document.getElementById('librarySelect').value"));
        JSONObject after = exportLibrary(selected);
        assertEquals(original, after.getJSONObject("memory").getJSONObject("nodes").getJSONObject(nodeId).getString("text"));
        assertEquals(before.getString("content_revision"), after.getString("content_revision"));
    }

    @Test public void separateLibrariesAndPortableExportsStayIsolated() throws Exception {
        ready();
        String markerA = "SYNTHETIC_A_" + UUID.randomUUID();
        String markerB = "SYNTHETIC_B_" + UUID.randomUUID();
        String nameA = "Smoke isolation A " + UUID.randomUUID();
        String libraryA = createLibrary(nameA);
        addMemory("库 A 的原文", markerA, "库 A 的回复🙂", "独立A");
        String libraryB = createLibrary("Smoke isolation B " + UUID.randomUUID());
        waitFor("new library empty", "document.querySelectorAll('.memory-card').length===0");
        addMemory("库 B 的原文", markerB, "", "独立B");
        JSONObject b = exportLibrary(libraryB);
        assertTrue(b.toString().contains(markerB));
        assertFalse(b.toString().contains(markerA));
        fill("librarySelect", libraryA);
        evaluateBody("document.getElementById('librarySelect').dispatchEvent(new Event('change',{bubbles:true})); return true;");
        waitFor("library A selection complete", "!document.getElementById('librarySelect').disabled && document.querySelectorAll('.memory-card').length===1 && document.querySelector('.memory-card h3').textContent==='库 A 的原文'");
        search(markerB);
        waitFor("library B text absent from A search", "document.querySelectorAll('.memory-card').length===0");
        search(markerA);
        waitFor("library A text remains searchable", "document.querySelectorAll('.memory-card').length===1");
        click("tab-backup");
        waitFor("backup screen is current library", "!document.getElementById('view-backup').hidden && document.getElementById('exportLibraryName').textContent===" + quote(nameA));
        JSONObject a = exportLibrary(libraryA);
        assertEquals("love-house-memory-share/v1", a.getString("format"));
        assertEquals("single_library", a.getString("scope"));
        assertEquals(nameA, a.getString("name"));
        assertEquals(1, a.getJSONObject("memory").getInt("version"));
        assertEquals(1, a.getJSONObject("counts").getInt("node_count"));
        assertEquals(0, a.getJSONObject("counts").getInt("archive_count"));
        assertEquals(0, a.getJSONArray("archives").length());
        assertFalse(a.getJSONObject("privacy").getBoolean("includes_keys"));
        assertFalse(a.getJSONObject("privacy").getBoolean("includes_connections"));
        assertTrue(a.toString().contains(markerA));
        assertFalse(a.toString().contains(markerB));
        JSONObject node = a.getJSONObject("memory").getJSONObject("nodes").getJSONObject(a.getJSONObject("memory").getJSONObject("nodes").keys().next());
        assertEquals(markerA, node.getString("text"));
        assertEquals("库 A 的回复🙂", node.getJSONObject("meta").getString("assistant_reply"));
    }

    private void ready() throws Exception {
        waitFor("packaged app ready using IndexedDB", "document.documentElement && document.documentElement.dataset.appReady==='true' && window.LoveHouseMobile && window.LoveHouseMobile.summary().ready && window.LoveHouseApp && window.LoveHouseApp.store && document.getElementById('newMemory') && !document.getElementById('newMemory').disabled");
        assertEquals(Boolean.TRUE, evaluate("document.getElementById('storageError').hidden"));
    }

    private String createLibrary(String name) throws Exception {
        click("newLibrary");
        waitFor("library editor", "document.getElementById('libraryDialog').open");
        fill("libraryName", name);
        submit("libraryForm");
        waitFor("new independent library committed", "!document.getElementById('libraryDialog').open && !document.getElementById('createLibrary').disabled && document.getElementById('librarySelect').selectedOptions[0].textContent===" + quote(name));
        return String.valueOf(evaluate("document.getElementById('librarySelect').value"));
    }

    private void addMemory(String title, String text, String assistant, String tags) throws Exception {
        click("newMemory");
        waitFor("memory editor", "document.getElementById('memoryDialog').open");
        fill("memoryTitle", title); fill("memoryText", text); fill("memoryAssistant", assistant); fill("memoryTags", tags);
        submit("memoryForm");
        waitFor("memory saved to real IndexedDB", "!document.getElementById('memoryDialog').open && !document.getElementById('saveMemory').disabled && Array.from(document.querySelectorAll('.memory-card h3')).some(function(n){return n.textContent===" + quote(title) + ";})");
    }

    private void openCard(String title) throws Exception {
        evaluateBody("var cards=document.querySelectorAll('.memory-card'); for(var i=0;i<cards.length;i++){if(cards[i].querySelector('h3').textContent===" + quote(title) + "){cards[i].click(); return true;}} throw new Error('Synthetic card missing');");
        waitFor("memory detail", "document.getElementById('detailDialog').open && document.getElementById('detailTitle').textContent===" + quote(title));
    }

    private void search(String query) throws Exception {
        fill("searchInput", query);
        submit("searchForm");
    }

    private void click(String id) throws Exception {
        evaluateBody("var element=document.getElementById(" + quote(id) + "); if(!element || element.disabled) throw new Error('Disabled or missing control: '+" + quote(id) + "); element.click(); return true;");
    }

    private void fill(String id, String value) throws Exception {
        evaluateBody("var element=document.getElementById(" + quote(id) + "); element.value=" + quote(value) + "; element.dispatchEvent(new Event('input',{bubbles:true})); return true;");
    }

    private void submit(String id) throws Exception {
        evaluateBody("document.getElementById(" + quote(id) + ").dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})); return true;");
    }

    private JSONObject exportLibrary(String libraryId) throws Exception {
        evaluateBody("window.__smokeExport=null; window.LoveHouseApp.store.exportLibrary(" + quote(libraryId) + ").then(function(value){window.__smokeExport={ok:true,value:value};},function(error){window.__smokeExport={ok:false,error:String(error)};}); return true;");
        waitFor("portable export completed", "window.__smokeExport!==null");
        JSONObject result = (JSONObject) evaluate("window.__smokeExport");
        assertTrue("Export error: " + result.optString("error"), result.getBoolean("ok"));
        return result.getJSONObject("value");
    }

    private Object evaluate(String expression) throws Exception {
        return evaluateBody("return (" + expression + ");");
    }

    private Object evaluateBody(String body) throws Exception {
        CountDownLatch completed = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        String script = "(function(){try{" + body + "}catch(error){return {__smokeError:String(error)};}})()";
        scenario.onActivity(activity -> activity.webViewForTest().evaluateJavascript(script, value -> {
            result.set(value); completed.countDown();
        }));
        assertTrue("WebView JavaScript callback timed out", completed.await(10, TimeUnit.SECONDS));
        Object value = new JSONArray("[" + result.get() + "]").get(0);
        if (value instanceof JSONObject && ((JSONObject) value).has("__smokeError")) fail(((JSONObject) value).getString("__smokeError"));
        return value;
    }

    private void waitFor(String description, String expression) throws Exception {
        long end = SystemClock.uptimeMillis() + PAGE_TIMEOUT_MS;
        do {
            if (Boolean.TRUE.equals(evaluate("Boolean(" + expression + ")"))) return;
            SystemClock.sleep(100);
        } while (SystemClock.uptimeMillis() < end);
        Object diagnostic = evaluate("({url:location.href,ready:document.documentElement ? document.documentElement.dataset.appReady||'' : 'no document element',storageError:document.getElementById('storageErrorText') ? document.getElementById('storageErrorText').textContent : 'no app document'})");
        fail("Timed out waiting for " + description + ": " + diagnostic);
    }

    private void saveScreenshot() throws Exception {
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();
        Bitmap image = InstrumentationRegistry.getInstrumentation().getUiAutomation().takeScreenshot();
        assertNotNull("Device screenshot unavailable", image);
        Context target = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File output = new File(target.getFilesDir(), "android-smoke.png");
        try (FileOutputStream stream = new FileOutputStream(output)) {
            assertTrue(image.compress(Bitmap.CompressFormat.PNG, 100, stream));
        } finally { image.recycle(); }
        assertTrue("Screenshot was not saved to target app files", output.isFile() && output.length() > 0);
    }

    private static String quote(String value) { return JSONObject.quote(value); }
}
