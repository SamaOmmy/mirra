package app.samantha.phone;

import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.NoRouteToHostException;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.net.URL;
import java.net.UnknownHostException;
import java.util.Map;

/** Minimal HTTP client: every request carries the PC's token. Plain Java, so it is tested on the PC too. */
final class Net {
    private Net() {}

    static final int DEFAULT_PORT = 8787;
    /** The "error" text in the PC's JSON answers. (A pattern, so this class runs on a plain JVM in the tests.) */
    private static final java.util.regex.Pattern ERROR = java.util.regex.Pattern.compile("\"error\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");

    /**
     * "100.64.0.5" becomes "http://100.64.0.5:8787", "mypc:9000" becomes "http://mypc:9000"; https addresses
     * (Tailscale's HTTPS) keep their own port. Trailing slashes go.
     */
    static String normalize(String server) {
        String s = server.trim();
        if (s.isEmpty()) return s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        boolean https = s.startsWith("https://");
        if (!https && !s.startsWith("http://")) s = "http://" + s;
        String rest = s.substring(s.indexOf("://") + 3);
        int slash = rest.indexOf('/');
        String host = slash < 0 ? rest : rest.substring(0, slash);
        if (!https && !host.contains(":")) {
            s = s.substring(0, s.indexOf("://") + 3) + host + ":" + DEFAULT_PORT + (slash < 0 ? "" : rest.substring(slash));
        }
        return s;
    }

    static final class Error extends IOException {
        final int code;

        Error(int code, String message) {
            super(message);
            this.code = code;
        }
    }

    static byte[] request(String method, String url, String token, byte[] body, String contentType,
                          Map<String, String> headers, int readTimeoutMs) throws IOException {
        HttpURLConnection c = open(method, url, token, readTimeoutMs);
        try {
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
            check(c);
            return readAll(c.getInputStream());
        } finally {
            c.disconnect();
        }
    }

    static byte[] get(String url, String token) throws IOException {
        return request("GET", url, token, null, null, null, 10000);
    }

    static byte[] postJson(String url, String token, String json) throws IOException {
        return request("POST", url, token, json.getBytes("UTF-8"), "application/json", null, 10000);
    }

    /** A connection for a long response (the picture or the sound). The caller reads it and disconnects. */
    static HttpURLConnection stream(String url, String token, int readTimeoutMs) throws IOException {
        HttpURLConnection c = open("GET", url, token, readTimeoutMs);
        try {
            check(c);
        } catch (IOException e) {
            c.disconnect();
            throw e;
        }
        return c;
    }

    /** Saves a download to a file. */
    static void download(String url, String token, java.io.File to) throws IOException {
        HttpURLConnection c = open("GET", url, token, 60000);
        try {
            check(c);
            try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(to)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
        } finally {
            c.disconnect();
        }
    }

    private static HttpURLConnection open(String method, String url, String token, int readTimeoutMs) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(8000);
        c.setReadTimeout(readTimeoutMs);
        c.setUseCaches(false);
        if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
        return c;
    }

    private static void check(HttpURLConnection c) throws IOException {
        int code = c.getResponseCode();
        if (code < 400) return;
        InputStream err = c.getErrorStream();
        byte[] data = err == null ? new byte[0] : readAll(err);
        throw new Error(code, describe(code, data));
    }

    static String describe(int code, byte[] data) {
        if (code == 401) return "This PC no longer accepts this phone. Pair it again with a new code.";
        if (code == 429) return "The PC is refusing this phone for a few minutes (too many wrong tries).";
        if (code == 503) return "Too many devices are watching this PC right now.";
        String text = new String(data).trim();
        java.util.regex.Matcher error = ERROR.matcher(text);
        if (text.startsWith("{") && error.find()) {
            return error.group(1).replace("\\\"", "\"").replace("\\\\", "\\");
        }
        return "The PC answered " + code + (text.isEmpty() || text.length() > 160 ? "." : ": " + text);
    }

    /** A sentence for someone holding the phone, for any network failure. */
    static String explain(Exception e) {
        if (e instanceof Error) return e.getMessage();
        if (e instanceof UnknownHostException) return "Can't find that PC. Check the address, and that Tailscale is on in this phone.";
        if (e instanceof ConnectException || e instanceof NoRouteToHostException || e instanceof SocketTimeoutException) {
            return "Can't reach your PC. Check that Tailscale is on in this phone, and that the PC is on and awake.";
        }
        return "Can't reach your PC (" + e.getMessage() + ").";
    }

    static byte[] readAll(InputStream in) throws IOException {
        try (InputStream stream = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = stream.read(buf)) > 0) out.write(buf, 0, n);
            return out.toByteArray();
        }
    }

    static String host(String base) {
        try {
            String host = URI.create(base).getHost();
            return host == null ? base : host;
        } catch (RuntimeException e) {
            return base;
        }
    }

    /** -1, 0 or 1 like compareTo, for versions such as "0.5.0". */
    static int compareVersions(String a, String b) {
        String[] x = a.split("\\."), y = b.split("\\.");
        for (int i = 0; i < Math.max(x.length, y.length); i++) {
            int p = i < x.length ? parse(x[i]) : 0, q = i < y.length ? parse(y[i]) : 0;
            if (p != q) return p < q ? -1 : 1;
        }
        return 0;
    }

    private static int parse(String s) {
        try {
            return Integer.parseInt(s.replaceAll("\\D.*", ""));
        } catch (NumberFormatException e) {
            return 0;
        }
    }
}
