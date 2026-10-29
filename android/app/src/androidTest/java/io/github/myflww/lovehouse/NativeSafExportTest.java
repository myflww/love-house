package io.github.myflww.lovehouse;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.content.IntentFilter;
import android.database.Cursor;
import android.os.SystemClock;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Exercises the real export button, JavaScript bridge, SAF result and native stream. */
@RunWith(AndroidJUnit4.class)
public final class NativeSafExportTest {
    private ActivityScenario<MainActivity> scenario;
    private final Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();

    @Test public void nativeSafWritesUtf8AndCancellationNeverClaimsSuccess() throws Exception {
        Instrumentation.ActivityMonitor saveMonitor = null, cancelMonitor = null;
        ContentResolver resolver = instrumentation.getTargetContext().getContentResolver();
        try {
            resolver.delete(SyntheticDocumentProvider.DOCUMENT, null, null);
            scenario = ActivityScenario.launch(MainActivity.class);
            waitFor("app ready", "document.documentElement.dataset.appReady==='true' && !document.getElementById('newMemory').disabled");
            String name = "Smoke SAF " + UUID.randomUUID();
            StringBuilder text = new StringBuilder("UTF8 合成原文 e\u0301 / é 🙂\n");
            // Larger than a pipe buffer: the native write must stay pending while the
            // controlled test provider has not started reading, exposing false success.
            for (int i = 0; i < 16000; i++) text.append("合成🙂\n");
            String original = text.toString();
            execute("document.getElementById('newLibrary').click();");
            fill("libraryName", name); submit("libraryForm");
            waitFor("synthetic library created", "!document.getElementById('libraryDialog').open && document.getElementById('librarySelect').selectedOptions[0].textContent===" + quote(name));
            execute("document.getElementById('newMemory').click();");
            fill("memoryTitle", "SAF 合成 UTF8"); fill("memoryText", original);
            fill("memoryAssistant", "独立回复❤️"); fill("memoryTags", "SAF，合成");
            submit("memoryForm");
            waitFor("synthetic record saved", "!document.getElementById('memoryDialog').open && document.querySelectorAll('.memory-card').length===1");
            execute("document.getElementById('tab-backup').click(); window.__safEvents=[]; window.addEventListener('lovehouse-save-result',function(event){window.__safEvents.push({saved:event.detail.saved,cancelled:event.detail.cancelled});});");

            Intent saved = new Intent().setData(SyntheticDocumentProvider.DOCUMENT);
            saveMonitor = instrumentation.addMonitor(documentFilter(), new Instrumentation.ActivityResult(Activity.RESULT_OK, saved), true);
            execute("document.getElementById('exportJson').click();");
            waitForMonitor(saveMonitor);
            waitForProviderOpen(resolver);
            // No success event or message is allowed while the OutputStream is blocked.
            assertEquals(Boolean.TRUE, evaluate("document.getElementById('exportJson').disabled"));
            assertEquals("", evaluate("document.getElementById('exportStatus').textContent"));
            assertEquals(0, ((Number) evaluate("window.__safEvents.length")).intValue());
            assertFalse(status(resolver).closed);
            ContentValues allow = new ContentValues(); allow.put("allow_read", true);
            resolver.update(SyntheticDocumentProvider.DOCUMENT, allow, null, null);
            Snapshot snapshot = waitForProviderClose(resolver);
            assertEquals("", snapshot.error);
            assertTrue("Expected a completed UTF-8 document", snapshot.byteCount > 65536);
            JSONObject exported = new JSONObject(snapshot.payload);
            assertEquals("love-house-memory-share/v1", exported.getString("format"));
            assertEquals("single_library", exported.getString("scope"));
            assertEquals(name, exported.getString("name"));
            JSONObject nodes = exported.getJSONObject("memory").getJSONObject("nodes");
            JSONObject node = nodes.getJSONObject(nodes.keys().next());
            assertEquals(original, node.getString("text"));
            assertEquals("独立回复❤️", node.getJSONObject("meta").getString("assistant_reply"));
            waitFor("UI confirms completed native save", "!document.getElementById('exportJson').disabled && document.getElementById('exportStatus').textContent==='文件已保存到你选择的位置。'");
            JSONObject success = ((JSONArray) evaluate("window.__safEvents")).getJSONObject(0);
            assertTrue(success.getBoolean("saved")); assertFalse(success.getBoolean("cancelled"));
            instrumentation.removeMonitor(saveMonitor); saveMonitor = null;

            execute("window.__safEvents=[];");
            cancelMonitor = instrumentation.addMonitor(documentFilter(), new Instrumentation.ActivityResult(Activity.RESULT_CANCELED, null), true);
            execute("document.getElementById('exportJson').click();");
            waitForMonitor(cancelMonitor);
            waitFor("cancelled export has honest UI", "!document.getElementById('exportJson').disabled && document.getElementById('exportStatus').textContent==='已取消，文件未保存。'");
            JSONObject cancelled = ((JSONArray) evaluate("window.__safEvents")).getJSONObject(0);
            assertFalse(cancelled.getBoolean("saved")); assertTrue(cancelled.getBoolean("cancelled"));
            assertEquals(1, status(resolver).openCount);
            assertEquals(snapshot.payload, status(resolver).payload);
            assertEquals(Boolean.FALSE, evaluate("document.getElementById('toast').textContent.indexOf('文件已保存')!==-1"));
        } finally {
            if (saveMonitor != null) instrumentation.removeMonitor(saveMonitor);
            if (cancelMonitor != null) instrumentation.removeMonitor(cancelMonitor);
            // Release a failed-test writer; the test provider never retains a disk file.
            ContentValues allow = new ContentValues(); allow.put("allow_read", true);
            try { resolver.update(SyntheticDocumentProvider.DOCUMENT, allow, null, null); } catch (Exception ignored) { }
            if (scenario != null) scenario.close();
        }
    }

    private static IntentFilter documentFilter() throws IntentFilter.MalformedMimeTypeException {
        IntentFilter filter = new IntentFilter(Intent.ACTION_CREATE_DOCUMENT);
        filter.addCategory(Intent.CATEGORY_OPENABLE); filter.addDataType("application/json");
        return filter;
    }

    private static final class Snapshot {
        int openCount, byteCount; boolean closed; String payload, error;
    }

    private static Snapshot status(ContentResolver resolver) {
        try (Cursor cursor = resolver.query(SyntheticDocumentProvider.DOCUMENT, null, null, null, null)) {
            assertNotNull(cursor); assertTrue(cursor.moveToFirst());
            Snapshot state = new Snapshot();
            state.openCount = cursor.getInt(cursor.getColumnIndexOrThrow("open_count"));
            state.closed = cursor.getInt(cursor.getColumnIndexOrThrow("closed")) == 1;
            state.byteCount = cursor.getInt(cursor.getColumnIndexOrThrow("byte_count"));
            state.payload = cursor.getString(cursor.getColumnIndexOrThrow("payload"));
            state.error = cursor.getString(cursor.getColumnIndexOrThrow("error"));
            return state;
        }
    }

    private static void waitForProviderOpen(ContentResolver resolver) {
        long end = SystemClock.uptimeMillis() + 20000;
        do { if (status(resolver).openCount == 1) return; SystemClock.sleep(50); } while (SystemClock.uptimeMillis() < end);
        fail("Native export did not open the synthetic SAF destination");
    }

    private static Snapshot waitForProviderClose(ContentResolver resolver) {
        long end = SystemClock.uptimeMillis() + 20000;
        do {
            Snapshot state = status(resolver);
            if (state.closed) return state;
            assertEquals("Synthetic stream error", "", state.error);
            SystemClock.sleep(50);
        } while (SystemClock.uptimeMillis() < end);
        throw new AssertionError("Native OutputStream did not reach EOF/close");
    }

    private static void waitForMonitor(Instrumentation.ActivityMonitor monitor) {
        long end = SystemClock.uptimeMillis() + 20000;
        do { if (monitor.getHits() == 1) return; SystemClock.sleep(50); } while (SystemClock.uptimeMillis() < end);
        fail("Export button did not launch ACTION_CREATE_DOCUMENT");
    }

    private void fill(String id, String value) throws Exception { execute("document.getElementById(" + quote(id) + ").value=" + quote(value) + ";"); }
    private void submit(String id) throws Exception { execute("document.getElementById(" + quote(id) + ").dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));"); }
    private void execute(String script) throws Exception { evaluateBody(script + " return true;"); }
    private Object evaluate(String expression) throws Exception { return evaluateBody("return (" + expression + ");"); }

    private Object evaluateBody(String body) throws Exception {
        CountDownLatch done = new CountDownLatch(1); AtomicReference<String> result = new AtomicReference<>();
        scenario.onActivity(activity -> activity.webViewForTest().evaluateJavascript("(function(){try{" + body + "}catch(error){return {__safError:String(error)};}})()", value -> { result.set(value); done.countDown(); }));
        assertTrue("WebView callback timed out", done.await(10, TimeUnit.SECONDS));
        Object value = new JSONArray("[" + result.get() + "]").get(0);
        if (value instanceof JSONObject && ((JSONObject) value).has("__safError")) fail(((JSONObject) value).getString("__safError"));
        return value;
    }

    private void waitFor(String label, String expression) throws Exception {
        long end = SystemClock.uptimeMillis() + 30000;
        do { if (Boolean.TRUE.equals(evaluate("Boolean(" + expression + ")"))) return; SystemClock.sleep(100); } while (SystemClock.uptimeMillis() < end);
        fail("Timed out waiting for " + label);
    }

    private static String quote(String value) { return JSONObject.quote(value); }
}
