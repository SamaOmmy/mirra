package app.samantha.phone;

import java.io.ByteArrayInputStream;
import java.net.HttpURLConnection;
import java.util.Arrays;

/**
 * Checks the plain-Java parts of the Android app on an ordinary JVM (run by tests/test_android.py):
 *
 *   NetCheck                     address normalizing, versions, the picture stream reader
 *   NetCheck BASE TOKEN CODE     plus a real session against a running server: pair with CODE, read pictures
 */
public final class NetCheck {
    private static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
        System.out.println("ok   " + what);
    }

    public static void main(String[] args) throws Exception {
        check(Net.normalize("100.64.0.5").equals("http://100.64.0.5:8787"), "a bare address gets http and the default port");
        check(Net.normalize(" mypc:9000/ ").equals("http://mypc:9000"), "a port is kept, spaces and slashes go");
        check(Net.normalize("https://pc.tail1.ts.net/").equals("https://pc.tail1.ts.net"), "https keeps its own port");
        check(Net.normalize("http://pc").equals("http://pc:8787"), "http without a port gets the default port");
        check(Net.compareVersions("0.5.0", "0.4.1") > 0 && Net.compareVersions("0.10.0", "0.9.9") > 0, "versions compare as numbers");
        check(Net.compareVersions("0.5", "0.5.0") == 0 && Net.compareVersions("0.4.1", "0.5.0") < 0, "missing parts count as 0");
        check(Net.describe(401, new byte[0]).contains("Pair it again"), "a refused token says to pair again");
        check(Net.describe(403, "{\"error\":\"That code is wrong\"}".getBytes()).equals("That code is wrong"), "the PC's own error is shown");

        byte[] one = {(byte) 0xff, (byte) 0xd8, 1, 2, 3}, two = {(byte) 0xff, (byte) 0xd8, 9};
        String stream = "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 5\r\n\r\n" + new String(one, "ISO-8859-1")
                + "\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 3\r\n\r\n" + new String(two, "ISO-8859-1") + "\r\n";
        Mjpeg m = new Mjpeg(new ByteArrayInputStream(stream.getBytes("ISO-8859-1")));
        byte[] a = m.next();
        check(Arrays.equals(Arrays.copyOf(a, m.length()), one), "the first picture is read whole");
        byte[] b = m.next();
        check(Arrays.equals(Arrays.copyOf(b, m.length()), two), "the second picture follows");
        check(m.next() == null, "the end of the stream is noticed");

        if (args.length == 3) {
            String base = Net.normalize(args[0]);
            try {
                Net.postJson(base + "/api/pair", null, "{\"code\":\"000000\"}");
                check(false, "a wrong code is refused");
            } catch (Net.Error e) {
                check(e.code == 403, "a wrong code is refused");
            }
            String answer = new String(Net.postJson(base + "/api/pair", null, "{\"code\":\"" + args[2] + "\",\"device\":\"JVM\"}"), "UTF-8");
            check(answer.contains("\"token\":\"" + args[1] + "\""), "the right code gives the token");
            HttpURLConnection c = Net.stream(base + "/stream", args[1], 15000);
            Mjpeg pictures = new Mjpeg(c.getInputStream());
            for (int i = 0; i < 3; i++) {
                byte[] jpeg = pictures.next();
                check(jpeg != null && pictures.length() > 100 && (jpeg[0] & 0xff) == 0xff && (jpeg[1] & 0xff) == 0xd8,
                        "picture " + (i + 1) + " from the PC is a JPEG");
            }
            c.disconnect();
            try {
                Net.get(base + "/api/state", "wrong-token-wrong-token");
                check(false, "a wrong token is refused");
            } catch (Net.Error e) {
                check(e.code == 401, "a wrong token is refused");
            }
        }
        System.out.println("all good");
    }
}
