package app.samantha.phone;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.pm.PackageInfo;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.hardware.HardwareBuffer;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.Bundle;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Talks to the PC and does what it asks. Runs for as long as the Accessibility permission is on.
 *
 * It connects out to the PC (it never listens for connections), asks "anything to do?" in a long request, and:
 *  - while a page on the PC is watching, takes screenshots and uploads them (Android gives the screenshot to
 *    accessibility services without a "start recording" question),
 *  - taps, swipes, presses Back/Home and types when the PC sends those and the control switch is on.
 */
public class PhoneService extends AccessibilityService {
    static volatile PhoneService instance;
    static volatile String status = "Not running";
    private static final String PAUSED = "Paused. The PC cannot see or use this phone.";

    private static final String CHANNEL = "watching";
    private static final int SHORT_SIDE = 720;        // screenshots are shrunk to this many pixels on the short side
    private static final int JPEG_QUALITY = 55;
    private static final long MIN_INTERVAL_MS = 340;  // Android allows one screenshot every 333 ms

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService shots = Executors.newSingleThreadExecutor();
    private final ExecutorService uploads = Executors.newSingleThreadExecutor();
    private final java.util.concurrent.atomic.AtomicBoolean uploading = new java.util.concurrent.atomic.AtomicBoolean();
    private volatile boolean running;
    private volatile boolean watching;
    private Thread linkThread;
    private Thread captureThread;
    private PowerManager.WakeLock wakeLock;
    private Prefs prefs;

    // -- lifecycle ---------------------------------------------------------------------------
    @Override
    protected void onServiceConnected() {
        instance = this;
        prefs = new Prefs(this);
        running = true;
        linkThread = new Thread(this::linkLoop, "samantha-link");
        linkThread.start();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) { }

    @Override
    public void onInterrupt() { }

    @Override
    public boolean onUnbind(android.content.Intent intent) {
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
        uploads.shutdownNow();
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

    // -- the link to the PC --------------------------------------------------------------------
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
                    byte[] data = Net.request("GET", base + "/api/phone/commands", token, null, null, null, 45000);
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
                .put("width", m.widthPixels)
                .put("height", m.heightPixels);
        } catch (Exception e) {
            throw new IOException(e);
        }
        byte[] answer = Net.request("POST", base + "/api/phone/hello", token, info.toString().getBytes(), "application/json", null, 8000);
        try {
            prefs.setPc(new JSONObject(new String(answer, "UTF-8")).optString("pc", ""));
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
        if (!prefs.control()) return;
        main.post(() -> {
            try {
                perform(type, c);
            } catch (Exception e) {
                report("Could not do that: " + e.getMessage());
            }
        });
    }

    // -- showing the screen --------------------------------------------------------------------
    private synchronized void setWatching(boolean on) {
        if (on == watching) return;
        watching = on;
        if (on) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "samantha:watching");
            wakeLock.acquire(30 * 60 * 1000L);
            showNotification(true);
            captureThread = new Thread(this::captureLoop, "samantha-capture");
            captureThread.start();
        } else {
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
            showNotification(false);
        }
    }

    private void captureLoop() {
        while (running && watching && !prefs.paused()) {
            long started = SystemClock.elapsedRealtime();
            Frame frame = grab();
            // Send it while the next one is taken (skip a picture rather than queue them if the network is slow).
            if (frame != null && uploading.compareAndSet(false, true)) {
                try {
                    uploads.execute(() -> {
                        try {
                            upload(frame);
                        } catch (IOException e) {
                            report("Could not send the screen to the PC: " + Net.explain(e));
                            pause(1000);
                        } finally {
                            uploading.set(false);
                        }
                    });
                } catch (java.util.concurrent.RejectedExecutionException e) {
                    return;   // shutting down
                }
            }
            if (wakeLock != null && !wakeLock.isHeld()) wakeLock.acquire(30 * 60 * 1000L);
            long spent = SystemClock.elapsedRealtime() - started;
            if (spent < MIN_INTERVAL_MS && !pause(MIN_INTERVAL_MS - spent)) return;
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
        } catch (InterruptedException e) {
            return null;
        } catch (RuntimeException e) {
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
            nm.cancel(1);
            return;
        }
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Screen sharing", NotificationManager.IMPORTANCE_LOW));
        Notification n = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle("Your PC is viewing this phone")
                .setContentText("Samantha is sharing this screen with " + prefs.pcLabel() + ".")
                .setOngoing(true)
                .build();
        nm.notify(1, n);
    }

    // -- using the phone -----------------------------------------------------------------------
    private DisplayMetrics realMetrics() {
        DisplayMetrics m = new DisplayMetrics();
        Display d = getSystemService(DisplayManager.class).getDisplay(Display.DEFAULT_DISPLAY);
        d.getRealMetrics(m);
        return m;
    }

    private void perform(String type, JSONObject c) throws JSONException {
        switch (type) {
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

    private void key(String name) {
        switch (name) {
            case "back": performGlobalAction(GLOBAL_ACTION_BACK); break;
            case "home": performGlobalAction(GLOBAL_ACTION_HOME); break;
            case "recents": performGlobalAction(GLOBAL_ACTION_RECENTS); break;
            case "notifications": performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS); break;
            case "quicksettings": performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS); break;
            case "wake": {
                PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
                @SuppressWarnings("deprecation")
                PowerManager.WakeLock w = pm.newWakeLock(
                        PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP, "samantha:wake");
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
