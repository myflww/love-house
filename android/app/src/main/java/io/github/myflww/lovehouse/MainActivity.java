package io.github.myflww.lovehouse;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowInsets;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import androidx.webkit.WebViewAssetLoader;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import java.io.ByteArrayInputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONException;
import org.json.JSONObject;

/** A private, offline application origin. There is no TCP listener or remote app page. */
public final class MainActivity extends Activity {
    static final String ORIGIN = "https://appassets.androidplatform.net";
    static final String HOME = ORIGIN + "/assets/web/index.html";
    private static final int OPEN_FILE = 41;
    private static final int SAVE_FILE = 42;
    private static final int MAX_EXPORT_BYTES = 32 * 1024 * 1024;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService files = Executors.newSingleThreadExecutor();
    private WebView browser;
    private ProgressBar progress;
    private LinearLayout root;
    private ValueCallback<Uri[]> fileChooser;
    private PendingSave pendingSave;
    private boolean closed;
    private OnBackInvokedCallback backCallback;

    private static final class PendingSave {
        final String id, filename, mime;
        final byte[] data;
        PendingSave(String id, String filename, String mime, byte[] data) {
            this.id = id; this.filename = filename; this.mime = mime; this.data = data;
        }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(255, 249, 239));
        getWindow().setNavigationBarColor(Build.VERSION.SDK_INT >= 27
            ? Color.rgb(255, 249, 239) : Color.rgb(71, 52, 47));
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(255, 249, 239));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true);
        root.addView(progress, new LinearLayout.LayoutParams(-1, 5));
        browser = new WebView(this);
        browser.setBackgroundColor(Color.rgb(255, 249, 239));
        root.addView(browser, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                android.graphics.Insets keyboard = insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, keyboard.bottom));
                return insets;
            });
            root.requestApplyInsets();
        } else {
            root.setFitsSystemWindows(true);
        }
        WebSettings settings = browser.getSettings();
        enableLocalScripts(settings);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        // Only user-selected SAF documents are granted; navigation to content:// is blocked.
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setGeolocationEnabled(false);
        settings.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptCookie(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(browser, false);
        WebView.setWebContentsDebuggingEnabled(false);
        browser.addJavascriptInterface(new NativeFiles(), "LoveHouseNative");
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            WebViewCompat.addDocumentStartJavaScript(browser,
                "window.LoveHousePlatform='android';", Collections.singleton(ORIGIN));
        }
        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this)).build();
        browser.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (!isLocal(uri) || !"GET".equals(request.getMethod())) return blocked();
                WebResourceResponse result = loader.shouldInterceptRequest(uri);
                if (result == null) return blocked();
                Map<String,String> headers = new HashMap<>();
                headers.put("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                    + "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
                    + "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'");
                headers.put("X-Content-Type-Options", "nosniff");
                headers.put("Referrer-Policy", "no-referrer");
                result.setResponseHeaders(headers);
                return result;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (isLocal(uri)) return false;
                if (request.isForMainFrame() && request.hasGesture() && "https".equals(uri.getScheme())) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
                    catch (ActivityNotFoundException ignored) { showMessage("没有可打开链接的浏览器。"); }
                }
                return true;
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!isLocal(Uri.parse(url))) return;
                progress.setVisibility(View.GONE);
                view.evaluateJavascript("window.LoveHousePlatform='android';", null);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showLoadFailure();
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame()) showLoadFailure();
            }
            @Override public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                // A dead renderer cannot be reused. Leave the origin's IndexedDB
                // intact and create a new WebView only when the user reopens it.
                if (browser == view) browser = null;
                fileChooser = null;
                pendingSave = null;
                root.removeView(view);
                view.destroy();
                progress.setVisibility(View.GONE);
                if (!closed && !isFinishing()) new AlertDialog.Builder(MainActivity.this)
                    .setTitle("界面需要重新打开")
                    .setMessage("系统已停止网页界面。已保存的记忆仍保留在此设备，请重新打开爱之屋。")
                    .setPositiveButton("重新打开", (dialog, which) -> recreate())
                    .setNegativeButton("关闭", (dialog, which) -> finish()).show();
                return true;
            }
        });
        browser.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onConsoleMessage(ConsoleMessage message) { return true; }
            @Override public void onPermissionRequest(PermissionRequest request) { request.deny(); }
            @Override public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                callback.invoke(origin, false, false);
            }
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileChooser != null) fileChooser.onReceiveValue(null);
                fileChooser = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/json", "text/plain", "application/octet-stream"});
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
                try { startActivityForResult(intent, OPEN_FILE); }
                catch (ActivityNotFoundException ignored) {
                    fileChooser.onReceiveValue(null); fileChooser = null;
                    showMessage("系统文件选择器不可用，未导入文件。");
                }
                return true;
            }
        });
        browser.loadUrl(HOME);
        if (Build.VERSION.SDK_INT >= 33) {
            backCallback = this::navigateBack;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT, backCallback);
        }
    }

    static boolean isLocal(Uri uri) {
        return "https".equals(uri.getScheme()) && "appassets.androidplatform.net".equals(uri.getHost())
            && uri.getPort() == -1 && uri.getUserInfo() == null && uri.getPath() != null
            && uri.getPath().startsWith("/assets/web/");
    }

    @SuppressLint("SetJavaScriptEnabled")
    private static void enableLocalScripts(WebSettings settings) {
        // Only the bundled local application executes scripts; navigation,
        // resource loading and CSP reject remote pages and imported active text.
        settings.setJavaScriptEnabled(true);
    }

    private static WebResourceResponse blocked() {
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden",
            Collections.singletonMap("Cache-Control", "no-store"),
            new ByteArrayInputStream("Blocked".getBytes(StandardCharsets.UTF_8)));
    }

    private void showMessage(String message) {
        if (!closed && !isFinishing()) new AlertDialog.Builder(this).setTitle("爱之屋")
            .setMessage(message).setPositiveButton("知道了", null).show();
    }

    private void showLoadFailure() {
        if (closed || isFinishing()) return;
        progress.setVisibility(View.GONE);
        new AlertDialog.Builder(this).setTitle("界面暂时未能打开")
            .setMessage("请确认系统 Android System WebView 可用。当前记忆数据未被清空。")
            .setPositiveButton("重试", (dialog, which) -> {
                if (browser != null) browser.loadUrl(HOME); else recreate();
            })
            .setNegativeButton("关闭", (dialog, which) -> finish()).show();
    }

    public final class NativeFiles {
        @JavascriptInterface public void saveFile(String requestId, String filename, String mime, String text) {
            if (requestId == null || !requestId.matches("[A-Za-z0-9_-]{1,100}")) return;
            if (filename == null || filename.length() > 180 || filename.matches(".*[\\\\/:*?\"<>|\\p{Cntrl}].*")
                || filename.endsWith(".") || filename.endsWith(" ") || text == null || text.length() > MAX_EXPORT_BYTES
                || !(filename.endsWith(".json") && "application/json".equals(mime)
                    || filename.endsWith(".md") && "text/markdown".equals(mime))) {
                main.post(() -> fileResult(requestId, false, false, "导出文件格式或大小不正确。"));
                return;
            }
            final byte[] data;
            try {
                ByteBuffer encoded = StandardCharsets.UTF_8.newEncoder()
                    .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                    .encode(CharBuffer.wrap(text));
                if (encoded.remaining() > MAX_EXPORT_BYTES) throw new CharacterCodingException();
                data = new byte[encoded.remaining()]; encoded.get(data);
            } catch (CharacterCodingException ignored) {
                main.post(() -> fileResult(requestId, false, false, "内容过大或包含无效字符，未保存。"));
                return;
            }
            main.post(() -> {
                if (closed || browser == null || pendingSave != null || !isLocal(Uri.parse(browser.getUrl() == null ? "" : browser.getUrl()))) {
                    fileResult(requestId, false, false, "另一个保存操作尚未结束，或页面已关闭。"); return;
                }
                pendingSave = new PendingSave(requestId, filename, mime, data);
                Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType(mime); intent.putExtra(Intent.EXTRA_TITLE, filename);
                try { startActivityForResult(intent, SAVE_FILE); }
                catch (ActivityNotFoundException ignored) {
                    pendingSave = null; fileResult(requestId, false, false, "系统文件保存窗口不可用，未保存。");
                }
            });
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == OPEN_FILE) {
            ValueCallback<Uri[]> callback = fileChooser; fileChooser = null;
            Uri uri = resultCode == RESULT_OK && data != null ? data.getData() : null;
            if (callback != null) callback.onReceiveValue(uri != null && "content".equals(uri.getScheme()) ? new Uri[]{uri} : null);
        } else if (requestCode == SAVE_FILE) {
            PendingSave save = pendingSave; pendingSave = null;
            if (save == null) return;
            Uri uri = resultCode == RESULT_OK && data != null ? data.getData() : null;
            if (uri == null) { fileResult(save.id, false, true, null); return; }
            if (!"content".equals(uri.getScheme())) { fileResult(save.id, false, false, "未获得有效的文件保存位置。"); return; }
            files.execute(() -> {
                boolean saved = false;
                try {
                    try (OutputStream stream = getContentResolver().openOutputStream(uri, "wt")) {
                        if (stream == null) throw new java.io.IOException();
                        stream.write(save.data); stream.flush();
                    }
                    saved = true;
                } catch (Exception ignored) { /* Never log paths, memory text or exception content. */ }
                final boolean complete = saved;
                main.post(() -> fileResult(save.id, complete, false, complete ? null : "文件写入失败，请检查保存位置与空间。"));
            });
        }
    }

    private void fileResult(String requestId, boolean saved, boolean cancelled, String error) {
        if (closed || browser == null) return;
        JSONObject result = new JSONObject();
        try {
            result.put("requestId", requestId); result.put("saved", saved); result.put("cancelled", cancelled);
            if (error != null) result.put("error", error);
        } catch (JSONException ignored) { return; }
        browser.evaluateJavascript("window.dispatchEvent(new CustomEvent('lovehouse-save-result',{detail:"
            + result.toString() + "}));", null);
    }

    // API 33+ gestures use the registered OnBackInvokedCallback above. Keep
    // this legacy callback for Android 8-12 and physical back buttons.
    @SuppressLint("GestureBackNavigation")
    @Override public void onBackPressed() {
        navigateBack();
    }

    private void navigateBack() {
        if (browser == null) { finish(); return; }
        browser.evaluateJavascript("(function(){var d=document.querySelector('dialog[open]');"
            + "if(d){d.close();return true;}return false;})()", handled -> {
                if ("true".equals(handled)) return;
                if (browser != null && browser.canGoBack()) browser.goBack(); else finish();
            });
    }

    @Override protected void onDestroy() {
        closed = true;
        if (Build.VERSION.SDK_INT >= 33 && backCallback != null) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);
        }
        if (fileChooser != null) { fileChooser.onReceiveValue(null); fileChooser = null; }
        pendingSave = null;
        if (browser != null) {
            browser.removeJavascriptInterface("LoveHouseNative");
            browser.stopLoading(); root.removeView(browser); browser.destroy(); browser = null;
        }
        files.shutdown();
        super.onDestroy();
    }

    WebView webViewForTest() { return browser; }
}
