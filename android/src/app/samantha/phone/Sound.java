package app.samantha.phone;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Plays the PC's sound (raw 16-bit PCM from /api/audio) while the PC's screen is shown. */
final class Sound {
    interface Listener {
        void soundStatus(String status);   // "" while playing fine, else why not
    }

    private static final double MAX_BEHIND_SECONDS = 0.5;   // more than this waiting in the network: skip ahead

    private final String base;
    private final String token;
    private final boolean lowData;
    private final Listener listener;
    private volatile boolean running;
    private volatile HttpURLConnection connection;
    private Thread thread;

    Sound(String base, String token, boolean lowData, Listener listener) {
        this.base = base;
        this.token = token;
        this.lowData = lowData;
        this.listener = listener;
    }

    void start() {
        running = true;
        thread = new Thread(this::run, "samantha-sound");
        thread.start();
    }

    void stop() {
        running = false;
        HttpURLConnection c = connection;
        if (c != null) c.disconnect();
        if (thread != null) thread.interrupt();
    }

    private void run() {
        long backoff = 1000;
        while (running) {
            AudioTrack track = null;
            try {
                HttpURLConnection c = Net.stream(base + "/api/audio" + (lowData ? "?q=low" : ""), token, 15000);
                connection = c;
                int rate = Integer.parseInt(c.getHeaderField("X-Audio-Rate"));
                int channels = Integer.parseInt(c.getHeaderField("X-Audio-Channels"));
                int frame = 2 * channels;
                int mask = channels == 1 ? AudioFormat.CHANNEL_OUT_MONO : AudioFormat.CHANNEL_OUT_STEREO;
                int min = AudioTrack.getMinBufferSize(rate, mask, AudioFormat.ENCODING_PCM_16BIT);
                track = new AudioTrack.Builder()
                        .setAudioAttributes(new AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                        .setAudioFormat(new AudioFormat.Builder().setSampleRate(rate).setChannelMask(mask)
                                .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                        .setBufferSizeInBytes(Math.max(min * 2, rate * frame / 5))
                        .setTransferMode(AudioTrack.MODE_STREAM)
                        .build();
                track.play();
                listener.soundStatus("");
                backoff = 1000;
                InputStream in = c.getInputStream();
                byte[] bytes = new byte[rate * frame / 25];   // 40 ms
                short[] samples = new short[bytes.length / 2];
                int carry = 0;
                long tooFar = (long) (rate * frame * MAX_BEHIND_SECONDS);
                while (running) {
                    int n = in.read(bytes, carry, bytes.length - carry);
                    if (n < 0) break;
                    n += carry;
                    if (in.available() > tooFar) {       // fell behind (the network stalled, then caught up)
                        long skip = in.available() - tooFar / 5;
                        skip -= skip % frame;
                        in.skip(skip);
                    }
                    int whole = n - n % frame;
                    ByteBuffer.wrap(bytes, 0, whole).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(samples, 0, whole / 2);
                    track.write(samples, 0, whole / 2);
                    carry = n - whole;
                    if (carry > 0) System.arraycopy(bytes, whole, bytes, 0, carry);
                }
            } catch (Exception e) {
                if (!running) break;
                if (e instanceof Net.Error && ((Net.Error) e).code == 409) {
                    listener.soundStatus("The PC can't play sound to phones right now.");
                } else {
                    listener.soundStatus("No sound: " + Net.explain(e));
                }
            } finally {
                if (track != null) {
                    try {
                        track.stop();
                    } catch (IllegalStateException ignored) {
                        // was never playing
                    }
                    track.release();
                }
                HttpURLConnection c = connection;
                if (c != null) c.disconnect();
                connection = null;
            }
            try {
                Thread.sleep(backoff);
            } catch (InterruptedException e) {
                return;
            }
            backoff = Math.min(backoff * 2, 10000);
        }
    }
}
