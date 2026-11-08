package io.github.myflww.lovehouse;

import static org.junit.Assert.*;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.SystemClock;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** The real legacy IndexedDB -> native private staging -> Python engine path. */
@RunWith(AndroidJUnit4.class)
public final class AndroidMigrationSmokeTest {
    private String managementCookie;
    private String get(String url) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        if(managementCookie!=null) connection.setRequestProperty("Cookie",managementCookie);
        connection.setConnectTimeout(10000); connection.setReadTimeout(15000);
        try (InputStream input = connection.getInputStream(); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192]; int length;
            while ((length=input.read(buffer))!=-1) bytes.write(buffer,0,length);
            return new String(bytes.toByteArray(),StandardCharsets.UTF_8);
        } finally { connection.disconnect(); }
    }
    private Object evaluate(ActivityScenario<MainActivity> scenario, String script) throws Exception {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        scenario.onActivity(activity -> activity.webViewForTest().evaluateJavascript(script, value -> {
            result.set(value); done.countDown();
        }));
        assertTrue("Legacy WebView callback timed out", done.await(15, TimeUnit.SECONDS));
        return new org.json.JSONTokener(result.get()).nextValue();
    }

    private void await(ActivityScenario<MainActivity> scenario, String script) throws Exception {
        long deadline = SystemClock.uptimeMillis() + 60000;
        do { if (Boolean.TRUE.equals(evaluate(scenario, script))) return; SystemClock.sleep(100); }
        while (SystemClock.uptimeMillis() < deadline);
        fail("Legacy migration preparation did not complete");
    }

    @Test public void selectedLegacyLibraryMovesOnlyByExplicitNativeActionAndOriginalSurvives() throws Exception {
        Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        String phrase = "合成迁移约定 " + UUID.randomUUID();
        Intent intent = new Intent(instrumentation.getTargetContext(), MainActivity.class).putExtra("legacy", true);
        try (ActivityScenario<MainActivity> legacy = ActivityScenario.launch(intent)) {
            await(legacy, "!!window.LoveHouseApp && document.documentElement.dataset.appReady==='true'");
            evaluate(legacy, "window.androidMigrationReady=false;(async()=>{const s=window.LoveHouseApp.store;"
                + "const lib=await s.createLibrary('合成迁移库');window.androidMigrationLibrary=lib.id;"
                + "await s.saveMemory(lib.id,{title:'跨引擎约定',text:" + JSONObject.quote(phrase) + ",assistant:'合成回复',tags:['迁移验收']});"
                + "window.androidMigrationPayload=JSON.stringify(await s.exportLibrary(lib.id));window.androidMigrationReady=true;})()");
            await(legacy, "window.androidMigrationReady===true");
            Instrumentation.ActivityMonitor monitor = instrumentation.addMonitor(EngineActivity.class.getName(), null, false);
            EngineActivity engine = null;
            try {
                // This calls the exact same native boundary as the confirmed
                // migrate button, without accepting a JS confirmation dialog.
                evaluate(legacy, "window.LoveHouseNative.importLegacy(window.androidMigrationPayload);true");
                engine = (EngineActivity) instrumentation.waitForMonitorWithTimeout(monitor, 30000);
                assertNotNull("Migration did not open the full engine", engine);
                AtomicReference<String> url = new AtomicReference<>();
                final EngineActivity active = engine;
                long deadline = SystemClock.uptimeMillis()+120000;
                do {
                    instrumentation.runOnMainSync(() -> url.set(active.engineUrlForTest()));
                    if (url.get()!=null) break;
                    SystemClock.sleep(100);
                } while (SystemClock.uptimeMillis()<deadline);
                assertNotNull("Migrated engine did not become ready", url.get());
                AtomicReference<String> cookie = new AtomicReference<>();
                instrumentation.runOnMainSync(() -> cookie.set(active.engineManagementCookieForTest()));
                managementCookie = cookie.get();
                assertNotNull("Native UI capability was not supplied",managementCookie);
                JSONObject libraries = new JSONObject(get(url.get()+"api/libraries"));
                String graph = get(url.get()+"api/graph?library_id="+libraries.getString("selected_id"));
                assertTrue("Selected legacy original was not migrated",graph.contains(phrase));
                assertTrue("Selected legacy assistant reply was not migrated",graph.contains("合成回复"));
                instrumentation.runOnMainSync(active::finish);
                engine = null;
                evaluate(legacy, "window.androidLegacyIntact=false;window.LoveHouseApp.store.listMemories(window.androidMigrationLibrary,{})"
                    + ".then(rows=>window.androidLegacyIntact=rows.some(row=>row.text==="+JSONObject.quote(phrase)+"))");
                await(legacy,"window.androidLegacyIntact===true");
            } finally {
                instrumentation.removeMonitor(monitor);
                if (engine!=null) { final EngineActivity active=engine;instrumentation.runOnMainSync(active::finish); }
            }
        }
    }
}
