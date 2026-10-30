package io.github.myflww.lovehouse.remoteqa;

import android.app.Activity;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.webkit.SslErrorHandler;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** Independent QA APK only. Production MainActivity and its offline store are untouched. */
public final class RemoteGatewayActivity extends Activity {
    private WebView webView;
    private Uri origin;
    public int sslErrors;
    public int mainFrameHttpErrors;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        origin = Uri.parse(getIntent().getStringExtra("gatewayOrigin"));
        if (!"https".equals(origin.getScheme()) || !("127.0.0.1".equals(origin.getHost()) || "localhost".equals(origin.getHost()))
                || origin.getPort() < 1 || origin.getPort() > 65535 || origin.getUserInfo() != null || origin.getQuery() != null) {
            throw new IllegalArgumentException("Only the isolated HTTPS fixture origin is allowed");
        }
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        webView.setWebViewClient(new WebViewClient() {
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                sslErrors++;
                handler.cancel();
            }
            @Override public void onReceivedHttpError(WebView view, android.webkit.WebResourceRequest request, android.webkit.WebResourceResponse response) {
                if (request.isForMainFrame()) mainFrameHttpErrors++;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
                Uri url = request.getUrl();
                return !("https".equals(url.getScheme()) && origin.getHost().equals(url.getHost()) && url.getPort() == origin.getPort());
            }
        });
        setContentView(webView);
        webView.loadUrl(origin.toString() + "/mobile");
    }

    public WebView webView() { return webView; }
    @Override public void onDestroy() {
        if (webView != null) { webView.destroy(); webView = null; }
        super.onDestroy();
    }
}
