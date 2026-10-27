package app.samantha.phone;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;

/**
 * The live link to the PC (see samantha_mirror/streamrelay.py): one TCP connection that carries the screen to the
 * PC and touches back. Frames are 1 byte type, 4 bytes length, payload. Plain Java, so it is tested on the PC too.
 */
final class Link {
    interface Listener {
        void onFrame(char type, byte[] payload);

        void onClosed(String why);
    }

    static final int MAX_FRAME = 8_000_000;
    private final Socket socket;
    private final OutputStream out;
    private final DataInputStream in;
    private volatile boolean open = true;

    private Link(Socket socket) throws IOException {
        this.socket = socket;
        this.out = new BufferedOutputStream(socket.getOutputStream(), 256 * 1024);
        this.in = new DataInputStream(new BufferedInputStream(socket.getInputStream(), 64 * 1024));
    }

    /** The relay's address: the PC's host, on the port it told us (the web port + 1 by default). */
    static String host(String base) {
        return URI.create(base).getHost();
    }

    static int defaultPort(String base) {
        int port = URI.create(base).getPort();
        return (port > 0 ? port : (base.startsWith("https") ? 443 : 80)) + 1;
    }

    /** Connects, says who we are, and starts reading. Throws with a readable message if the PC says no. */
    static Link open(String host, int port, String token, String role, Listener listener) throws IOException {
        Socket s = new Socket();
        s.setTcpNoDelay(true);
        s.setSendBufferSize(1 << 20);
        s.connect(new InetSocketAddress(host, port), 6000);
        s.setSoTimeout(10000);
        Link link = new Link(s);
        String hello = "{\"token\":\"" + token.replace("\\", "\\\\").replace("\"", "\\\"") + "\",\"role\":\"" + role + "\"}\n";
        link.out.write(hello.getBytes("UTF-8"));
        link.out.flush();
        String answer = readLine(link.in);
        if (!answer.contains("\"ok\": true") && !answer.contains("\"ok\":true")) {
            s.close();
            int at = answer.indexOf("\"error\"");
            throw new IOException(at < 0 ? "The PC refused the link." : answer.substring(at).replaceAll("[\"{}]", "")
                    .replace("error:", "").trim());
        }
        s.setSoTimeout(0);
        Thread reader = new Thread(() -> link.readLoop(listener), "mirra-link-in");
        reader.setDaemon(true);
        reader.start();
        return link;
    }

    private static String readLine(InputStream in) throws IOException {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        int ch;
        while ((ch = in.read()) >= 0 && ch != '\n') {
            line.write(ch);
            if (line.size() > 4096) throw new IOException("bad answer from the PC");
        }
        if (ch < 0) throw new IOException("the PC closed the link");
        return line.toString("UTF-8");
    }

    private void readLoop(Listener listener) {
        String why = "closed";
        try {
            while (open) {
                char type = (char) in.readUnsignedByte();
                int size = in.readInt();
                if (size < 0 || size > MAX_FRAME) throw new IOException("frame too large");
                byte[] payload = new byte[size];
                in.readFully(payload);
                listener.onFrame(type, payload);
            }
        } catch (IOException e) {
            why = e.getMessage();
        } finally {
            close();
            listener.onClosed(why);
        }
    }

    boolean isOpen() {
        return open;
    }

    /** Sends one frame. `prefix` (may be null) goes before `data`, e.g. the flags byte of a video packet. */
    synchronized void send(char type, byte[] prefix, byte[] data, int offset, int length) throws IOException {
        int total = (prefix == null ? 0 : prefix.length) + length;
        out.write((byte) type);
        out.write((total >>> 24) & 0xff);
        out.write((total >>> 16) & 0xff);
        out.write((total >>> 8) & 0xff);
        out.write(total & 0xff);
        if (prefix != null) out.write(prefix);
        out.write(data, offset, length);
        out.flush();
    }

    void send(char type, byte[] data) throws IOException {
        send(type, null, data, 0, data.length);
    }

    void close() {
        open = false;
        try {
            socket.close();
        } catch (IOException ignored) {
            // already closed
        }
    }
}
