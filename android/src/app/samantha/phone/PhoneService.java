package app.samantha.phone;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.hardware.HardwareBuffer;
import android.hardware.display.DisplayManager;
import android.media.AudioManager;
import android.content.pm.ApplicationInfo;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Talks to the PC and does what it asks. Runs for as long as the Accessibility permission is on.
 *
 * It connects out to the PC (it never listens for connections) and asks "anything to do?" in a long request. When
 * the Mirra window on the PC shows this phone it is told to share the screen:
 *  - as smooth video (CaptureService, screen recording). Android asks "Start now?" for every recording; this service
 *    answers that question itself, so nobody has to tap it;
 *  - or, if recording is not possible, as screenshots (a few a second; Android gives those to accessibility services).
 * Touches, keys and typing from the PC arrive over the live link (or the web link) when the control switch is on.
 */
public class PhoneService extends AccessibilityService {
    static volatile PhoneService instance;
    static volatile String status = "Not running";
    private static final String PAUSED = "Paused. The PC cannot see or use this phone.";
    private static final String CHANNEL = "watching";
    private static final int SHORT_SIDE = 720;        // screenshots are shrunk to this many pixels on the short side
    private static final int JPEG_QUALITY = 60;
    private static final long MIN_INTERVAL_MS = 340;  // Android allows one screenshot every 333 ms
    private static volatile long consentUntil;        // answer the "Start now?" question until then
    private static final ExecutorService NOTIFY = Executors.newSingleThreadExecutor();
    private String lastNotification = "";
    private long lastNotificationAt;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService shots = Executors.newSingleThreadExecutor();
    private volatile boolean running;
    private volatile boolean watching;
    private volatile boolean screenshots;              // sharing by screenshots instead of video
    private Thread linkThread;
    private PowerManager.WakeLock wakeLock;
    private Prefs prefs;

    // -- lifecycle ---------------------------------------------------------------------------
    @Override
    protected void onServiceConnected() {
        instance = this;
        prefs = new Prefs(this);
        running = true;
        linkThread = new Thread(this::linkLoop, "mirra-web-link");
        linkThread.start();
    }

    @Override
    public void onInterrupt() { }

    @Override
    public boolean onUnbind(Intent intent) {
        shutdown();
        return super.onUnbind(intent);
    }

    @Override
    public void onDestroy() {
        shutdown();
        super.onDestroy();
    }

    private void shutdown() {
        running = false;
        setWatching(false);
        if (instance == this) {
            instance = null;
            status = "Not running";
        }
        if (linkThread != null) linkThread.interrupt();
        shots.shutdownNow();
    }

    /** The UI changed a switch: tell the PC and apply it now. */
    static void settingsChanged() {
        PhoneService s = instance;
        if (s == null) return;
        if (s.prefs.paused()) {
            s.setWatching(false);
            s.report(PAUSED);
            if (s.linkThread != null) s.linkThread.interrupt();   // end the waiting request now, not in 25 seconds
        }
        new Thread(() -> {
            try {
                s.hello(s.prefs.server(), s.prefs.token());
            } catch (IOException ignored) {
                // the link loop reports connection problems
            }
        }).start();
    }

    // -- "Start now?": Android asks before every screen recording ------------------------------------
    static void expectConsent() {
        consentUntil = SystemClock.elapsedRealtime() + 15000;
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event != null && event.getEventType() == AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED) {
            forwardNotification(event);
            return;
        }
        if (SystemClock.elapsedRealtime() > consentUntil || event == null) return;
        CharSequence pkg = event.getPackageName();
        if (pkg == null || !pkg.toString().equals("com.android.systemui")) return;
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;
        // Android 14+: choose "Entire screen" if it offers a choice (CaptureActivity asks for the whole screen anyway)
        for (AccessibilityNodeInfo n : root.findAccessibilityNodeInfosByText("Entire screen")) {
            if (n.isClickable()) n.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        }
        for (AccessibilityNodeInfo button : root.findAccessibilityNodeInfosByViewId("android:id/button1")) {
            if (button.isEnabled() && button.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                consentUntil = 0;
                return;
            }
        }
    }

    /**
     * A notification on this phone goes to the PC (switch "Notifications on the PC"): the app's name, the title and
     * the text. Not: Mirra's own, ongoing ones (music, downloads), group summaries, or ones marked secret.
     */
    private void forwardNotification(AccessibilityEvent event) {
        if (!prefs.notifications() || !prefs.paired() || prefs.paused()) return;
        if (!(event.getParcelableData() instanceof Notification)) return;   // a toast
        Notification n = (Notification) event.getParcelableData();
        String pkg = String.valueOf(event.getPackageName());
        if (pkg.equals(getPackageName()) || n.visibility == Notification.VISIBILITY_SECRET
                || (n.flags & (Notification.FLAG_ONGOING_EVENT | Notification.FLAG_GROUP_SUMMARY)) != 0) return;
        CharSequence title = n.extras.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence text = n.extras.getCharSequence(Notification.EXTRA_BIG_TEXT);
        if (text == null) text = n.extras.getCharSequence(Notification.EXTRA_TEXT);
        String t = title == null ? "" : title.toString(), x = text == null ? "" : text.toString();
        if (t.isEmpty() && x.isEmpty()) return;
        String key = pkg + "|" + t + "|" + x;
        long now = SystemClock.elapsedRealtime();
        if (key.equals(lastNotification) && now - lastNotificationAt < 10000) return;   // the same one, updated
        lastNotification = key;
        lastNotificationAt = now;
        String body;
        try {
            body = new JSONObject().put("app", appName(n, pkg)).put("title", t).put("text", x).toString();
        } catch (JSONException e) {
            return;
        }
        String url = prefs.server() + "/api/phone/notify", token = prefs.token();
        NOTIFY.execute(() -> {
            try {
                Net.postJson(url, token, body);
            } catch (IOException ignored) {
                // the PC is away: the notification is still on the phone
            }
        });
    }

    @SuppressWarnings("deprecation")   // the typed getParcelable needs Android 13
    private String appName(Notification n, String pkg) {
        try {
            Object info = n.extras.getParcelable("android.appInfo");   // set by Android on every notification
            if (info instanceof ApplicationInfo) return ((ApplicationInfo) info).loadLabel(getPackageManager()).toString();
        } catch (RuntimeException ignored) {
            // fall back to the package name
        }
        String last = pkg.substring(pkg.lastIndexOf('.') + 1);
        return last.isEmpty() ? pkg : Character.toUpperCase(last.charAt(0)) + last.substring(1);
    }

    /** "?battery=80&charging=1" for the command request: the PC shows the phone's battery. */
    private String batteryQuery() {
        BatteryManager bm = getSystemService(BatteryManager.class);
        int level = bm == null ? -1 : bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
        return level < 0 || level > 100 ? "" : "?battery=" + level + "&charging=" + (bm.isCharging() ? 1 : 0);
    }

    // -- the web link to the PC ----------------------------------------------------------------
    private void linkLoop() {
        long backoff = 2000;
        while (running) {
            if (!prefs.paired()) {
                report("Not paired with a PC yet.");
                if (!pause(1500)) return;
                continue;
            }
            if (prefs.paused()) {
                report(PAUSED);
                setWatching(false);
                if (!pause(1500)) return;
                continue;
            }
            final String base = prefs.server();
            final String token = prefs.token();
            try {
                hello(base, token);
                report("Connected to " + prefs.pcLabel() + ".");
                backoff = 2000;
                while (running && !prefs.paused() && base.equals(prefs.server()) && token.equals(prefs.token())) {
                    byte[] data = Net.request("GET", base + "/api/phone/commands" + batteryQuery(), token, null, null, null, 45000);
                    JSONArray commands = new JSONArray(new String(data));
                    for (int i = 0; i < commands.length(); i++) handle(commands.getJSONObject(i));
                }
            } catch (Net.Error e) {
                report(e.getMessage());
                if (e.code == 401) backoff = 15000;
            } catch (IOException | JSONException e) {
                report(Net.explain(e) + " Trying again...");
            }
            setWatching(false);
            if (!pause(backoff)) return;
            backoff = Math.min(backoff * 2, 15000);
        }
    }

    /**
     * Sets the line the app shows. Only the running service may: when Android restarts the service, the old one's
     * thread stops with an error that must not overwrite what the new one says.
     */
    private void report(String text) {
        if (!running || instance != this) return;
        status = prefs.paused() ? PAUSED : text;
    }

    private boolean pause(long ms) {
        try {
            Thread.sleep(ms);
            return running;
        } catch (InterruptedException e) {
            return false;
        }
    }

    private void hello(String base, String token) throws IOException {
        JSONObject info = new JSONObject();
        try {
            PackageInfo pkg = getPackageManager().getPackageInfo(getPackageName(), 0);
            DisplayMetrics m = realMetrics();
            info.put("device", Build.MANUFACTURER + " " + Build.MODEL)
                .put("version", pkg.versionName)
                .put("control", prefs.control())
                .put("video", true)
                .put("width", m.widthPixels)
                .put("height", m.heightPixels);
        } catch (Exception e) {
            throw new IOException(e);
        }
        byte[] answer = Net.request("POST", base + "/api/phone/hello", token, info.toString().getBytes(), "application/json", null, 8000);
        try {
            JSONObject a = new JSONObject(new String(answer, "UTF-8"));
            prefs.setPc(a.optString("pc", ""));
            prefs.setRelayPort(a.optInt("relay_port", 0));
        } catch (JSONException ignored) {
            // an older PC: it does not say its name
        }
    }

    private void handle(JSONObject c) {
        String type = c.optString("t");
        if (type.equals("watch")) {
            setWatching(c.optBoolean("on") && !prefs.paused());
            return;
        }
        if (type.equals("file")) {   // a file from the PC (it does not need the tap-and-type switch)
            Transfer.receive(this, prefs, c);
            return;
        }
        live(c);
    }

    // -- sharing the screen ----------------------------------------------------------------------
    private synchronized void setWatching(boolean on) {
        if (on == watching) return;
        watching = on;
        if (on) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "mirra:watching");
            wakeLock.acquire(60 * 60 * 1000L);
            if (prefs.video()) {
                report("Starting the screen sharing...");
                main.post(() -> startActivity(new Intent(this, CaptureActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION)));
                // if the recording has not started in time, share screenshots instead
                main.postDelayed(() -> {
                    if (watching && !CaptureService.active() && !screenshots) startScreenshots("Screen recording did not start.");
                }, 15000);
            } else {
                startScreenshots(null);
            }
        } else {
            screenshots = false;
            CaptureService.stop();
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
            showNotification(false);
            report("Connected to " + prefs.pcLabel() + ".");
        }
    }

    /** CaptureService could not record (refused, failed, or stopped by Android): fall back to screenshots. */
    static void captureFailed(String why) {
        PhoneService s = instance;
        if (s == null) return;
        s.main.post(() -> {
            if (s.watching && !s.screenshots) s.startScreenshots(why);
        });
    }

    private void startScreenshots(String why) {
        if (screenshots || !watching) return;
        screenshots = true;
        if (why != null) report(why + " Sharing screenshots instead.");
        showNotification(true);
        new Thread(this::screenshotLoop, "mirra-screenshots").start();
    }

    private void screenshotLoop() {
        Link link = null;
        try {
            String base = prefs.server();
            link = Link.open(Link.host(base), prefs.relayPort(base), prefs.token(), "phone", new Link.Listener() {
                @Override
                public void onFrame(char type, byte[] payload) {
                    if (type != 'I') return;
                    try {
                        live(new JSONObject(new String(payload, "UTF-8")));
                    } catch (Exception ignored) {
                        // not an input event we understand
                    }
                }

                @Override
                public void onClosed(String why) { }
            });
        } catch (IOException e) {
            link = null;   // an older PC without the live link: upload over the web link
        }
        boolean sentInfo = false;
        try {
            while (running && watching && screenshots && !prefs.paused()) {
                long started = SystemClock.elapsedRealtime();
                Frame frame = grab();
                if (frame != null) {
                    try {
                        if (link != null && link.isOpen()) {
                            if (!sentInfo) {
                                link.send('H', ("{\"codec\":\"jpeg\",\"width\":" + frame.width + ",\"height\":" + frame.height
                                        + ",\"device\":\"" + Build.MANUFACTURER + " " + Build.MODEL + "\"}").getBytes("UTF-8"));
                                sentInfo = true;
                            }
                            link.send('J', frame.jpeg);
                        } else {
                            upload(frame);
                        }
                    } catch (IOException e) {
                        report("Could not send the screen to the PC: " + Net.explain(e));
                        if (!pause(1000)) return;
                    }
                }
                long spent = SystemClock.elapsedRealtime() - started;
                if (spent < MIN_INTERVAL_MS && !pause(MIN_INTERVAL_MS - spent)) return;
            }
        } finally {
            if (link != null) link.close();
        }
    }

    private static final class Frame {
        final byte[] jpeg;
        final int width;
        final int height;

        Frame(byte[] jpeg, int width, int height) {
            this.jpeg = jpeg;
            this.width = width;
            this.height = height;
        }
    }

    /** One screenshot, shrunk and compressed. Null when Android would not give one (e.g. too soon, or a secure screen). */
    private Frame grab() {
        final Object[] box = new Object[2];
        final CountDownLatch done = new CountDownLatch(1);
        try {
            takeScreenshot(Display.DEFAULT_DISPLAY, shots, new TakeScreenshotCallback() {
                @Override
                public void onSuccess(ScreenshotResult result) {
                    try {
                        box[0] = encode(result);
                    } catch (Throwable t) {
                        box[1] = -1;
                    } finally {
                        done.countDown();
                    }
                }

                @Override
                public void onFailure(int errorCode) {
                    box[1] = errorCode;
                    done.countDown();
                }
            });
            if (!done.await(3, TimeUnit.SECONDS)) return null;
        } catch (InterruptedException | RuntimeException e) {
            return null;
        }
        if (box[1] != null) {
            if ((Integer) box[1] == ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT) pause(400);
            return null;
        }
        return (Frame) box[0];
    }

    private static Frame encode(ScreenshotResult result) {
        HardwareBuffer buffer = result.getHardwareBuffer();
        Bitmap hardware = Bitmap.wrapHardwareBuffer(buffer, result.getColorSpace());
        if (hardware == null) {
            buffer.close();
            throw new IllegalStateException("no picture");
        }
        Bitmap soft = hardware.copy(Bitmap.Config.ARGB_8888, false);
        hardware.recycle();
        buffer.close();
        float scale = Math.min(1f, (float) SHORT_SIDE / Math.min(soft.getWidth(), soft.getHeight()));
        int w = Math.max(1, Math.round(soft.getWidth() * scale));
        int h = Math.max(1, Math.round(soft.getHeight() * scale));
        Bitmap small = scale < 1f ? Bitmap.createScaledBitmap(soft, w, h, true) : soft;
        ByteArrayOutputStream out = new ByteArrayOutputStream(64 * 1024);
        small.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out);
        if (small != soft) small.recycle();
        soft.recycle();
        return new Frame(out.toByteArray(), w, h);
    }

    private void upload(Frame frame) throws IOException {
        Map<String, String> headers = new HashMap<>();
        headers.put("X-Width", String.valueOf(frame.width));
        headers.put("X-Height", String.valueOf(frame.height));
        Net.request("POST", prefs.server() + "/api/phone/frame", prefs.token(), frame.jpeg, "image/jpeg", headers, 8000);
    }

    private void showNotification(boolean on) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (!on) {
            if (!CaptureService.active()) nm.cancel(1);
            return;
        }
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Screen sharing", NotificationManager.IMPORTANCE_LOW));
        Notification n = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle("Your PC is viewing this phone")
                .setContentText("Mirra is sharing this screen with " + prefs.pcLabel() + ".")
                .setOngoing(true)
                .build();
        nm.notify(1, n);
    }

    // -- using the phone -----------------------------------------------------------------------
    /** An input event from the PC (live link or web link). Ignored when the control switch is off. */
    static void live(JSONObject c) {
        PhoneService s = instance;
        if (s == null || !s.prefs.control()) return;
        s.main.post(() -> {
            try {
                s.perform(c.optString("t"), c);
            } catch (Exception e) {
                s.report("Could not do that: " + e.getMessage());
            }
        });
    }

    private DisplayMetrics realMetrics() {
        DisplayMetrics m = new DisplayMetrics();
        Display d = getSystemService(DisplayManager.class).getDisplay(Display.DEFAULT_DISPLAY);
        d.getRealMetrics(m);
        return m;
    }

    private void perform(String type, JSONObject c) throws JSONException {
        switch (type) {
            case "touch":
                touch(c.getString("a"), (float) c.getDouble("x"), (float) c.getDouble("y"));
                break;
            case "scroll":
                scroll((float) c.getDouble("x"), (float) c.getDouble("y"), (float) c.getDouble("dy"));
                break;
            case "pinch":
                pinch((float) c.getDouble("x"), (float) c.getDouble("y"), c.optBoolean("in"));
                break;
            case "tap":
                swipe(new float[][]{{(float) c.getDouble("x"), (float) c.getDouble("y")}}, 50);
                break;
            case "long":
                swipe(new float[][]{{(float) c.getDouble("x"), (float) c.getDouble("y")}}, 800);
                break;
            case "gesture": {
                JSONArray pts = c.getJSONArray("pts");
                float[][] points = new float[pts.length()][2];
                for (int i = 0; i < pts.length(); i++) {
                    points[i][0] = (float) pts.getJSONArray(i).getDouble(0);
                    points[i][1] = (float) pts.getJSONArray(i).getDouble(1);
                }
                swipe(points, Math.max(1, c.getLong("ms")));
                break;
            }
            case "key":
                key(c.getString("k"));
                break;
            case "text":
                type(c.getString("s"));
                break;
            default:
                break;
        }
    }

    /** A position 0..1 as a pixel that is really on the screen (a gesture outside the screen is dropped by Android). */
    private static float pixel(float fraction, int size) {
        return Math.max(0f, Math.min(size - 1f, fraction * size));
    }

    /** A finger going through the given points (each 0..1 of the screen) in the given time. */
    private void swipe(float[][] points, long ms) {
        DisplayMetrics m = realMetrics();
        Path path = new Path();
        path.moveTo(pixel(points[0][0], m.widthPixels), pixel(points[0][1], m.heightPixels));
        for (int i = 1; i < points.length; i++) path.lineTo(pixel(points[i][0], m.widthPixels), pixel(points[i][1], m.heightPixels));
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, ms))
                .build();
        dispatchGesture(gesture, null, null);
    }

    /**
     * The PC's mouse wheel: drag by dy (a fraction of the screen; negative = up) and hold still before letting go, so
     * the page moves exactly that far instead of flinging on.
     */
    private void scroll(float fx, float fy, float dy) {
        DisplayMetrics m = realMetrics();
        float from = fy, to = fy + dy;
        if (to < 0.05f) { from += 0.05f - to; to = 0.05f; }
        if (to > 0.95f) { from -= to - 0.95f; to = 0.95f; }
        from = Math.max(0.02f, Math.min(0.98f, from));
        float x = pixel(fx, m.widthPixels), y0 = pixel(from, m.heightPixels), y1 = pixel(to, m.heightPixels);
        Path move = new Path();
        move.moveTo(x, y0);
        move.lineTo(x, y1);
        GestureDescription.StrokeDescription drag = new GestureDescription.StrokeDescription(move, 0, 140, true);
        stroke = null;   // a wheel scroll replaces a live finger
        dispatchGesture(new GestureDescription.Builder().addStroke(drag).build(), new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription g) {
                Path hold = new Path();
                hold.moveTo(x, y1);
                hold.lineTo(x, y1);
                try {
                    dispatchGesture(new GestureDescription.Builder().addStroke(drag.continueStroke(hold, 0, 80, false)).build(),
                            null, null);
                } catch (IllegalStateException | IllegalArgumentException ignored) {
                    // the phone ended the gesture itself
                }
            }
        }, main);
    }

    /** Ctrl + wheel on the PC: two fingers moving apart (zoom in) or together (zoom out) around (x, y). */
    private void pinch(float fx, float fy, boolean zoomIn) {
        DisplayMetrics m = realMetrics();
        float cx = pixel(fx, m.widthPixels), cy = pixel(fy, m.heightPixels);
        float near = m.widthPixels * 0.05f, far = m.widthPixels * 0.22f;
        float a = zoomIn ? near : far, b = zoomIn ? far : near;
        GestureDescription.Builder g = new GestureDescription.Builder();
        for (int side = -1; side <= 1; side += 2) {
            Path p = new Path();
            p.moveTo(clampX(cx + side * a, m), clampY(cy + side * a, m));
            p.lineTo(clampX(cx + side * b, m), clampY(cy + side * b, m));
            g.addStroke(new GestureDescription.StrokeDescription(p, 0, 220));
        }
        stroke = null;
        dispatchGesture(g.build(), null, null);
    }

    private static float clampX(float x, DisplayMetrics m) {
        return Math.max(0f, Math.min(m.widthPixels - 1f, x));
    }

    private static float clampY(float y, DisplayMetrics m) {
        return Math.max(0f, Math.min(m.heightPixels - 1f, y));
    }

    // A live finger: the PC sends down / move / up as the mouse moves, and the finger follows. Android plays a
    // stroke piece by piece (continueStroke); the next piece may only start when the previous one has been played.
    private GestureDescription.StrokeDescription stroke;
    private float lastX, lastY;
    private long lastAt;
    private boolean strokeBusy, upWanted;
    private final List<float[]> pending = new ArrayList<>();

    private void touch(String action, float fx, float fy) {
        DisplayMetrics m = realMetrics();
        float x = pixel(fx, m.widthPixels), y = pixel(fy, m.heightPixels);
        long now = SystemClock.uptimeMillis();
        if (action.equals("down")) {
            pending.clear();
            upWanted = false;
            Path p = new Path();
            p.moveTo(x, y);
            stroke = new GestureDescription.StrokeDescription(p, 0, 1, true);
            lastX = x;
            lastY = y;
            lastAt = now;
            play(stroke);
            return;
        }
        if (stroke == null) return;
        pending.add(new float[]{x, y, now});
        if (action.equals("up")) upWanted = true;
        flush();
    }

    private void flush() {
        if (strokeBusy || stroke == null || (pending.isEmpty() && !upWanted)) return;
        Path p = new Path();
        p.moveTo(lastX, lastY);
        long at = lastAt;
        for (float[] pt : pending) {
            p.lineTo(pt[0], pt[1]);
            lastX = pt[0];
            lastY = pt[1];
            at = (long) pt[2];
        }
        if (pending.isEmpty()) p.lineTo(lastX, lastY);
        long duration = Math.max(1, Math.min(500, at - lastAt));
        lastAt = Math.max(at, lastAt + duration);
        pending.clear();
        boolean more = !upWanted;
        try {
            stroke = stroke.continueStroke(p, 0, duration, more);
        } catch (IllegalStateException | IllegalArgumentException e) {
            stroke = null;
            return;
        }
        if (!more) upWanted = false;
        play(stroke);
        if (!more) stroke = null;
    }

    private void play(GestureDescription.StrokeDescription s) {
        strokeBusy = true;
        GestureDescription g = new GestureDescription.Builder().addStroke(s).build();
        boolean sent = dispatchGesture(g, new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription gestureDescription) {
                strokeBusy = false;
                flush();
            }

            @Override
            public void onCancelled(GestureDescription gestureDescription) {
                strokeBusy = false;
                stroke = null;
                pending.clear();
                upWanted = false;
            }
        }, main);
        if (!sent) {
            strokeBusy = false;
            stroke = null;
        }
    }

    private void key(String name) {
        switch (name) {
            case "back": performGlobalAction(GLOBAL_ACTION_BACK); break;
            case "home": performGlobalAction(GLOBAL_ACTION_HOME); break;
            case "recents": performGlobalAction(GLOBAL_ACTION_RECENTS); break;
            case "notifications": performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS); break;
            case "quicksettings": performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS); break;
            case "lock": performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN); break;
            case "power": performGlobalAction(GLOBAL_ACTION_POWER_DIALOG); break;
            case "screenshot": performGlobalAction(GLOBAL_ACTION_TAKE_SCREENSHOT); break;
            case "volup":
            case "voldown": {
                AudioManager audio = getSystemService(AudioManager.class);
                audio.adjustStreamVolume(AudioManager.STREAM_MUSIC,
                        name.equals("volup") ? AudioManager.ADJUST_RAISE : AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI);
                break;
            }
            case "wake": {
                PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
                @SuppressWarnings("deprecation")
                PowerManager.WakeLock w = pm.newWakeLock(
                        PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP, "mirra:wake");
                w.acquire(3000);
                break;
            }
            default: break;
        }
    }

    /** Types into the field that has the cursor. A backspace character deletes, a newline presses Enter. */
    private void type(String chars) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;
        AccessibilityNodeInfo field = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (field == null || !field.isEditable()) return;
        CharSequence now = field.isShowingHintText() ? null : field.getText();
        StringBuilder text = new StringBuilder(now == null ? "" : now.toString());
        for (int i = 0; i < chars.length(); i++) {
            char ch = chars.charAt(i);
            if (ch == '\b') {
                if (text.length() > 0) text.setLength(text.length() - 1);
            } else if (ch == '\n') {
                setText(field, text);
                field.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId());
            } else {
                text.append(ch);
            }
        }
        setText(field, text);
    }

    private static void setText(AccessibilityNodeInfo field, CharSequence text) {
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
    }
}
