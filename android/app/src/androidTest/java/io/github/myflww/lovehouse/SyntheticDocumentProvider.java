package io.github.myflww.lovehouse;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Binder;
import android.os.ParcelFileDescriptor;
import android.os.Process;
import java.io.ByteArrayOutputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Test-APK-only SAF destination. No filesystem calls, general URI access or personal data. */
public final class SyntheticDocumentProvider extends ContentProvider {
    public static final Uri DOCUMENT = Uri.parse(
        "content://io.github.myflww.lovehouse.preview.test.synthetic-saf/document/export.json");
    private static final int MAX_BYTES = 2 * 1024 * 1024;
    private final Object lock = new Object();
    private byte[] data = new byte[0];
    private int openCount;
    private boolean active, closed;
    private String error = "";
    private CountDownLatch allowRead = new CountDownLatch(1);

    @Override public boolean onCreate() { return true; }

    private void check(Uri uri) {
        if (!DOCUMENT.equals(uri)) throw new SecurityException("Only the fixed synthetic document exists");
        if (Binder.getCallingUid() == Process.myUid()) return;
        String[] packages = getContext().getPackageManager().getPackagesForUid(Binder.getCallingUid());
        if (packages != null) for (String name : packages) {
            if ("io.github.myflww.lovehouse.preview".equals(name)) return;
        }
        throw new SecurityException("Synthetic provider is restricted to the instrumented preview app");
    }

    @Override public String getType(Uri uri) { check(uri); return "application/json"; }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        check(uri);
        if (projection != null || selection != null || args != null || sort != null) {
            throw new IllegalArgumentException("Only the fixed synthetic status query is supported");
        }
        MatrixCursor result = new MatrixCursor(new String[]{"open_count", "closed", "byte_count", "payload", "error"}, 1);
        synchronized (lock) {
            result.addRow(new Object[]{openCount, closed ? 1 : 0, data.length,
                closed ? new String(data, StandardCharsets.UTF_8) : "", error});
        }
        return result;
    }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        check(uri);
        if (!("w".equals(mode) || "wt".equals(mode))) throw new FileNotFoundException("Synthetic document is write-only");
        final ParcelFileDescriptor[] pipe;
        final CountDownLatch gate;
        synchronized (lock) {
            if (active) throw new FileNotFoundException("Synthetic writer already active");
            try { pipe = ParcelFileDescriptor.createReliablePipe(); }
            catch (IOException exception) { throw new FileNotFoundException("Synthetic pipe unavailable"); }
            active = true; closed = false; data = new byte[0]; error = ""; openCount++;
            allowRead = new CountDownLatch(1); gate = allowRead;
        }
        Thread reader = new Thread(() -> {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            String failure = "";
            boolean reachedClose = false;
            try (ParcelFileDescriptor.AutoCloseInputStream stream = new ParcelFileDescriptor.AutoCloseInputStream(pipe[0])) {
                if (!gate.await(30, TimeUnit.SECONDS)) throw new IOException("Synthetic reader gate timed out");
                byte[] buffer = new byte[8192];
                int count;
                while ((count = stream.read(buffer)) != -1) {
                    if (bytes.size() + count > MAX_BYTES) throw new IOException("Synthetic document limit exceeded");
                    bytes.write(buffer, 0, count);
                }
                // EOF can only arrive after the native app closed its OutputStream.
                reachedClose = true;
            } catch (Exception exception) { failure = "Synthetic document stream did not complete"; }
            synchronized (lock) {
                data = bytes.toByteArray(); closed = reachedClose; active = false; error = failure;
            }
        }, "synthetic-saf-reader");
        reader.setDaemon(true); reader.start();
        return pipe[1];
    }

    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) {
        check(uri);
        if (selection != null || args != null || values == null || values.size() != 1
                || !Boolean.TRUE.equals(values.getAsBoolean("allow_read"))) throw new IllegalArgumentException("Unknown synthetic control");
        synchronized (lock) { allowRead.countDown(); }
        return 1;
    }

    @Override public int delete(Uri uri, String selection, String[] args) {
        check(uri);
        if (selection != null || args != null) throw new IllegalArgumentException("No synthetic selections");
        synchronized (lock) {
            if (active) throw new IllegalStateException("Cannot reset an active synthetic write");
            data = new byte[0]; openCount = 0; closed = false; error = "";
        }
        return 1;
    }

    @Override public Uri insert(Uri uri, ContentValues values) {
        check(uri); throw new UnsupportedOperationException("Synthetic document already exists");
    }
}
