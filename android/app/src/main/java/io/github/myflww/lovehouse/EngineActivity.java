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
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/** Full desktop memory engine, hosted exclusively inside this application's private process.
 * The original offline Activity/origin remains separate for lossless old-library migration.
 */
public final class EngineActivity extends Activity {
    private static final int OPEN_FILE = 141, SAVE_FILE = 142;
    private static final int MAX_EXPORT_BYTES = 64 * 1024 * 1024;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService work = Executors.newSingleThreadExecutor();
    private WebView browser;
    private LinearLayout root, nativeToolbar;
    private ProgressBar progress;
    private TextView status;
    private String engineUrl, engineManagementCookie;
    private Uri engineOrigin;
    private OnBackInvokedCallback backCallback;
    private ValueCallback<Uri[]> fileChooser;
    private PendingSave pendingSave;
    private boolean closed, preparingSave, migrationCompleted;

    private static final class PendingSave {
        final String id, filename, mime, event;
        final byte[] bytes;
        PendingSave(String id, String filename, String mime, String event, byte[] bytes) {
            this.id = id; this.filename = filename; this.mime = mime; this.event = event; this.bytes = bytes;
        }
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        migrationCompleted = saved != null && saved.getBoolean("migration_completed", false);
        final String migrationPath = migrationCompleted ? null : getIntent().getStringExtra("migration_path");
        getWindow().setStatusBarColor(Color.rgb(255, 249, 239));
        getWindow().setNavigationBarColor(Build.VERSION.SDK_INT >= 27
            ? Color.rgb(255, 249, 239) : Color.rgb(71, 52, 47));
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(255, 249, 239));
        LinearLayout toolbar = new LinearLayout(this); nativeToolbar = toolbar;
        toolbar.setPadding(12, 2, 12, 2);
        status = new TextView(this); status.setText("爱之屋 · 正在打开完整记忆引擎…");
        status.setTextColor(Color.rgb(91, 65, 65)); status.setTextSize(13);
        toolbar.addView(status, new LinearLayout.LayoutParams(0, -2, 1));
        Button offline = new Button(this); offline.setText("旧版离线库"); offline.setTextSize(12);
        offline.setContentDescription("打开原手机离线库，可先导出 JSON，再在完整记忆中导入；原记录不会被移动或清空");
        offline.setOnClickListener(view -> startActivity(new Intent(this, MainActivity.class).putExtra("legacy", true)));
        toolbar.addView(offline, new LinearLayout.LayoutParams(-2, -2));
        root.addView(toolbar, new LinearLayout.LayoutParams(-1, -2));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true); root.addView(progress, new LinearLayout.LayoutParams(-1, 4));
        setContentView(root);
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                android.graphics.Insets keyboard = insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, keyboard.bottom));
                return insets;
            }); root.requestApplyInsets();
        } else root.setFitsSystemWindows(true);
        if (!hasModernWebView()) {
            progress.setVisibility(View.GONE); status.setText("需要更新系统 WebView");
            new AlertDialog.Builder(this).setTitle("请先更新 Android System WebView")
                .setMessage("完整记忆页面需要 Chromium 109 或更新内核，建议在系统应用商店更新 Android System WebView 或 Chrome。更新后重新打开即可；不需要卸载爱之屋或清除数据，原离线库保持不变。")
                .setPositiveButton("更新后重试", (dialog, which) -> recreate())
                .setNegativeButton("打开旧版离线库", (dialog, which) -> {
                    startActivity(new Intent(this, MainActivity.class).putExtra("legacy", true)); finish();
                }).show();
            return;
        }
        if (Build.VERSION.SDK_INT >= 33) {
            backCallback = this::navigateBack;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, backCallback);
        }
        work.execute(() -> {
            try {
                synchronized (Python.class) {
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                }
                String dataDir = new java.io.File(getNoBackupFilesDir(), "love-house-engine").getAbsolutePath();
                String result = Python.getInstance().getModule("lovehouse_android")
                    .callAttr("start", dataDir, new AndroidCredentialVault(getApplicationContext())).toString();
                boolean migrationFailed = false;
                if (migrationPath != null && !migrationPath.isEmpty()) {
                    try {
                        java.io.File staged = new java.io.File(migrationPath).getCanonicalFile();
                        java.io.File allowed = new java.io.File(getNoBackupFilesDir(), "engine-imports").getCanonicalFile();
                        if (!allowed.equals(staged.getParentFile()) || !staged.getName().matches("[A-Za-z0-9_-]{1,100}\\.json"))
                            throw new IllegalArgumentException();
                        JSONObject migrated = new JSONObject(Python.getInstance().getModule("lovehouse_android")
                            .callAttr("import_legacy", staged.getAbsolutePath()).toString());
                        if (!migrated.optBoolean("imported", false) && !migrated.optBoolean("duplicate", false)) throw new IllegalStateException();
                        // The independent engine library is committed before the staging
                        // copy is removed; the original IndexedDB library stays intact.
                        if (staged.exists() && !staged.delete()) throw new java.io.IOException();
                        migrationCompleted = true;
                    } catch (Exception ignored) { migrationFailed = true; }
                }
                final boolean migrationWarning = migrationFailed;
                JSONObject response = new JSONObject(result);
                String url = response.getString("url");
                String uiSession = response.getString("ui_session");
                if (!uiSession.matches("[A-Za-z0-9_-]{40,200}")) throw new IllegalArgumentException();
                Uri origin = Uri.parse(url);
                if (!"http".equals(origin.getScheme()) || !"127.0.0.1".equals(origin.getHost())
                        || origin.getPort() < 1 || origin.getPort() > 65535 || origin.getUserInfo() != null
                        || !"/".equals(origin.getPath()) || origin.getQuery() != null || origin.getFragment() != null)
                    throw new IllegalArgumentException();
                main.post(() -> {
                    if (closed || isFinishing()) return;
                    engineUrl = url; engineOrigin = origin; engineManagementCookie = "LoveHouseUI=" + uiSession; openWebView();
                    if (migrationCompleted) getIntent().removeExtra("migration_path");
                    if (migrationWarning) message("旧版记忆未能迁入完整引擎，原离线库与迁移文件已保留。请返回旧版离线库重试，或先导出 JSON 再手动导入。");
                });
            } catch (Exception ignored) {
                main.post(() -> {
                    if (closed || isFinishing()) return;
                    progress.setVisibility(View.GONE); status.setText("完整引擎暂未启动");
                    new AlertDialog.Builder(this).setTitle("记忆引擎未能打开")
                        .setMessage("请检查设备可用空间并重新打开。旧版离线库仍可从右上角进入；没有清空任何记忆。")
                        .setPositiveButton("重试", (dialog, which) -> recreate())
                        .setNegativeButton("返回", (dialog, which) -> finish()).show();
                });
            }
        });
    }

    private boolean hasModernWebView() {
        try {
            android.content.pm.PackageInfo provider = WebViewCompat.getCurrentWebViewPackage(this);
            if (provider == null || provider.versionName == null) return false;
            java.util.regex.Matcher match = java.util.regex.Pattern.compile("^(\\d+)(?:\\.|$)").matcher(provider.versionName);
            return match.find() && Integer.parseInt(match.group(1)) >= 109;
        } catch (Exception ignored) { return false; }
    }

    boolean isEngineUri(Uri uri) {
        return uri != null && engineOrigin != null && "http".equals(uri.getScheme())
            && "127.0.0.1".equals(uri.getHost()) && uri.getPort() == engineOrigin.getPort()
            && uri.getUserInfo() == null;
    }

    private boolean trustedPage() {
        return browser != null && isEngineUri(Uri.parse(browser.getUrl() == null ? "" : browser.getUrl()));
    }

    private static WebResourceResponse blocked() {
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden",
            Collections.singletonMap("Cache-Control", "no-store"),
            new ByteArrayInputStream("Blocked".getBytes(StandardCharsets.UTF_8)));
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void openWebView() {
        nativeToolbar.setVisibility(View.VISIBLE);
        if (browser != null) { root.removeView(browser); browser.destroy(); }
        browser = new WebView(this); browser.setBackgroundColor(Color.rgb(16, 16, 20));
        root.addView(browser, new LinearLayout.LayoutParams(-1, 0, 1));
        WebSettings settings = browser.getSettings();
        settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false); settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false); settings.setSupportMultipleWindows(true);
        settings.setMediaPlaybackRequiresUserGesture(true); settings.setGeolocationEnabled(false);
        settings.setSafeBrowsingEnabled(true);
        WebView.setWebContentsDebuggingEnabled(false);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(browser, false);
        browser.addJavascriptInterface(new NativeFiles(), "LoveHouseEngineFiles");
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            WebViewCompat.addDocumentStartJavaScript(browser, nativeScript(),
                Collections.singleton("http://127.0.0.1:" + engineOrigin.getPort()));
        }
        browser.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return isEngineUri(request.getUrl()) ? null : blocked();
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (isEngineUri(request.getUrl())) return false;
                if (request.isForMainFrame() && request.hasGesture()) openExternal(request.getUrl());
                return true;
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!isEngineUri(Uri.parse(url))) return;
                progress.setVisibility(View.GONE); status.setText("爱之屋 · 完整记忆");
                nativeToolbar.setVisibility(View.GONE);
                view.evaluateJavascript(nativeScript(), null);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) loadFailure();
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame()) loadFailure();
            }
            @Override public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                if (browser == view) browser = null;
                fileChooser = null; pendingSave = null; preparingSave = false;
                root.removeView(view); view.destroy(); progress.setVisibility(View.GONE);
                if (!closed && !isFinishing()) new AlertDialog.Builder(EngineActivity.this)
                    .setTitle("界面需要重新打开").setMessage("系统已停止网页界面，已保存的记忆仍在此设备。")
                    .setPositiveButton("重新打开", (dialog, which) -> openWebView())
                    .setNegativeButton("返回", (dialog, which) -> finish()).show();
                return true;
            }
        });
        browser.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onConsoleMessage(ConsoleMessage message) { return true; }
            @Override public void onPermissionRequest(PermissionRequest request) { request.deny(); }
            @Override public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                callback.invoke(origin, false, false);
            }
            @Override public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, android.os.Message resultMsg) {
                if (!isUserGesture) return false;
                WebView temporary = new WebView(EngineActivity.this);
                temporary.getSettings().setJavaScriptEnabled(false);
                temporary.setWebViewClient(new WebViewClient() {
                    @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest request) {
                        openExternal(request.getUrl()); v.destroy(); return true;
                    }
                    @Override public boolean onRenderProcessGone(WebView v, RenderProcessGoneDetail detail) {
                        // This temporary view only hands an explicit external link
                        // to Android. It never owns migration or memory writes.
                        v.destroy(); message("外部链接没有打开，请重试；本机记忆已保留。"); return true;
                    }
                });
                ((WebView.WebViewTransport) resultMsg.obj).setWebView(temporary); resultMsg.sendToTarget(); return true;
            }
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (!trustedPage()) { callback.onReceiveValue(null); return true; }
                if (fileChooser != null) fileChooser.onReceiveValue(null);
                fileChooser = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*"); intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
                try { startActivityForResult(intent, OPEN_FILE); }
                catch (ActivityNotFoundException ignored) {
                    fileChooser.onReceiveValue(null); fileChooser = null; message("系统文件选择器不可用，未导入文件。");
                }
                return true;
            }
        });
        browser.setDownloadListener((url, agent, disposition, mime, size) -> {
            Uri uri = Uri.parse(url);
            if (isEngineUri(uri) && "/api/adapters/astrbot/package".equals(uri.getPath()))
                new NativeFiles().saveLocal("download_" + System.currentTimeMillis(), "LoveHouse-AstrBot-0.3.0-experimental.zip", url, "lovehouse-native-saved");
            else message("请使用页面内的导出按钮，选择系统保存位置。");
        });
        WebView target = browser;
        // Android's numeric loopback is reachable by other applications. The
        // native-only bootstrap capability authorizes our own WebView; opening
        // the root URL anonymously never grants management authority.
        CookieManager.getInstance().setCookie(engineUrl,
            engineManagementCookie + "; Path=/; HttpOnly; SameSite=Strict", accepted -> {
                if (closed || browser != target) return;
                if (Boolean.TRUE.equals(accepted)) target.loadUrl(engineUrl);
                else loadFailure();
            });
    }

    private void openExternal(Uri uri) {
        if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
        catch (ActivityNotFoundException ignored) { message("没有可打开链接的浏览器。"); }
    }

    private void loadFailure() {
        if (closed || isFinishing()) return;
        progress.setVisibility(View.GONE); status.setText("本机界面暂未连接");
        nativeToolbar.setVisibility(View.VISIBLE);
        new AlertDialog.Builder(this).setTitle("本机界面暂未连接")
            .setMessage("已保存的记忆没有清空。请重试；若系统关闭了应用进程，重新打开爱之屋。")
            .setPositiveButton("重试", (dialog, which) -> { if (browser != null) browser.loadUrl(engineUrl); else openWebView(); })
            .setNegativeButton("返回", (dialog, which) -> finish()).show();
    }

    private void message(String text) {
        if (!closed && !isFinishing()) new AlertDialog.Builder(this).setTitle("爱之屋").setMessage(text).setPositiveButton("知道了", null).show();
    }

    static String nativeScript() {
        return "(function(){if(window.__loveHouseAndroidBridge)return;window.__loveHouseAndroidBridge=true;"
            + "window.LoveHousePlatform='android';window.LoveHouseEnginePlatform='android';"
            + "var native=window.LoveHouseEngineFiles;var handlers={saveMemoryFile:{postMessage:function(o){native.saveText(String(o.request_id||''),String(o.filename||''),String(o.content||''),'lovehouse-file-saved');}},"
            + "exportAstrBotAdapter:{postMessage:function(o){native.saveLocal(String(o.request_id||''),'LoveHouse-AstrBot-0.3.0-experimental.zip',location.origin+'/api/adapters/astrbot/package','lovehouse-adapter-exported');}}};"
            + "window.webkit=window.webkit||{};window.webkit.messageHandlers=Object.assign({},window.webkit.messageHandlers||{},handlers);"
            + "var blobs=new Map(),create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);"
            + "URL.createObjectURL=function(blob){var url=create(blob);blobs.set(url,blob);return url;};"
            + "URL.revokeObjectURL=function(url){blobs.delete(url);return revoke(url);};"
            + "document.addEventListener('click',function(event){var a=event.target.closest&&event.target.closest('a[download]');if(!a)return;"
            + "var blob=blobs.get(a.href);if(!blob)return;event.preventDefault();event.stopPropagation();"
            + "if(blob.size>67108864){alert('文件超过手机版单次导出64MiB上限。请分库导出，原记忆已保留。');return;}"
            + "var reader=new FileReader();reader.onload=function(){var value=String(reader.result||'').split(',')[1]||'';native.saveBase64('download_'+Date.now(),String(a.download||'love-house.json'),String(blob.type||'application/octet-stream'),value);};reader.onerror=function(){alert('文件准备未完成，请重试导出。');};reader.readAsDataURL(blob);},true);"
            + "window.addEventListener('lovehouse-native-saved',function(event){var d=event.detail||{};if(d.error)alert(d.error);});"
            + "})()";
    }

    private static boolean allowedName(String filename) {
        return filename != null && !filename.isEmpty() && filename.length() <= 180
            && !filename.matches(".*[\\\\/:*?\"<>|\\p{Cntrl}].*") && !filename.endsWith(".") && !filename.endsWith(" ")
            && (filename.endsWith(".json") || filename.endsWith(".md") || filename.endsWith(".txt") || filename.endsWith(".zip"));
    }

    private static String mimeFor(String filename) {
        return filename.endsWith(".json") ? "application/json" : filename.endsWith(".md") ? "text/markdown"
            : filename.endsWith(".txt") ? "text/plain" : "application/zip";
    }

    private boolean beginSave(String id, String filename, String event) {
        if (closed || !trustedPage() || pendingSave != null || preparingSave) {
            fileResult(id, event, false, false, "另一个保存操作尚未结束，或页面已关闭。"); return false;
        }
        if (id == null || !id.matches("[A-Za-z0-9_-]{1,100}") || !allowedName(filename)
                || !("lovehouse-file-saved".equals(event) || "lovehouse-adapter-exported".equals(event) || "lovehouse-native-saved".equals(event))) {
            fileResult(id, event, false, false, "导出文件格式不正确。"); return false;
        }
        preparingSave = true; return true;
    }

    private void chooseSave(PendingSave save) {
        preparingSave = false;
        if (closed || !trustedPage()) return;
        pendingSave = save;
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType(save.mime); intent.putExtra(Intent.EXTRA_TITLE, save.filename);
        try { startActivityForResult(intent, SAVE_FILE); }
        catch (ActivityNotFoundException ignored) {
            pendingSave = null; fileResult(save.id, save.event, false, false, "系统文件保存窗口不可用，未保存。");
        }
    }

    public final class NativeFiles {
        @JavascriptInterface public void closeEngine() {
            main.post(() -> {
                if (closed || !trustedPage()) return;
                startActivity(new Intent(EngineActivity.this, MainActivity.class).putExtra("legacy", true));
                finish();
            });
        }
        @JavascriptInterface public void saveText(String id, String filename, String text, String event) {
            main.post(() -> {
                if (!beginSave(id, filename, event)) return;
                work.execute(() -> {
                    try {
                        if (text == null || text.length() > MAX_EXPORT_BYTES) throw new CharacterCodingException();
                        ByteBuffer buffer = StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                            .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(text));
                        if (buffer.remaining() > MAX_EXPORT_BYTES) throw new CharacterCodingException();
                        byte[] bytes = new byte[buffer.remaining()]; buffer.get(bytes);
                        main.post(() -> chooseSave(new PendingSave(id, filename, mimeFor(filename), event, bytes)));
                    } catch (Exception ignored) { saveFailure(id, event); }
                });
            });
        }
        @JavascriptInterface public void saveBase64(String id, String filename, String mime, String content) {
            main.post(() -> {
                if (!beginSave(id, filename, "lovehouse-native-saved")) return;
                work.execute(() -> {
                    try {
                        if (content == null || content.length() > ((MAX_EXPORT_BYTES + 2L) / 3L) * 4L + 4L) throw new java.io.IOException();
                        byte[] bytes = android.util.Base64.decode(content, android.util.Base64.DEFAULT);
                        if (bytes.length > MAX_EXPORT_BYTES) throw new java.io.IOException();
                        main.post(() -> chooseSave(new PendingSave(id, filename, mimeFor(filename), "lovehouse-native-saved", bytes)));
                    } catch (Exception ignored) { saveFailure(id, "lovehouse-native-saved"); }
                });
            });
        }
        @JavascriptInterface public void saveLocal(String id, String filename, String url, String event) {
            main.post(() -> {
                if (!beginSave(id, filename, event)) return;
                Uri uri = Uri.parse(url == null ? "" : url);
                if (!isEngineUri(uri) || !"/api/adapters/astrbot/package".equals(uri.getPath()) || uri.getQuery() != null || uri.getFragment() != null) {
                    preparingSave = false; fileResult(id, event, false, false, "只允许导出本机附带的插件文件。"); return;
                }
                String cookie = CookieManager.getInstance().getCookie(engineUrl);
                work.execute(() -> {
                    HttpURLConnection connection = null;
                    try {
                        connection = (HttpURLConnection) new URL(url).openConnection();
                        connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(10000); connection.setReadTimeout(15000);
                        if (cookie != null) connection.setRequestProperty("Cookie", cookie);
                        if (connection.getResponseCode() != 200 || connection.getContentLengthLong() > MAX_EXPORT_BYTES) throw new java.io.IOException();
                        byte[] bytes;
                        try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                            byte[] buffer = new byte[8192]; int count;
                            while ((count = input.read(buffer)) != -1) {
                                if (output.size() + count > MAX_EXPORT_BYTES) throw new java.io.IOException();
                                output.write(buffer, 0, count);
                            }
                            bytes = output.toByteArray();
                        }
                        main.post(() -> chooseSave(new PendingSave(id, filename, mimeFor(filename), event, bytes)));
                    } catch (Exception ignored) { saveFailure(id, event); }
                    finally { if (connection != null) connection.disconnect(); }
                });
            });
        }
    }

    private void saveFailure(String id, String event) {
        main.post(() -> { preparingSave = false; fileResult(id, event, false, false, "文件准备失败或超过64MiB，原记录已保留。"); });
    }

    @Override protected void onActivityResult(int code, int result, Intent data) {
        super.onActivityResult(code, result, data);
        if (code == OPEN_FILE) {
            ValueCallback<Uri[]> callback = fileChooser; fileChooser = null;
            Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
            if (callback != null) callback.onReceiveValue(uri != null && "content".equals(uri.getScheme()) ? new Uri[]{uri} : null);
        } else if (code == SAVE_FILE) {
            PendingSave save = pendingSave; pendingSave = null;
            if (save == null) return;
            Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
            if (uri == null) { fileResult(save.id, save.event, false, true, null); return; }
            if (!"content".equals(uri.getScheme())) { fileResult(save.id, save.event, false, false, "未获得有效的文件保存位置。"); return; }
            work.execute(() -> {
                boolean ok = false;
                try (OutputStream stream = getContentResolver().openOutputStream(uri, "wt")) {
                    if (stream == null) throw new java.io.IOException();
                    stream.write(save.bytes); stream.flush(); ok = true;
                } catch (Exception ignored) { /* Never log memory, URI or exception content. */ }
                final boolean saved = ok;
                main.post(() -> fileResult(save.id, save.event, saved, false, saved ? null : "文件写入失败，请检查保存位置与空间。"));
            });
        }
    }

    private void fileResult(String id, String event, boolean saved, boolean cancelled, String error) {
        if (closed || !trustedPage() || id == null || !id.matches("[A-Za-z0-9_-]{1,100}")
                || !("lovehouse-file-saved".equals(event) || "lovehouse-adapter-exported".equals(event) || "lovehouse-native-saved".equals(event))) return;
        try {
            JSONObject result = new JSONObject().put("request_id", id).put("saved", saved).put("cancelled", cancelled);
            if (error != null) result.put("error", error);
            browser.evaluateJavascript("window.dispatchEvent(new CustomEvent(" + JSONObject.quote(event) + ",{detail:" + result + "}));", null);
        } catch (Exception ignored) { /* Only controlled event metadata is returned. */ }
    }

    @SuppressLint("GestureBackNavigation")
    @Override public void onBackPressed() { navigateBack(); }

    private void navigateBack() {
        if (browser == null) { finish(); return; }
        browser.evaluateJavascript("(function(){var d=document.querySelector('dialog[open]');if(d){d.close();return true;}return false;})()", handled -> {
            if ("true".equals(handled)) return;
            if (browser != null && browser.canGoBack()) browser.goBack(); else finish();
        });
    }

    @Override protected void onResume() {
        super.onResume();
        // The original offline Activity rejects cookies globally. Returning to
        // this trusted engine restores only normal same-origin UI sessions.
        CookieManager.getInstance().setAcceptCookie(true);
        if (browser != null) browser.onResume();
    }

    @Override protected void onPause() {
        if (browser != null) browser.onPause();
        super.onPause();
    }

    @Override protected void onSaveInstanceState(Bundle out) {
        out.putBoolean("migration_completed", migrationCompleted);
        super.onSaveInstanceState(out);
    }

    @Override protected void onDestroy() {
        closed = true;
        if (Build.VERSION.SDK_INT >= 33 && backCallback != null)
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);
        if (fileChooser != null) { fileChooser.onReceiveValue(null); fileChooser = null; }
        pendingSave = null;
        if (browser != null) {
            browser.removeJavascriptInterface("LoveHouseEngineFiles"); browser.stopLoading();
            root.removeView(browser); browser.destroy(); browser = null;
        }
        work.shutdown();
        // The Python runtime retains the private controller while Android keeps
        // this application process alive. A process restart reopens persisted data.
        super.onDestroy();
    }

    WebView webViewForTest() { return browser; }
    String engineUrlForTest() { return engineUrl; }
    String engineManagementCookieForTest() { return engineManagementCookie; }
    boolean supportsFullWebViewForTest() { return hasModernWebView(); }
    int nativeToolbarVisibilityForTest() { return nativeToolbar.getVisibility(); }
    String nativeStatusForTest() { return status.getText().toString(); }
}
