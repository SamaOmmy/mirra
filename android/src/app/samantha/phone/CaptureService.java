package app.samantha.phone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.Surface;

import org.json.JSONObject;

import java.io.IOException;
import java.nio.ByteBuffer;

/**
 * Records the screen with the phone's hardware video encoder (H.264, up to 60 fps) and streams it to the PC over the
 * live link, while the Mirra window on the PC shows this phone. Touches from the PC come back on the same link.
 */
public class CaptureService extends Service implements Link.Listener {
    static final String EXTRA_CODE = "code", EXTRA_DATA = "data";
    static volatile CaptureService instance;
    private static final String CHANNEL = "watching";

    private final Handler main = new Handler(Looper.getMainLooper());
    private Prefs prefs;
    private MediaProjection projection;
    private VirtualDisplay display;
    private volatile MediaCodec codec;
    private volatile boolean running, restart;
    private volatile Link link;
    private int width, height;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        prefs = new Prefs(this);
        showNotification();
        if (intent == null || running) return START_NOT_STICKY;
        int code = intent.getIntExtra(EXTRA_CODE, 0);
        @SuppressWarnings("deprecation")   // the typed version needs Android 13
        Intent data = intent.getParcelableExtra(EXTRA_DATA);
        try {
            projection = getSystemService(MediaProjectionManager.class).getMediaProjection(code, data);
        } catch (RuntimeException e) {
            projection = null;
        }
        if (projection == null) {
            PhoneService.captureFailed("Android did not start the screen recording.");
            stopSelf();
            return START_NOT_STICKY;
        }
        projection.registerCallback(new MediaProjection.Callback() {
            @Override
            public void onStop() {
                stopCapture();
            }
        }, main);
        instance = this;
        running = true;
        new Thread(this::run, "mirra-capture").start();
        return START_NOT_STICKY;
    }

    private void showNotification() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Screen sharing", NotificationManager.IMPORTANCE_LOW));
        Notification n = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle("Your PC is viewing this phone")
                .setContentText("Mirra is sharing this screen with " + new Prefs(this).pcLabel() + ".")
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        else startForeground(1, n);
    }

    static boolean active() {
        CaptureService s = instance;
        return s != null && s.running;
    }

    /** Stops recording (nobody is watching any more, or the user paused sharing). */
    static void stop() {
        CaptureService s = instance;
        if (s != null) s.stopCapture();
    }

    private void stopCapture() {
        running = false;
        Link l = link;
        if (l != null) l.close();
        main.post(() -> {
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
        });
    }

    @Override
    public void onDestroy() {
        running = false;
        if (instance == this) instance = null;
        releaseCodec();
        if (display != null) display.release();
        if (projection != null) projection.stop();
        Link l = link;
        if (l != null) l.close();
        super.onDestroy();
    }

    // -- the picture size --------------------------------------------------------------------------
    private DisplayMetrics metrics() {
        DisplayMetrics m = new DisplayMetrics();
        Display d = getSystemService(DisplayManager.class).getDisplay(Display.DEFAULT_DISPLAY);
        d.getRealMetrics(m);
        return m;
    }

    /** The screen scaled so the long side is at most `max`, in sizes the encoder accepts (multiples of 16). */
    private int[] videoSize(DisplayMetrics m, int max) {
        int w = m.widthPixels, h = m.heightPixels;
        MediaCodecInfo.VideoCapabilities caps = null;
        try {
            MediaCodec probe = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC);
            caps = probe.getCodecInfo().getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC).getVideoCapabilities();
            probe.release();
        } catch (IOException | RuntimeException ignored) {
            // use the plain size
        }
        int limit = max > 0 ? max : Math.max(w, h);
        for (int attempt = 0; attempt < 12; attempt++) {
            float scale = Math.min(1f, (float) limit / Math.max(w, h));
            int vw = Math.max(16, Math.round(w * scale / 16f) * 16);
            int vh = Math.max(16, Math.round(h * scale / 16f) * 16);
            if (caps == null || caps.isSizeSupported(vw, vh)) return new int[]{vw, vh};
            limit = Math.round(limit * 0.85f);
        }
        return new int[]{720, Math.round(720f * h / w / 16f) * 16};
    }

    // -- recording and sending -----------------------------------------------------------------------
    private void run() {
        String why = null;
        try {
            Prefs p = prefs;
            String base = p.server();
            link = Link.open(Link.host(base), p.relayPort(base), p.token(), "phone", this);
            while (running) {
                restart = false;
                DisplayMetrics m = metrics();
                int[] size = videoSize(m, p.maxSize());
                width = size[0];
                height = size[1];
                Surface surface = startCodec(width, height, p.bitrate(), p.fps());
                if (display == null) {
                    display = projection.createVirtualDisplay("mirra", width, height, m.densityDpi,
                            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, surface, null, null);
                } else {
                    display.resize(width, height, m.densityDpi);
                    display.setSurface(surface);
                }
                sendInfo(m);
                drain(m);
                if (display != null) display.setSurface(null);
                releaseCodec();
            }
        } catch (IOException | RuntimeException e) {
            why = e.getMessage();
        } finally {
            boolean wanted = running;
            stopCapture();
            if (wanted) PhoneService.captureFailed(why == null ? "The screen recording stopped." : why);
        }
    }

    private Surface startCodec(int w, int h, int bitrate, int fps) throws IOException {
        MediaFormat f = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, w, h);
        f.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
        f.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
        f.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
        f.setFloat(MediaFormat.KEY_MAX_FPS_TO_ENCODER, fps);
        f.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 10);
        f.setLong(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER, 100_000);   // a still screen still sends 10 pictures a second
        f.setInteger(MediaFormat.KEY_PRIORITY, 0);                          // real time
        f.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0);                      // no reordering: lowest delay
        f.setInteger(MediaFormat.KEY_LATENCY, 1);
        MediaCodec c = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC);
        try {
            c.configure(f, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        } catch (RuntimeException e) {   // some encoders refuse the extra keys: try the plain set
            f = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, w, h);
            f.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
            f.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
            f.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
            f.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 10);
            f.setLong(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER, 100_000);
            c.configure(f, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        }
        Surface surface = c.createInputSurface();
        c.start();
        codec = c;
        return surface;
    }

    private void releaseCodec() {
        MediaCodec c = codec;
        codec = null;
        if (c == null) return;
        try {
            c.stop();
        } catch (RuntimeException ignored) {
            // already stopped
        }
        c.release();
    }

    private void sendInfo(DisplayMetrics m) throws IOException {
        try {
            JSONObject info = new JSONObject()
                    .put("codec", "h264").put("width", width).put("height", height)
                    .put("screen_width", m.widthPixels).put("screen_height", m.heightPixels)
                    .put("device", Build.MANUFACTURER + " " + Build.MODEL)
                    .put("fps", prefs.fps()).put("bitrate", prefs.bitrate()).put("max_size", prefs.maxSize());
            link.send('H', info.toString().getBytes("UTF-8"));
        } catch (org.json.JSONException e) {
            throw new IOException(e);
        }
    }

    /** Sends encoded pictures until the size must change (rotation, quality) or recording stops. */
    private void drain(DisplayMetrics started) throws IOException {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        byte[] buf = new byte[256 * 1024];
        byte[] flags = new byte[1];
        long checkAt = 0;
        while (running && !restart) {
            MediaCodec c = codec;
            int index = c.dequeueOutputBuffer(info, 100_000);
            if (index >= 0) {
                ByteBuffer out = c.getOutputBuffer(index);
                if (out != null && info.size > 0) {
                    if (buf.length < info.size) buf = new byte[info.size + info.size / 2];
                    out.position(info.offset);
                    out.get(buf, 0, info.size);
                    flags[0] = (byte) (((info.flags & MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0 ? 1 : 0)
                            | ((info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0 ? 2 : 0));
                    link.send('V', flags, buf, 0, info.size);
                }
                c.releaseOutputBuffer(index, false);
            }
            long now = System.currentTimeMillis();
            if (now > checkAt) {   // turned the phone round?
                checkAt = now + 400;
                DisplayMetrics m = metrics();
                if (m.widthPixels != started.widthPixels || m.heightPixels != started.heightPixels) restart = true;
            }
        }
    }

    // -- from the PC --------------------------------------------------------------------------------
    @Override
    public void onFrame(char type, byte[] payload) {
        try {
            JSONObject msg = new JSONObject(new String(payload, "UTF-8"));
            if (type == 'I') {
                PhoneService.live(msg);
            } else if (type == 'C') {
                control(msg);
            }
        } catch (Exception ignored) {
            // a message we do not understand
        }
    }

    private void control(JSONObject msg) {
        String t = msg.optString("t");
        if (t.equals("keyframe")) {
            MediaCodec c = codec;
            if (c != null) {
                Bundle b = new Bundle();
                b.putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0);
                try {
                    c.setParameters(b);
                } catch (IllegalStateException ignored) {
                    // the codec is being replaced
                }
            }
        } else if (t.equals("quality")) {
            int size = msg.optInt("max_size", prefs.maxSize()), rate = msg.optInt("bitrate", prefs.bitrate());
            int fps = msg.optInt("fps", prefs.fps());
            // A new size or frame rate needs a new encoder; a new bit rate does not (and a still screen gives a
            // new encoder no picture until something on it changes, so avoid restarting when nothing changed).
            boolean reconfigure = size != prefs.maxSize() || fps != prefs.fps();
            prefs.setQuality(size, rate, fps);
            MediaCodec c = codec;
            if (reconfigure) {
                restart = true;
            } else if (c != null) {
                Bundle b = new Bundle();
                b.putInt(MediaCodec.PARAMETER_KEY_VIDEO_BITRATE, prefs.bitrate());
                try {
                    c.setParameters(b);
                } catch (IllegalStateException ignored) {
                    // the codec is being replaced
                }
            }
        }
    }

    @Override
    public void onClosed(String why) {
        if (running) stopCapture();
    }
}
