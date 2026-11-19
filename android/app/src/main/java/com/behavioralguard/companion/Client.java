package com.behavioralguard.companion;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONObject;
import java.io.*;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.cert.X509Certificate;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.*;

final class Client {
    static final String PREFS = "guard_private", KEY_ALIAS = "guard_pairing_key";
    static final class Credentials {
        String host, token, pin, device;
        int port;
    }
    static SharedPreferences prefs(Context context) { return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE); }
    static Credentials parse(String link) throws Exception {
        Uri uri = Uri.parse(link.trim());
        if (!"behavioralguard-v2".equals(uri.getScheme()) || !"pair".equals(uri.getHost())) throw new IOException("Use the V2 pairing code from your PC.");
        Credentials result = new Credentials();
        result.host = uri.getQueryParameter("host");
        result.port = Integer.parseInt(uri.getQueryParameter("port"));
        result.token = uri.getQueryParameter("token"); result.pin = uri.getQueryParameter("pin");
        result.device = java.util.UUID.randomUUID().toString().replace("-", "");
        validate(result);
        return result;
    }
    static void validate(Credentials value) throws IOException {
        if (value.host == null || !value.host.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}") || value.port < 1 || value.port > 65535 ||
            value.token == null || !value.token.matches("[A-Za-z0-9_-]{40,64}") || value.pin == null || !value.pin.matches("[a-f0-9]{64}"))
            throw new IOException("Invalid pairing code.");
        String[] parts = value.host.split("\\."); int a = Integer.parseInt(parts[0]), b = Integer.parseInt(parts[1]);
        for (String part : parts) if (Integer.parseInt(part) > 255) throw new IOException("Invalid PC address.");
        if (!(a == 10 || a == 127 || a == 192 && b == 168 || a == 172 && b >= 16 && b <= 31))
            throw new IOException("Use a PC on your local Wi-Fi.");
    }
    static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias(KEY_ALIAS)) return (SecretKey) store.getKey(KEY_ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }
    static void save(Context context, Credentials value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] secret = cipher.doFinal(value.token.getBytes(StandardCharsets.UTF_8));
        prefs(context).edit().putString("host", value.host).putInt("port", value.port).putString("pin", value.pin)
            .putString("device", value.device).putString("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
            .putString("secret", Base64.encodeToString(secret, Base64.NO_WRAP)).remove("alert").remove("answered").apply();
    }
    static Credentials load(Context context) throws Exception {
        SharedPreferences p = prefs(context); if (!p.contains("secret")) throw new IOException("Pair your phone first.");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(p.getString("iv", ""), Base64.NO_WRAP)));
        Credentials value = new Credentials(); value.host = p.getString("host", ""); value.port = p.getInt("port", 8766);
        value.pin = p.getString("pin", ""); value.device = p.getString("device", "");
        value.token = new String(cipher.doFinal(Base64.decode(p.getString("secret", ""), Base64.NO_WRAP)), StandardCharsets.UTF_8);
        validate(value); return value;
    }
    static final class ApiError extends IOException {
        final int status;
        ApiError(int code, String message) { super(message); status = code; }
    }
    static String hex(byte[] data) { StringBuilder value = new StringBuilder(); for (byte b : data) value.append(String.format("%02x", b & 255)); return value.toString(); }
    static HttpsURLConnection connection(Credentials value, String path) throws Exception {
        validate(value);
        TrustManager[] trust = { new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            public void checkClientTrusted(X509Certificate[] chain, String type) throws java.security.cert.CertificateException { throw new java.security.cert.CertificateException(); }
            public void checkServerTrusted(X509Certificate[] chain, String type) throws java.security.cert.CertificateException {
                try {
                    if (chain.length == 0 || !MessageDigest.isEqual(hex(MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded())).getBytes(StandardCharsets.US_ASCII), value.pin.getBytes(StandardCharsets.US_ASCII)))
                        throw new java.security.cert.CertificateException("PC identity changed. Pair again.");
                    chain[0].checkValidity();
                } catch (java.security.cert.CertificateException e) { throw e; }
                catch (Exception e) { throw new java.security.cert.CertificateException(e); }
            }
        }};
        SSLContext ssl = SSLContext.getInstance("TLS"); ssl.init(null, trust, new SecureRandom());
        HttpsURLConnection connection = (HttpsURLConnection) new URL("https://"+value.host+":"+value.port+path).openConnection();
        connection.setSSLSocketFactory(ssl.getSocketFactory());
        // The certificate's exact SHA-256 pin authenticates the PC, including its local IP.
        connection.setHostnameVerifier((hostname, session) -> true);
        connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(8000); connection.setReadTimeout(30000);
        connection.setRequestProperty("Authorization", "Bearer "+value.token);
        connection.setRequestProperty("X-Guard-Device", value.device);
        return connection;
    }
    static JSONObject request(Credentials value, String path, JSONObject body) throws Exception {
        HttpsURLConnection connection = connection(value, path);
        try { return exchange(connection, body); } finally { connection.disconnect(); }
    }
    static JSONObject exchange(HttpsURLConnection connection, JSONObject body) throws Exception {
        if (body != null) {
            connection.setRequestMethod("POST"); connection.setDoOutput(true); connection.setRequestProperty("Content-Type", "application/json");
            byte[] data = body.toString().getBytes(StandardCharsets.UTF_8); connection.setFixedLengthStreamingMode(data.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(data); }
        }
        int code = connection.getResponseCode(); InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        if (stream != null) try (InputStream input = stream) { byte[] buffer = new byte[2048]; int count; while ((count=input.read(buffer)) != -1) { if (bytes.size()+count > 32768) throw new IOException("Invalid PC response."); bytes.write(buffer, 0, count); } }
        JSONObject result = new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
        if (code != 200) throw new ApiError(code, result.optString("error", "Connection failed."));
        return result;
    }
    static JSONObject activeAlert(Context context) {
        SharedPreferences state = prefs(context);
        try {
            JSONObject alert = new JSONObject(state.getString("alert", ""));
            return alert.optString("id").equals(state.getString("answered", "")) ? null : alert;
        }
        catch (org.json.JSONException error) { return null; }
    }
    static void respond(Context context, String identifier, boolean answer, String code) throws Exception {
        JSONObject body = new JSONObject().put("id", identifier).put("answer", answer);
        if (answer) body.put("code", code);
        request(load(context), "/v1/respond", body);
        SharedPreferences state = prefs(context);
        state.edit().putString("answered", identifier).apply();
    }
}
