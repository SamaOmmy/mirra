package app.samantha.phone;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Map;

/** Minimal HTTP client: every request carries the PC's token. */
final class Http {
    private Http() {}

    static final class Error extends IOException {
        final int code;

        Error(int code, String message) {
            super(message);
            this.code = code;
        }
    }

    static byte[] request(String method, String url, String token, byte[] body, String contentType,
                          Map<String, String> headers, int readTimeoutMs) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setRequestMethod(method);
            c.setConnectTimeout(8000);
            c.setReadTimeout(readTimeoutMs);
            c.setRequestProperty("Authorization", "Bearer " + token);
            if (headers != null) {
                for (Map.Entry<String, String> h : headers.entrySet()) c.setRequestProperty(h.getKey(), h.getValue());
            }
            if (body != null) {
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", contentType);
                c.setFixedLengthStreamingMode(body.length);
                try (OutputStream out = c.getOutputStream()) {
                    out.write(body);
                }
            }
            int code = c.getResponseCode();
            InputStream in = code < 400 ? c.getInputStream() : c.getErrorStream();
            byte[] data = in == null ? new byte[0] : readAll(in);
            if (code >= 400) throw new Error(code, describe(code, data));
            return data;
        } finally {
            c.disconnect();
        }
    }

    private static String describe(int code, byte[] data) {
        if (code == 401) return "The PC did not accept the token. Pair again.";
        if (code == 429) return "The PC is rejecting this phone for now (too many wrong tries).";
        String text = new String(data).trim();
        return "The PC answered " + code + (text.isEmpty() || text.length() > 120 ? "" : ": " + text);
    }

    private static byte[] readAll(InputStream in) throws IOException {
        try (InputStream stream = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = stream.read(buf)) > 0) out.write(buf, 0, n);
            return out.toByteArray();
        }
    }
}
