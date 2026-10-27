package app.samantha.phone;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;

/** Reads the PC's picture stream (multipart JPEG): each call to next() returns one picture. */
final class Mjpeg {
    private static final int MAX_FRAME = 20_000_000;
    private final InputStream in;
    private byte[] buffer = new byte[256 * 1024];
    private int length;

    Mjpeg(InputStream in) {
        this.in = new BufferedInputStream(in, 64 * 1024);
    }

    /** The bytes of the next picture (valid until the next call; see length()), or null at the end of the stream. */
    byte[] next() throws IOException {
        int size = -1;
        while (true) {
            String line = readLine();
            if (line == null) return null;
            if (line.regionMatches(true, 0, "content-length:", 0, 15)) {
                try {
                    size = Integer.parseInt(line.substring(15).trim());
                } catch (NumberFormatException e) {
                    throw new IOException("bad picture header");
                }
            } else if (line.isEmpty() && size >= 0) {
                break;
            }
        }
        if (size > MAX_FRAME) throw new IOException("picture too large");
        if (buffer.length < size) buffer = new byte[size + size / 4];
        int read = 0;
        while (read < size) {
            int n = in.read(buffer, read, size - read);
            if (n < 0) return null;
            read += n;
        }
        length = size;
        return buffer;
    }

    int length() {
        return length;
    }

    private String readLine() throws IOException {
        StringBuilder s = new StringBuilder();
        while (true) {
            int ch = in.read();
            if (ch < 0) return s.length() == 0 ? null : s.toString();
            if (ch == '\n') break;
            if (ch != '\r') s.append((char) ch);
            if (s.length() > 1000) throw new IOException("bad picture stream");
        }
        return s.toString();
    }
}
