package io.github.myflww.lovehouse;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** App-private credentials. The AES key never leaves Android Keystore.
 * This object is passed to Python only, never registered as a Javascript interface.
 */
public final class AndroidCredentialVault {
    private static final String ALIAS = "local.lovehouse.credentials.v1";
    private static final Object LOCK = new Object();
    private final SharedPreferences values;

    public AndroidCredentialVault(Context context) {
        values = context.getApplicationContext().getSharedPreferences("lovehouse-encrypted-credentials-v1", Context.MODE_PRIVATE);
    }

    private SecretKey encryptionKey(boolean create) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        java.security.Key key = store.getKey(ALIAS, null);
        if (key instanceof SecretKey) return (SecretKey) key;
        if (!create) return null;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
            KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).setRandomizedEncryptionRequired(true).build());
        return generator.generateKey();
    }

    /** Fixed protocol shared with the embedded Python credential adapter.
     * Errors intentionally contain no credential, filesystem path or exception text.
     */
    public String call(String operation, String account, String value) {
        synchronized (LOCK) {
            try {
                if (account == null || !account.matches("[a-f0-9]{64}")) return "{\"ok\":false}";
                if ("delete".equals(operation)) {
                    boolean committed = values.edit().remove(account).commit();
                    return new JSONObject().put("ok", committed && !values.contains(account)).toString();
                }
                if ("set".equals(operation)) {
                    if (value == null || value.trim().isEmpty() || value.getBytes(StandardCharsets.UTF_8).length > 32768
                            || value.indexOf('\0') >= 0 || value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0)
                        return "{\"ok\":false}";
                    Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                    cipher.init(Cipher.ENCRYPT_MODE, encryptionKey(true));
                    cipher.updateAAD(account.getBytes(StandardCharsets.US_ASCII));
                    byte[] plaintext = value.getBytes(StandardCharsets.UTF_8);
                    byte[] ciphertext;
                    try { ciphertext = cipher.doFinal(plaintext); }
                    finally { Arrays.fill(plaintext, (byte) 0); }
                    String record = new JSONObject().put("v", 1)
                        .put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                        .put("data", Base64.encodeToString(ciphertext, Base64.NO_WRAP)).toString();
                    return new JSONObject().put("ok", values.edit().putString(account, record).commit()).toString();
                }
                if (!"get".equals(operation)) return "{\"ok\":false}";
                String record = values.getString(account, null);
                if (record == null) return "{\"ok\":true,\"value\":\"\"}";
                if (record.length() > 66000) return "{\"ok\":false}";
                JSONObject encoded = new JSONObject(record);
                if (encoded.getInt("v") != 1) return "{\"ok\":false}";
                SecretKey key = encryptionKey(false);
                if (key == null) return "{\"ok\":false}";
                byte[] iv = Base64.decode(encoded.getString("iv"), Base64.NO_WRAP);
                byte[] ciphertext = Base64.decode(encoded.getString("data"), Base64.NO_WRAP);
                if (iv.length != 12 || ciphertext.length > 32784) return "{\"ok\":false}";
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, iv));
                cipher.updateAAD(account.getBytes(StandardCharsets.US_ASCII));
                byte[] plaintext = cipher.doFinal(ciphertext);
                try { return new JSONObject().put("ok", true).put("value", new String(plaintext, StandardCharsets.UTF_8)).toString(); }
                finally { Arrays.fill(plaintext, (byte) 0); }
            } catch (Exception ignored) {
                // Corrupt, locked or invalidated system credentials remain unavailable;
                // do not silently replace them or include their contents in diagnostics.
                return "{\"ok\":false}";
            }
        }
    }
}
