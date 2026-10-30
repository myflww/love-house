package io.github.myflww.lovehouse.upgradeqa;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Activity;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.Build;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Predicate;

/**
 * Developer-only UI probe across a real, persistent old-App -> new-App install.
 * It instruments itself, reads no app-private files, uses no JavaScript hooks,
 * and only enters the fixed synthetic record below on a disposable emulator.
 */
public final class UpgradeProbeInstrumentation extends Instrumentation {
    private static final String APP = "io.github.myflww.lovehouse.preview";
    private static final String CERT = "ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc";
    private static final String TITLE = "UPGRADE_SEED_080RC1";
    private static final String TEXT = "升级前的合成原文：海边🙂；Unicode e\u0301 / é；不能丢失。";
    private static final String REPLY = "升级前的合成回复：我记得这个约定❤️。";
    private static final String TAGS = "升级验收,只供测试";
    private static final long TIMEOUT = 45000;
    private Bundle arguments;
    private UiAutomation automation;
    private String stage = "arguments";

    @Override public void onCreate(Bundle args) {
        super.onCreate(args);
        arguments = args == null ? new Bundle() : new Bundle(args);
        start();
    }

    @Override public void onStart() {
        super.onStart();
        String mode = arguments.getString("mode", "");
        Bundle report = new Bundle();
        report.putString("mode", mode);
        report.putString("target_package", APP);
        report.putString("protocol", "love-house-ui-upgrade/v1");
        try {
            require(mode.equals("seed") || mode.equals("verify"));
            stage = "disposable_emulator";
            require(Build.VERSION.SDK_INT == 28 || Build.VERSION.SDK_INT == 36);
            Process prop = new ProcessBuilder("/system/bin/getprop", "ro.kernel.qemu").start();
            require(readUtf8(prop.getInputStream(), 128).trim().equals("1"));
            require(prop.waitFor() == 0);
            stage = "installed_identity";
            checkInstalledIdentity(mode);
            automation = getUiAutomation();
            AccessibilityServiceInfo info = automation.getServiceInfo();
            info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
                | AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
                | AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
            automation.setServiceInfo(info);
            stage = "launch_original_app";
            // Fixed public component, no user-supplied command arguments.
            try (ParcelFileDescriptor descriptor = automation.executeShellCommand(
                    "am start -W -n io.github.myflww.lovehouse.preview/io.github.myflww.lovehouse.MainActivity");
                 InputStream input = new ParcelFileDescriptor.AutoCloseInputStream(descriptor)) {
                readUtf8(input, 32768);
            }
            stage = "app_ready";
            waitFor(() -> enabledText("记一段", false) && presentText("默认记忆库", false));
            if (mode.equals("seed")) seed(); else verify();
            report.putBoolean("ok", true);
            report.putInt("api_level", Build.VERSION.SDK_INT);
            report.putInt("expected_version_code", mode.equals("seed") ? 1 : 2);
            report.putBoolean("same_original_certificate", true);
            report.putBoolean("original_text_preserved", true);
            report.putBoolean("assistant_reply_preserved", true);
            report.putBoolean("tags_preserved", true);
            finish(Activity.RESULT_OK, report);
        } catch (Throwable failure) {
            // Neither arbitrary tool output nor memory text is printed.
            report.putBoolean("ok", false);
            report.putString("error", "Upgrade UI check failed at " + stage);
            report.putString("exception", failure.getClass().getSimpleName());
            addDiagnostics(report);
            finish(1, report);
        }
    }

    @SuppressWarnings("deprecation")
    private void checkInstalledIdentity(String mode) throws Exception {
        PackageManager manager = getTargetContext().getPackageManager();
        PackageInfo info = manager.getPackageInfo(APP, PackageManager.GET_SIGNING_CERTIFICATES);
        require(info.packageName.equals(APP));
        require(info.versionCode == (mode.equals("seed") ? 1 : 2));
        require((mode.equals("seed") ? "0.1.0-preview1" : "0.8.0rc1").equals(info.versionName));
        Signature[] signatures = info.signingInfo.getApkContentsSigners();
        require(signatures != null && signatures.length == 1);
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray());
        StringBuilder hex = new StringBuilder();
        for (byte value : digest) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        require(CERT.equals(hex.toString()));
    }

    private void seed() throws Exception {
        stage = "seed_editor_click";
        require(!presentText(TITLE, false));
        clickText("记一段", false);
        stage = "seed_editor_fields";
        // Modern WebViews can expose the real controls before a separate
        // accessibility heading. Four actual inputs are the editor signal.
        recycle(editorFields());
        String[] values = {TITLE, TEXT, REPLY, TAGS};
        for (int index = 0; index < values.length; index++) {
            stage = "seed_field_" + index;
            List<AccessibilityNodeInfo> fields = editorFields();
            try {
                require(fields.size() == 4);
                AccessibilityNodeInfo field = fields.get(index);
                field.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.getId());
                Bundle value = new Bundle();
                value.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, values[index]);
                require(field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, value));
            } finally { recycle(fields); }
        }
        stage = "seed_commit";
        clickText("保存到本机", true);
        waitFor(() -> !presentText("记下一段原话", true) && presentText(TITLE, false));
        stage = "seed_read_back";
        openAndCheckRecord();
    }

    private void verify() throws Exception {
        stage = "upgrade_card_preserved";
        waitFor(() -> presentText(TITLE, false));
        stage = "upgrade_read_original";
        openAndCheckRecord();
    }

    private void openAndCheckRecord() throws Exception {
        clickText(TITLE, false);
        waitFor(() -> presentText("完整记忆", true));
        waitFor(() -> presentText(TEXT, true));
        require(presentText(REPLY, true));
        require(presentText("#升级验收", false));
        require(presentText("#只供测试", false));
    }

    /** Locate the actual four HTML form fields, excluding the background search box. */
    private List<AccessibilityNodeInfo> editorFields() throws Exception {
        long end = SystemClock.uptimeMillis() + TIMEOUT;
        do {
            List<AccessibilityNodeInfo> fields = collect(node -> node.isEditable()
                || "android.widget.EditText".contentEquals(node.getClassName() == null ? "" : node.getClassName()));
            if (fields.size() == 4) return fields;
            // Some old WebViews also expose the inert background search field.
            // Source DOM order is search, title, original text, reply, tags.
            if (fields.size() == 5 && presentText("保存到本机", false)) {
                fields.remove(0).recycle();
                return fields;
            }
            recycle(fields);
            SystemClock.sleep(100);
        } while (SystemClock.uptimeMillis() < end);
        throw new AssertionError();
    }

    private boolean enabledText(String text, boolean exact) {
        AccessibilityNodeInfo node = find(value -> value.isEnabled() && matches(value, text, exact));
        if (node == null) return false;
        node.recycle(); return true;
    }

    private boolean presentText(String text, boolean exact) {
        AccessibilityNodeInfo node = find(value -> matches(value, text, exact));
        if (node == null) return false;
        node.recycle(); return true;
    }

    private void clickText(String text, boolean exact) throws Exception {
        long end = SystemClock.uptimeMillis() + TIMEOUT;
        do {
            List<AccessibilityNodeInfo> candidates = collect(value -> value.isEnabled() && matches(value, text, exact));
            // Do not retry an aggregated WebView/container label forever.
            // Prefer direct short button labels, then try every other match.
            candidates.sort((left, right) -> Integer.compare(clickScore(left), clickScore(right)));
            try {
                for (AccessibilityNodeInfo candidate : candidates) {
                    AccessibilityNodeInfo node = AccessibilityNodeInfo.obtain(candidate);
                    for (int depth = 0; node != null && depth < 5; depth++) {
                        node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.getId());
                        if (!"android.webkit.WebView".contentEquals(node.getClassName() == null ? "" : node.getClassName())
                                && supportsClick(node) && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                            node.recycle(); return;
                        }
                        AccessibilityNodeInfo parent = node.getParent();
                        node.recycle(); node = parent;
                    }
                    if (node != null) node.recycle();
                }
            } finally { recycle(candidates); }
            SystemClock.sleep(100);
        } while (SystemClock.uptimeMillis() < end);
        throw new AssertionError();
    }

    private static boolean supportsClick(AccessibilityNodeInfo node) {
        if (node.isClickable()) return true;
        for (AccessibilityNodeInfo.AccessibilityAction action : node.getActionList()) {
            if (action.getId() == AccessibilityNodeInfo.ACTION_CLICK) return true;
        }
        return false;
    }

    private static int clickScore(AccessibilityNodeInfo node) {
        String type = node.getClassName() == null ? "" : node.getClassName().toString();
        int length = (node.getText() == null ? 0 : node.getText().length())
            + (node.getContentDescription() == null ? 0 : node.getContentDescription().length());
        return (type.endsWith("Button") ? 0 : 10000) + (supportsClick(node) ? 0 : 1000) + Math.min(length, 999);
    }

    private void addDiagnostics(Bundle report) {
        if (automation == null) return;
        try {
            List<AccessibilityNodeInfo> fields = collect(node -> node.isEditable()
                || "android.widget.EditText".contentEquals(node.getClassName() == null ? "" : node.getClassName()));
            report.putInt("editable_count", fields.size());
            recycle(fields);
            List<AccessibilityNodeInfo> matches = collect(node -> matches(node, "记一段", false)
                || matches(node, "保存到本机", false) || matches(node, "记下一段原话", false));
            report.putInt("editor_control_match_count", matches.size());
            StringBuilder types = new StringBuilder();
            for (int i = 0; i < Math.min(matches.size(), 12); i++) {
                AccessibilityNodeInfo node = matches.get(i);
                if (i != 0) types.append(';');
                types.append(node.getClassName()).append(":click=").append(supportsClick(node))
                    .append(":visible=").append(node.isVisibleToUser()).append(":enabled=").append(node.isEnabled());
            }
            report.putString("editor_control_types", types.toString());
            recycle(matches);
        } catch (Throwable ignored) { report.putString("diagnostics", "unavailable"); }
    }

    private boolean matches(AccessibilityNodeInfo node, String expected, boolean exact) {
        if (!APP.contentEquals(node.getPackageName() == null ? "" : node.getPackageName())) return false;
        // Text can be outside the viewport inside the scrollable detail sheet;
        // it is still a real accessibility node, not a hidden storage/API read.
        String text = node.getText() == null ? "" : node.getText().toString();
        String description = node.getContentDescription() == null ? "" : node.getContentDescription().toString();
        return exact ? expected.equals(text) || expected.equals(description)
                     : text.contains(expected) || description.contains(expected);
    }

    private AccessibilityNodeInfo find(Predicate<AccessibilityNodeInfo> condition) {
        List<AccessibilityNodeInfo> found = collect(condition);
        if (found.isEmpty()) return null;
        AccessibilityNodeInfo first = found.remove(0);
        recycle(found); return first;
    }

    private List<AccessibilityNodeInfo> collect(Predicate<AccessibilityNodeInfo> condition) {
        List<AccessibilityNodeInfo> found = new ArrayList<>();
        AccessibilityNodeInfo root = automation.getRootInActiveWindow();
        if (root == null) return found;
        ArrayDeque<AccessibilityNodeInfo> pending = new ArrayDeque<>();
        pending.add(root);
        while (!pending.isEmpty()) {
            AccessibilityNodeInfo node = pending.removeFirst();
            // Push in reverse so traversal preserves the HTML form's source order.
            for (int index = node.getChildCount() - 1; index >= 0; index--) {
                AccessibilityNodeInfo child = node.getChild(index);
                if (child != null) pending.addFirst(child);
            }
            if (condition.test(node)) found.add(node); else node.recycle();
        }
        return found;
    }

    private interface Check { boolean done() throws Exception; }
    private void waitFor(Check check) throws Exception {
        long end = SystemClock.uptimeMillis() + TIMEOUT;
        do { if (check.done()) return; SystemClock.sleep(100); } while (SystemClock.uptimeMillis() < end);
        throw new AssertionError();
    }
    private static void require(boolean value) { if (!value) throw new AssertionError(); }
    private static void recycle(List<AccessibilityNodeInfo> values) {
        for (AccessibilityNodeInfo node : values) node.recycle();
    }
    private static String readUtf8(InputStream stream, int maximum) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096]; int count;
        while ((count = stream.read(chunk)) != -1) {
            if (bytes.size() + count > maximum) throw new AssertionError();
            bytes.write(chunk, 0, count);
        }
        return new String(bytes.toByteArray(), StandardCharsets.UTF_8);
    }
}
