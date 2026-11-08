package io.github.myflww.lovehouse;

import static org.junit.Assert.*;
import android.os.SystemClock;
import android.view.View;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Real device-provider boundary, including the old API28 image's WebView66. */
@RunWith(AndroidJUnit4.class)
public final class AndroidWebViewCompatibilityTest {
    @Test public void providerEitherLoadsTheFullUiOrExplainsTheRequiredUpdate() throws Exception {
        try (ActivityScenario<EngineActivity> scenario = ActivityScenario.launch(EngineActivity.class)) {
            AtomicBoolean supported = new AtomicBoolean();
            scenario.onActivity(activity -> supported.set(activity.supportsFullWebViewForTest()));
            if (!supported.get()) {
                scenario.onActivity(activity -> {
                    assertNull("Old provider must not start the memory engine", activity.engineUrlForTest());
                    assertEquals("需要更新系统 WebView", activity.nativeStatusForTest());
                    assertEquals(View.VISIBLE, activity.nativeToolbarVisibilityForTest());
                });
                boolean dialog = false;
                long deadline = SystemClock.uptimeMillis() + 10000;
                do {
                    AccessibilityNodeInfo window = InstrumentationRegistry.getInstrumentation()
                        .getUiAutomation().getRootInActiveWindow();
                    if (window != null) {
                        dialog = !window.findAccessibilityNodeInfosByText("请先更新 Android System WebView").isEmpty();
                        window.recycle();
                    }
                    if (dialog) break;
                    SystemClock.sleep(100);
                } while (SystemClock.uptimeMillis() < deadline);
                assertTrue("Old provider must show an actionable native update dialog", dialog);
            } else {
                boolean ready = false;
                long deadline = SystemClock.uptimeMillis() + 120000;
                do {
                    CountDownLatch callback = new CountDownLatch(1);
                    AtomicBoolean value = new AtomicBoolean();
                    scenario.onActivity(activity -> {
                        if (activity.webViewForTest() == null) { callback.countDown(); return; }
                        boolean toolbarHidden = activity.nativeToolbarVisibilityForTest() == View.GONE;
                        activity.webViewForTest().evaluateJavascript(
                            "typeof S!=='undefined' && S.mode==='serve'", result -> {
                                value.set(toolbarHidden && "true".equals(result)); callback.countDown();
                            });
                    });
                    assertTrue("Native WebView callback did not finish", callback.await(15, TimeUnit.SECONDS));
                    ready = value.get();
                    if (ready) break;
                    SystemClock.sleep(100);
                } while (SystemClock.uptimeMillis() < deadline);
                assertTrue("Supported provider must load the real bundled UI", ready);
                scenario.onActivity(activity -> {
                    assertNotNull(activity.engineUrlForTest());
                    assertEquals(View.GONE, activity.nativeToolbarVisibilityForTest());
                });
            }
        }
    }
}
