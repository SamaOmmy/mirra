package app.samantha.phone;

import android.Manifest;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * The app's home: pair with the PC (its address and a code from the Samantha window), open the PC's screen,
 * sound, and whether the PC may see and use this phone.
 */
public class MainActivity extends Activity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private Prefs prefs;
    private LinearLayout root;
    private volatile boolean visible;

    // pairing screen
    private EditText addressField, codeField;
    private TextView pairMessage;
    private Button connect;

    // paired screen
    private TextView pcName, pcStatus, phoneStatus, updateText;
    private LinearLayout accessOff, updateCard;
    private Switch soundSwitch, lowDataSwitch, controlSwitch, pauseSwitch;
    private volatile String online;       // null while unknown, "" when the PC answers, else the problem
    private volatile String pcVersion = "";
    private boolean updating;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = new Prefs(this);
        getWindow().setStatusBarColor(Ui.BG);
        getWindow().setNavigationBarColor(Ui.BG);
        build();
    }

    @Override
    protected void onResume() {
        super.onResume();
        visible = true;
        main.post(tick);
        new Thread(this::checkLoop, "samantha-check").start();
    }

    @Override
    protected void onPause() {
        visible = false;
        main.removeCallbacks(tick);
        super.onPause();
    }

    private void build() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(Ui.dp(this, 20), Ui.dp(this, 28), Ui.dp(this, 20), Ui.dp(this, 40));
        root.addView(Ui.text(this, "Samantha", 28, Ui.TEXT, true));
        root.addView(Ui.text(this, "Your PC on this phone, and this phone on your PC.", 14, Ui.MUTED, false));
        if (prefs.paired()) buildPaired();
        else buildPairing();
        TextView version = Ui.text(this, "Samantha for Android " + Updater.installedVersion(this), 12, Ui.MUTED, false);
        version.setPadding(0, Ui.dp(this, 24), 0, 0);
        root.addView(version);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Ui.BG);
        scroll.setFillViewport(true);
        scroll.addView(root);
        setContentView(scroll);
    }

    private EditText field(String hint, int type) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setSingleLine();
        e.setInputType(type);
        e.setTextColor(Ui.TEXT);
        e.setHintTextColor(0xff6b7280);
        e.setTextSize(17);
        e.setBackground(Ui.round(this, Ui.BG, 10, Ui.LINE));
        e.setPadding(Ui.dp(this, 14), Ui.dp(this, 12), Ui.dp(this, 14), Ui.dp(this, 12));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(this, 6);
        e.setLayoutParams(lp);
        return e;
    }

    private TextView caption(String s) {
        TextView t = Ui.text(this, s, 13, Ui.MUTED, true);
        t.setPadding(0, Ui.dp(this, 14), 0, 0);
        return t;
    }

    // -- not paired yet -----------------------------------------------------------------------------
    private void buildPairing() {
        LinearLayout card = Ui.card(this);
        card.addView(Ui.text(this, "Connect to your PC", 19, Ui.TEXT, true));
        card.addView(Ui.text(this, "On your PC, open Samantha. Its Home page shows the PC's address and a code. "
                + "Type them here.", 14, Ui.MUTED, false));
        card.addView(caption("PC address"));
        addressField = field("For example 100.101.102.103", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        String old = prefs.server();
        if (!old.isEmpty()) addressField.setText(Net.host(old));
        card.addView(addressField);
        card.addView(caption("Code"));
        codeField = field("6 digits", InputType.TYPE_CLASS_NUMBER);
        codeField.setImeOptions(EditorInfo.IME_ACTION_GO);
        codeField.setOnEditorActionListener((v, action, event) -> {
            pair();
            return true;
        });
        card.addView(codeField);
        card.addView(Ui.gap(this, 16));
        connect = Ui.button(this, "Connect", true, v -> pair());
        card.addView(connect);
        pairMessage = Ui.text(this, "", 14, Ui.WARN, false);
        pairMessage.setPadding(0, Ui.dp(this, 10), 0, 0);
        card.addView(pairMessage);
        root.addView(card);

        LinearLayout help = Ui.card(this);
        help.addView(Ui.text(this, "Before you start", 16, Ui.TEXT, true));
        help.addView(Ui.text(this, "Your phone reaches your PC through Tailscale, a free private network. Install the "
                + "Tailscale app on this phone, sign in with the same account as on the PC, and switch it on.", 14, Ui.MUTED, false));
        help.addView(Ui.gap(this, 10));
        help.addView(Ui.button(this, "Get Tailscale", false, v -> open("https://play.google.com/store/apps/details?id=com.tailscale.ipn")));
        root.addView(help);
    }

    private void pair() {
        String address = addressField.getText().toString().trim();
        String code = codeField.getText().toString().replaceAll("\\D", "");
        if (address.isEmpty() || code.length() != 6) {
            pairMessage.setText("Type the PC address and the 6-digit code from Samantha on your PC.");
            return;
        }
        connect.setEnabled(false);
        pairMessage.setTextColor(Ui.MUTED);
        pairMessage.setText("Connecting...");
        String base = Net.normalize(address);
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject().put("code", code).put("device", Build.MANUFACTURER + " " + Build.MODEL);
                JSONObject answer = new JSONObject(new String(Net.postJson(base + "/api/pair", null, body.toString()), "UTF-8"));
                prefs.pair(base, answer.getString("token"), answer.optString("pc", ""));
                PhoneService.settingsChanged();
                main.post(this::build);
            } catch (Exception e) {
                String why = Net.explain(e);
                main.post(() -> {
                    connect.setEnabled(true);
                    pairMessage.setTextColor(Ui.WARN);
                    pairMessage.setText(why);
                });
            }
        }).start();
    }

    // -- paired -------------------------------------------------------------------------------------
    private void buildPaired() {
        LinearLayout pc = Ui.card(this);
        LinearLayout head = Ui.row(this);
        pcName = Ui.text(this, prefs.pcLabel(), 20, Ui.TEXT, true);
        head.addView(pcName, Ui.weight(1));
        pc.addView(head);
        pcStatus = Ui.text(this, "Checking...", 14, Ui.MUTED, false);
        pc.addView(pcStatus);
        pc.addView(Ui.gap(this, 14));
        Button show = Ui.button(this, "Show my PC", true, v -> startActivity(new Intent(this, ViewerActivity.class)));
        show.setTextSize(17);
        show.setMinHeight(Ui.dp(this, 56));
        pc.addView(show);
        pc.addView(Ui.gap(this, 6));
        soundSwitch = Ui.toggle(this, "Play the PC's sound", prefs.sound(), (b, on) -> {
            prefs.setSound(on);
            lowDataSwitch.setVisibility(on ? View.VISIBLE : View.GONE);
        });
        pc.addView(soundSwitch);
        lowDataSwitch = Ui.toggle(this, "Use less data for sound (mono)", prefs.lowData(), (b, on) -> prefs.setLowData(on));
        lowDataSwitch.setVisibility(prefs.sound() ? View.VISIBLE : View.GONE);
        pc.addView(lowDataSwitch);
        root.addView(pc);

        LinearLayout phone = Ui.card(this);
        phone.addView(Ui.text(this, "Let this PC see and use my phone", 17, Ui.TEXT, true));
        phoneStatus = Ui.text(this, "", 14, Ui.MUTED, false);
        phoneStatus.setPadding(0, Ui.dp(this, 4), 0, 0);
        phone.addView(phoneStatus);
        accessOff = new LinearLayout(this);
        accessOff.setOrientation(LinearLayout.VERTICAL);
        accessOff.addView(Ui.gap(this, 12));
        accessOff.addView(Ui.button(this, "Turn it on", true, v -> {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
            startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
        }));
        accessOff.addView(Ui.text(this, "\nIn the list, choose Samantha and switch it on. You do this once; Android "
                + "never asks again.\n\nIf Android says the setting is restricted (it does that for apps installed "
                + "from outside the Play Store): first try the switch once so Android blocks it, then open App info "
                + "below, tap the three dots at the top right, choose \"Allow restricted settings\", and switch it on "
                + "again. The three dots only appear after Android has blocked the switch once.", 13, Ui.MUTED, false));
        accessOff.addView(Ui.gap(this, 10));
        accessOff.addView(Ui.button(this, "Open App info", false, v -> startActivity(
                new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName())))));
        phone.addView(accessOff);
        controlSwitch = Ui.toggle(this, "Allow tapping, swiping and typing", prefs.control(), (b, on) -> {
            prefs.setControl(on);
            PhoneService.settingsChanged();
        });
        phone.addView(controlSwitch);
        pauseSwitch = Ui.toggle(this, "Pause (the PC can't see or use this phone)", prefs.paused(), (b, on) -> {
            prefs.setPaused(on);
            PhoneService.settingsChanged();
        });
        phone.addView(pauseSwitch);
        phone.addView(Ui.text(this, "While your PC is looking, a notification says so. Banking apps and password "
                + "screens show black on the PC.", 12, Ui.MUTED, false));
        root.addView(phone);

        updateCard = Ui.card(this);
        updateCard.addView(Ui.text(this, "Update available", 17, Ui.TEXT, true));
        updateText = Ui.text(this, "", 14, Ui.MUTED, false);
        updateCard.addView(updateText);
        updateCard.addView(Ui.gap(this, 10));
        updateCard.addView(Ui.button(this, "Update", true, v -> update()));
        updateCard.setVisibility(View.GONE);
        root.addView(updateCard);

        LinearLayout about = Ui.card(this);
        about.addView(Ui.text(this, "This PC", 16, Ui.TEXT, true));
        about.addView(Ui.text(this, prefs.server(), 14, Ui.MUTED, false));
        about.addView(Ui.gap(this, 10));
        about.addView(Ui.button(this, "Forget this PC", false, v -> {
            prefs.unpair();
            PhoneService.settingsChanged();
            build();
        }));
        root.addView(about);
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            refresh();
            main.postDelayed(this, 1000);
        }
    };

    private boolean accessibilityOn() {
        if (PhoneService.instance != null) return true;
        String enabled = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        return enabled != null && enabled.contains(new ComponentName(this, PhoneService.class).flattenToString());
    }

    private void refresh() {
        if (!prefs.paired() || pcStatus == null) return;
        String o = online;
        pcName.setText(prefs.pcLabel());
        if (o == null) {
            pcStatus.setText("Checking...");
            pcStatus.setTextColor(Ui.MUTED);
        } else if (o.isEmpty()) {
            pcStatus.setText("Online");
            pcStatus.setTextColor(Ui.OK);
        } else {
            pcStatus.setText(o);
            pcStatus.setTextColor(Ui.WARN);
        }
        boolean on = accessibilityOn();
        accessOff.setVisibility(on ? View.GONE : View.VISIBLE);
        controlSwitch.setVisibility(on ? View.VISIBLE : View.GONE);
        pauseSwitch.setVisibility(on ? View.VISIBLE : View.GONE);
        if (!on) {
            phoneStatus.setText("Off. Your PC can't see this phone yet.");
        } else if (PhoneService.instance == null) {
            phoneStatus.setText("Starting...");
        } else {
            phoneStatus.setText(PhoneService.status);
        }
        if (Updater.newerOnPc(this, pcVersion) && !updating) {
            updateText.setText("Your PC has Samantha " + pcVersion + " (this phone has " + Updater.installedVersion(this)
                    + "). Update this app to match.");
            updateCard.setVisibility(View.VISIBLE);
        } else if (!updating) {
            updateCard.setVisibility(View.GONE);
        }
    }

    /** While this screen is open: is the PC there, and does it have a newer app? */
    private void checkLoop() {
        while (visible) {
            if (!prefs.paired()) {
                online = null;
                pcVersion = "";
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    return;
                }
                continue;
            }
            try {
                JSONObject state = new JSONObject(new String(Net.get(prefs.server() + "/api/state", prefs.token()), "UTF-8"));
                prefs.setPc(state.optString("pc", ""));
                JSONObject phone = new JSONObject(new String(Net.get(prefs.server() + "/api/phone/state", prefs.token()), "UTF-8"));
                pcVersion = phone.optBoolean("app_available") ? state.optString("version", "") : "";
                online = "";
            } catch (Exception e) {
                online = Net.explain(e);
            }
            try {
                Thread.sleep(4000);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    private void update() {
        if (updating || !Updater.mayInstall(this)) return;
        updating = true;
        updateText.setText("Downloading the update from your PC...");
        new Thread(() -> {
            try {
                Updater.install(this, prefs.server(), prefs.token());
                main.post(() -> updateText.setText("Confirm the update in the window Android shows."));
            } catch (Exception e) {
                main.post(() -> updateText.setText("The update did not download: " + Net.explain(e)));
            } finally {
                main.postDelayed(() -> updating = false, 5000);
            }
        }).start();
    }

    private void open(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
            // no browser or store on this phone
        }
    }
}
