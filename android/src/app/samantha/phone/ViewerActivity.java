package app.samantha.phone;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentValues;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;

/** The PC's screen, live, full screen, with its sound if switched on. The PC is view-only from here. */
public class ViewerActivity extends Activity implements ScreenView.Listener, Sound.Listener {
    private static final String[][] PRESETS = {
            // name, hint, fps, quality, scale
            {"Data saver", "Mobile data", "15", "50", "0.5"},
            {"Balanced", "Default", "30", "70", "0.75"},
            {"Sharp", "Wi-Fi", "30", "85", "1"},
            {"Smooth", "60 fps, Wi-Fi", "60", "65", "0.75"},
    };

    private final Handler main = new Handler(Looper.getMainLooper());
    private Prefs prefs;
    private String base, token;
    private ScreenView screen;
    private LinearLayout top, bottom;
    private TextView status, message;
    private Button soundButton;
    private volatile boolean running;
    private volatile HttpURLConnection pictureConnection;
    private Sound sound;
    private volatile String problem;         // why there is no picture, or null
    private volatile String soundProblem = "";
    private volatile JSONObject state;       // the PC's /api/state, refreshed every 2 seconds
    private final long[] frameTimes = new long[30];
    private int frameIndex;
    private final Runnable hideBars = () -> setBars(false);

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = new Prefs(this);
        if (!prefs.paired()) {
            finish();
            return;
        }
        base = prefs.server();
        token = prefs.token();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().getAttributes().layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        applyOrientation();
        buildUi();
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xff000000);
        screen = new ScreenView(this);
        screen.setListener(this);
        root.addView(screen, new FrameLayout.LayoutParams(-1, -1));

        message = Ui.text(this, "Connecting...", 16, Ui.TEXT, false);
        message.setGravity(Gravity.CENTER);
        message.setPadding(Ui.dp(this, 32), 0, Ui.dp(this, 32), 0);
        root.addView(message, new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER));

        top = Ui.row(this);
        top.setBackgroundColor(0xcc0b0d12);
        top.setPadding(Ui.dp(this, 16), Ui.dp(this, 10), Ui.dp(this, 16), Ui.dp(this, 10));
        status = Ui.text(this, "", 14, Ui.TEXT, false);
        top.addView(status, Ui.weight(1));
        root.addView(top, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));

        bottom = Ui.row(this);
        bottom.setBackgroundColor(0xcc0b0d12);
        bottom.setPadding(Ui.dp(this, 8), Ui.dp(this, 8), Ui.dp(this, 8), Ui.dp(this, 8));
        soundButton = barButton("", v -> toggleSound());
        bottom.addView(soundButton, Ui.weight(1));
        bottom.addView(barButton("Rotate", v -> rotate()), Ui.weight(1));
        bottom.addView(barButton("More", v -> showMore()), Ui.weight(1));
        bottom.addView(barButton("Close", v -> finish()), Ui.weight(1));
        root.addView(bottom, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        updateSoundButton();

        root.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            top.setPadding(Ui.dp(this, 16) + bars.left, Ui.dp(this, 10) + bars.top, Ui.dp(this, 16) + bars.right, Ui.dp(this, 10));
            bottom.setPadding(Ui.dp(this, 8) + bars.left, Ui.dp(this, 8), Ui.dp(this, 8) + bars.right, Ui.dp(this, 8) + bars.bottom);
            return insets;
        });
        setContentView(root);
    }

    private Button barButton(String text, View.OnClickListener l) {
        Button b = Ui.button(this, text, false, v -> {
            l.onClick(v);
            scheduleHide();
        });
        b.setBackground(null);
        b.setTextSize(14);
        b.setSingleLine(true);
        b.setPadding(Ui.dp(this, 4), b.getPaddingTop(), Ui.dp(this, 4), b.getPaddingBottom());
        return b;
    }

    /** A PC screen is wide: show it sideways unless the user turns the phone upright with Rotate. */
    private void rotate() {
        boolean upright = !prefs.upright();
        prefs.setUpright(upright);
        applyOrientation();
    }

    private void applyOrientation() {
        setRequestedOrientation(prefs.upright() ? android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT
                : android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (base == null) return;
        running = true;
        hideSystemBars();
        new Thread(this::pictureLoop, "samantha-picture").start();
        new Thread(this::stateLoop, "samantha-state").start();
        if (prefs.sound()) startSound();
        setBars(true);
        scheduleHide();
        main.post(tick);
    }

    @Override
    protected void onStop() {
        running = false;
        main.removeCallbacks(tick);
        HttpURLConnection c = pictureConnection;
        if (c != null) c.disconnect();
        stopSound();
        super.onStop();
    }

    @Override
    public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) hideSystemBars();
    }

    private void hideSystemBars() {
        WindowInsetsController c = getWindow().getInsetsController();
        if (c == null) return;
        c.hide(WindowInsets.Type.systemBars());
        c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
    }

    // -- the picture -----------------------------------------------------------------------------
    private void pictureLoop() {
        long backoff = 1000;
        while (running) {
            try {
                HttpURLConnection c = Net.stream(base + "/stream", token, 20000);
                pictureConnection = c;
                Mjpeg pictures = new Mjpeg(c.getInputStream());
                backoff = 1000;
                while (running) {
                    byte[] data = pictures.next();
                    if (data == null) break;
                    Bitmap bitmap = decode(data, pictures.length());
                    if (bitmap == null) continue;
                    problem = null;
                    screen.show(bitmap);
                    synchronized (frameTimes) {
                        frameTimes[frameIndex++ % frameTimes.length] = SystemClock.elapsedRealtime();
                    }
                }
            } catch (Exception e) {
                if (!running) return;
                problem = Net.explain(e);
                if (e instanceof Net.Error && ((Net.Error) e).code == 401) backoff = 15000;
            } finally {
                HttpURLConnection c = pictureConnection;
                if (c != null) c.disconnect();
                pictureConnection = null;
            }
            if (!sleep(backoff)) return;
            backoff = Math.min(backoff * 2, 8000);
        }
    }

    private Bitmap decode(byte[] data, int length) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inMutable = true;
        o.inBitmap = screen.spare();
        try {
            return BitmapFactory.decodeByteArray(data, 0, length, o);
        } catch (IllegalArgumentException e) {   // the spare has the wrong size: the PC's picture size changed
            o.inBitmap = null;
            return BitmapFactory.decodeByteArray(data, 0, length, o);
        }
    }

    private int fps() {
        long now = SystemClock.elapsedRealtime();
        int n = 0;
        long oldest = now;
        synchronized (frameTimes) {
            for (long t : frameTimes) {
                if (t > 0 && now - t < 2000) {
                    n++;
                    oldest = Math.min(oldest, t);
                }
            }
        }
        if (n < 2 || now == oldest) return n;
        return Math.round((n - 1) * 1000f / (now - oldest));
    }

    private boolean sleep(long ms) {
        try {
            Thread.sleep(ms);
            return running;
        } catch (InterruptedException e) {
            return false;
        }
    }

    // -- the PC's state (capture problems, size) ---------------------------------------------------
    private void stateLoop() {
        while (running) {
            try {
                state = new JSONObject(new String(Net.get(base + "/api/state", token), "UTF-8"));
                JSONObject s = state;
                prefs.setPc(s.optString("pc", ""));
            } catch (Exception e) {
                state = null;
            }
            if (!sleep(2000)) return;
        }
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            refresh();
            main.postDelayed(this, 500);
        }
    };

    private void refresh() {
        JSONObject s = state;
        String captureError = s == null ? "" : s.optString("error", "");
        if (captureError.equals("null")) captureError = "";
        String text;
        if (problem != null) {
            text = problem + "\n\nTrying again...";
        } else if (screen.pictureSize() == null) {
            text = "Connecting to " + prefs.pcLabel() + "...";
        } else if (!captureError.isEmpty()) {
            text = "The PC's screen can't be captured right now (" + captureError + "). It may be locked.";
        } else {
            text = "";
        }
        message.setText(text);
        message.setVisibility(text.isEmpty() ? View.GONE : View.VISIBLE);
        message.setBackgroundColor(screen.pictureSize() == null ? 0 : 0xcc000000);

        StringBuilder line = new StringBuilder();
        line.append(prefs.pcLabel());
        if (problem == null && screen.pictureSize() != null) {
            line.append("  ·  ").append(fps()).append(" fps");
            int[] size = screen.pictureSize();
            line.append("  ·  ").append(size[0]).append("×").append(size[1]);
        }
        if (prefs.sound()) line.append(soundProblem.isEmpty() ? "  ·  sound on" : "  ·  " + soundProblem);
        status.setText(line);
    }

    // -- bars ---------------------------------------------------------------------------------------
    @Override
    public void onSingleTap() {
        setBars(top.getVisibility() != View.VISIBLE);
        if (top.getVisibility() == View.VISIBLE) scheduleHide();
    }

    private void setBars(boolean visible) {
        main.removeCallbacks(hideBars);
        top.setVisibility(visible ? View.VISIBLE : View.GONE);
        bottom.setVisibility(visible ? View.VISIBLE : View.GONE);
    }

    private void scheduleHide() {
        main.removeCallbacks(hideBars);
        main.postDelayed(hideBars, 5000);
    }

    // -- sound --------------------------------------------------------------------------------------
    private void startSound() {
        stopSound();
        soundProblem = "";
        sound = new Sound(base, token, prefs.lowData(), this);
        sound.start();
    }

    private void stopSound() {
        if (sound != null) sound.stop();
        sound = null;
    }

    @Override
    public void soundStatus(String text) {
        soundProblem = text;
    }

    private void toggleSound() {
        prefs.setSound(!prefs.sound());
        if (prefs.sound()) startSound();
        else stopSound();
        updateSoundButton();
        refresh();
    }

    private void updateSoundButton() {
        soundButton.setText(prefs.sound() ? "Sound on" : "Sound off");
    }

    // -- quality and screen picker ------------------------------------------------------------------
    private void showMore() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(this, 20), Ui.dp(this, 8), Ui.dp(this, 20), Ui.dp(this, 8));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(box);
        AlertDialog dialog = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("Picture").setView(scroll).setPositiveButton("Done", null).create();
        Button shot = Ui.button(this, "Save a screenshot of the PC", false, v -> {
            screenshot();
            dialog.dismiss();
        });
        box.addView(shot, new LinearLayout.LayoutParams(-1, -2));
        box.addView(Ui.gap(this, 14));

        JSONObject s = state;
        JSONObject current = s == null ? null : s.optJSONObject("settings");
        box.addView(Ui.text(this, "Quality", 13, Ui.MUTED, true));
        for (String[] p : PRESETS) {
            boolean on = current != null && current.optInt("fps") == Integer.parseInt(p[2])
                    && current.optInt("quality") == Integer.parseInt(p[3])
                    && Math.abs(current.optDouble("scale") - Double.parseDouble(p[4])) < 0.01;
            Button b = Ui.button(this, p[0] + "  ·  " + p[1], on, v -> {
                send("{\"fps\":" + p[2] + ",\"quality\":" + p[3] + ",\"scale\":" + p[4] + "}");
                dialog.dismiss();
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = Ui.dp(this, 8);
            box.addView(b, lp);
        }
        TextView screens = Ui.text(this, "Screen", 13, Ui.MUTED, true);
        screens.setPadding(0, Ui.dp(this, 18), 0, 0);
        box.addView(screens);
        LinearLayout monitorList = new LinearLayout(this);
        monitorList.setOrientation(LinearLayout.VERTICAL);
        box.addView(monitorList);
        Switch pointer = Ui.toggle(this, "Show the mouse pointer", current == null || current.optBoolean("cursor", true),
                (b, on) -> send("{\"cursor\":" + on + "}"));
        box.addView(pointer);
        box.addView(Ui.text(this, "These apply to everyone watching this PC.", 12, Ui.MUTED, false));
        dialog.show();

        int selected = current == null ? 1 : current.optInt("monitor", 1);
        new Thread(() -> {
            try {
                JSONArray monitors = new JSONObject(new String(Net.get(base + "/api/monitors", token), "UTF-8")).getJSONArray("monitors");
                main.post(() -> {
                    for (int i = 0; i < monitors.length(); i++) {
                        JSONObject m = monitors.optJSONObject(i);
                        int index = m.optInt("index");
                        Button b = Ui.button(this, m.optString("label") + "  ·  " + m.optInt("width") + "×" + m.optInt("height"),
                                index == selected, v -> {
                                    send("{\"monitor\":" + index + "}");
                                    dialog.dismiss();
                                });
                        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
                        lp.topMargin = Ui.dp(this, 8);
                        monitorList.addView(b, lp);
                    }
                });
            } catch (Exception e) {
                main.post(() -> monitorList.addView(Ui.text(this, Net.explain(e), 13, Ui.WARN, false)));
            }
        }).start();
    }

    private void send(String json) {
        new Thread(() -> {
            try {
                Net.postJson(base + "/api/settings", token, json);
            } catch (Exception e) {
                main.post(() -> Toast.makeText(this, Net.explain(e), Toast.LENGTH_LONG).show());
            }
        }).start();
    }

    // -- screenshot ---------------------------------------------------------------------------------
    private void screenshot() {
        Toast.makeText(this, "Taking a screenshot of the PC...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                byte[] png = Net.request("GET", base + "/api/screenshot", token, null, null, null, 30000);
                ContentValues v = new ContentValues();
                v.put(MediaStore.Images.Media.DISPLAY_NAME, "PC screenshot " + System.currentTimeMillis() + ".png");
                v.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
                v.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/Samantha");
                Uri uri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
                if (uri == null) throw new java.io.IOException("no room for it");
                try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                    out.write(png);
                }
                main.post(() -> Toast.makeText(this, "Saved in Pictures/Samantha.", Toast.LENGTH_LONG).show());
            } catch (Exception e) {
                main.post(() -> Toast.makeText(this, "No screenshot: " + Net.explain(e), Toast.LENGTH_LONG).show());
            }
        }).start();
    }
}
