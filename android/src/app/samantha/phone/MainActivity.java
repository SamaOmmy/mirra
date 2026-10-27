package app.samantha.phone;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * Mirra's home: connect to the PC (scan the QR code on the PC, or type its name and a code), show the PC, sound,
 * and whether the PC may see and use this phone.
 */
public class MainActivity extends Activity {
    static final String SETUP_URL =
            "https://github.com/SamaOmmy/samantha-screen-mirror/releases/latest/download/Mirra-for-Android-Setup.apk";
    private final Handler main = new Handler(Looper.getMainLooper());
    private Prefs prefs;
    private LinearLayout root;
    private volatile boolean visible;

    // not paired yet
    private EditText addressField, codeField;
    private TextView pairMessage;
    private Button connect;

    // paired
    private TextView pcName, phoneStatus;
    private LinearLayout pcChipHolder, accessOff, accessOn, restrictedBox;
    private Switch lowDataSwitch;
    private View lowDataRow;
    private volatile String online;       // null while unknown, "" when the PC answers, else the problem
    private volatile String pcVersion = "";
    private String offered = "";          // the update version already offered in a pop-up
    private boolean updating;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = new Prefs(this);
        getWindow().setStatusBarColor(Ui.BG);
        getWindow().setNavigationBarColor(Ui.BG);
        build();
        handleLink(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleLink(intent);
    }

    @Override
    protected void onResume() {
        super.onResume();
        visible = true;
        main.post(tick);
        new Thread(this::checkLoop, "mirra-check").start();
    }

    @Override
    protected void onPause() {
        visible = false;
        main.removeCallbacks(tick);
        super.onPause();
    }

    /** mirra://pair?host=...&port=...&code=... from the page the PC's QR code opens: pair without typing. */
    private void handleLink(Intent intent) {
        Uri uri = intent == null ? null : intent.getData();
        if (uri == null || !"mirra".equals(uri.getScheme())) return;
        String host = uri.getQueryParameter("host"), port = uri.getQueryParameter("port"), code = uri.getQueryParameter("code");
        if (host == null || code == null) return;
        if (prefs.paired()) {
            prefs.unpair();   // pairing again, possibly with another PC
            build();
        }
        String address = host + (port == null || port.isEmpty() ? "" : ":" + port);
        if (addressField != null) {
            addressField.setText(address);
            codeField.setText(code);
        }
        pair(address, code);
    }

    private void build() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(Ui.dp(this, 20), Ui.dp(this, 24), Ui.dp(this, 20), Ui.dp(this, 40));
        LinearLayout head = Ui.row(this);
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.logo);
        head.addView(logo, new LinearLayout.LayoutParams(Ui.dp(this, 44), Ui.dp(this, 44)));
        LinearLayout titles = new LinearLayout(this);
        titles.setOrientation(LinearLayout.VERTICAL);
        titles.setPadding(Ui.dp(this, 14), 0, 0, 0);
        titles.addView(Ui.text(this, "Mirra", 26, Ui.TEXT, true));
        titles.addView(Ui.text(this, "Your PC on your phone. Your phone on your PC.", 13, Ui.MUTED, false));
        head.addView(titles, Ui.weight(1));
        root.addView(head);
        if (prefs.paired()) buildPaired();
        else buildPairing();
        TextView version = Ui.text(this, "Mirra for Android " + Updater.installedVersion(this), 12, Ui.MUTED, false);
        version.setGravity(Gravity.CENTER_HORIZONTAL);
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
        e.setHintTextColor(0xff5d6475);
        e.setTextSize(17);
        e.setBackground(Ui.round(this, Ui.BG, 14, Ui.LINE));
        e.setPadding(Ui.dp(this, 16), Ui.dp(this, 14), Ui.dp(this, 16), Ui.dp(this, 14));
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
        LinearLayout hero = Ui.hero(this);
        hero.addView(Ui.text(this, "Connect to your PC", 22, 0xffffffff, true));
        hero.addView(Ui.text(this, "On your PC, open Mirra. Point this phone's camera at the QR code on its Home page "
                + "and tap the link: Mirra connects by itself.", 15, 0xe6ffffff, false));
        root.addView(hero);

        LinearLayout card = Ui.card(this);
        card.addView(Ui.title(this, "Or type it in"));
        card.addView(Ui.text(this, "Mirra on the PC shows its name and a 6-digit code.", 14, Ui.MUTED, false));
        card.addView(caption("PC name or address"));
        addressField = field("For example  my-pc  or  100.101.102.103", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        String old = prefs.server();
        if (!old.isEmpty()) addressField.setText(Net.host(old));
        card.addView(addressField);
        card.addView(caption("Code"));
        codeField = field("6 digits", InputType.TYPE_CLASS_NUMBER);
        codeField.setImeOptions(EditorInfo.IME_ACTION_GO);
        codeField.setOnEditorActionListener((v, action, event) -> {
            pairFromFields();
            return true;
        });
        card.addView(codeField);
        connect = Ui.button(this, "Connect", true, v -> pairFromFields());
        card.addView(connect);
        pairMessage = Ui.text(this, "", 14, Ui.WARN, false);
        pairMessage.setPadding(0, Ui.dp(this, 10), 0, 0);
        card.addView(pairMessage);
        root.addView(card);

        LinearLayout help = Ui.card(this);
        help.addView(Ui.settingRow(this, R.drawable.ic_monitor, "Tailscale on this phone",
                "Mirra reaches your PC through Tailscale, a free private network. Install it, sign in with the same "
                        + "account as on the PC, and switch it on.", null));
        help.addView(Ui.button(this, "Get Tailscale", false,
                v -> open("https://play.google.com/store/apps/details?id=com.tailscale.ipn")));
        root.addView(help);
    }

    private void pairFromFields() {
        pair(addressField.getText().toString().trim(), codeField.getText().toString().replaceAll("\\D", ""));
    }

    private void pair(String address, String code) {
        if (address.isEmpty() || code.length() != 6) {
            if (pairMessage != null) pairMessage.setText("Type the PC's name (or address) and the 6-digit code from Mirra on the PC.");
            return;
        }
        if (connect != null) connect.setEnabled(false);
        if (pairMessage != null) {
            pairMessage.setTextColor(Ui.MUTED);
            pairMessage.setText("Connecting...");
        }
        String base = Net.normalize(address);
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject().put("code", code).put("device", Build.MANUFACTURER + " " + Build.MODEL);
                JSONObject answer = new JSONObject(new String(Net.postJson(base + "/api/pair", null, body.toString()), "UTF-8"));
                prefs.pair(base, answer.getString("token"), answer.optString("pc", ""));
                PhoneService.settingsChanged();
                main.post(() -> {
                    Toast.makeText(this, "Connected to " + prefs.pcLabel() + ".", Toast.LENGTH_LONG).show();
                    build();
                });
            } catch (Exception e) {
                String why = Net.explain(e);
                main.post(() -> {
                    if (connect != null) connect.setEnabled(true);
                    if (pairMessage != null) {
                        pairMessage.setTextColor(Ui.WARN);
                        pairMessage.setText(why);
                    } else {
                        Toast.makeText(this, why, Toast.LENGTH_LONG).show();
                    }
                });
            }
        }).start();
    }

    // -- paired -------------------------------------------------------------------------------------
    private void buildPaired() {
        LinearLayout hero = Ui.hero(this);
        LinearLayout top = Ui.row(this);
        top.addView(Ui.icon(this, R.drawable.ic_monitor, 0xffffffff, 26));
        pcName = Ui.text(this, prefs.pcLabel(), 22, 0xffffffff, true);
        pcName.setPadding(Ui.dp(this, 12), 0, 0, 0);
        top.addView(pcName, Ui.weight(1));
        hero.addView(top);
        pcChipHolder = new LinearLayout(this);
        pcChipHolder.setPadding(0, Ui.dp(this, 10), 0, 0);
        hero.addView(pcChipHolder);
        Button show = Ui.button(this, "Show my PC", false, v -> startActivity(new Intent(this, ViewerActivity.class)));
        show.setBackground(Ui.ripple(Ui.round(this, 0xffffffff, 16, 0), Ui.round(this, 0xffffffff, 16, 0)));
        show.setTextColor(0xff1d1650);
        show.setTextSize(17);
        show.setMinHeight(Ui.dp(this, 58));
        hero.addView(show);
        root.addView(hero);

        LinearLayout sound = Ui.card(this);
        sound.addView(Ui.settingRow(this, R.drawable.ic_sound, "Play the PC's sound", "Hear the PC while you watch it.",
                Ui.toggle(this, prefs.sound(), (b, on) -> {
                    prefs.setSound(on);
                    lowDataRow.setVisibility(on ? View.VISIBLE : View.GONE);
                })));
        lowDataSwitch = Ui.toggle(this, prefs.lowData(), (b, on) -> prefs.setLowData(on));
        lowDataRow = Ui.settingRow(this, R.drawable.ic_sound, "Use less data", "Mono sound: a quarter of the data.", lowDataSwitch);
        lowDataRow.setVisibility(prefs.sound() ? View.VISIBLE : View.GONE);
        sound.addView(lowDataRow);
        root.addView(sound);

        LinearLayout phone = Ui.card(this);
        LinearLayout ph = Ui.row(this);
        ph.addView(Ui.icon(this, R.drawable.ic_phone, Ui.ACCENT2, 22));
        TextView pt = Ui.title(this, "This phone on your PC");
        pt.setPadding(Ui.dp(this, 10), 0, 0, 0);
        ph.addView(pt, Ui.weight(1));
        phone.addView(ph);
        phoneStatus = Ui.text(this, "", 14, Ui.MUTED, false);
        phoneStatus.setPadding(0, Ui.dp(this, 6), 0, 0);
        phone.addView(phoneStatus);

        accessOff = new LinearLayout(this);
        accessOff.setOrientation(LinearLayout.VERTICAL);
        accessOff.addView(Ui.text(this, "Let Mirra on your PC show this phone and use it with the mouse and keyboard. "
                + "Switch it on once in Android's Accessibility settings: choose Mirra and turn it on.", 14, Ui.MUTED, false));
        accessOff.addView(Ui.button(this, "Turn it on", true, v -> {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
            startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
        }));
        // Android 13+ blocks the switch ("Restricted setting") for an app installed from a downloaded file, and many
        // phones hide the way to allow it. Mirra Setup installs the app so that Android does not block it.
        restrictedBox = new LinearLayout(this);
        restrictedBox.setOrientation(LinearLayout.VERTICAL);
        restrictedBox.addView(Ui.text(this, "\nDoes Android say \"Restricted setting\"? It blocks this switch because "
                + "Mirra was installed from a downloaded file. Fix it once: get Mirra Setup, open it and let it install "
                + "Mirra again (it removes this copy first, so connect to your PC again afterwards).", 13, Ui.WARN, false));
        restrictedBox.addView(Ui.button(this, "Get Mirra Setup", false, v -> open(SETUP_URL)));
        accessOff.addView(restrictedBox);
        phone.addView(accessOff);

        accessOn = new LinearLayout(this);
        accessOn.setOrientation(LinearLayout.VERTICAL);
        accessOn.addView(Ui.divider(this));
        accessOn.addView(Ui.settingRow(this, R.drawable.ic_touch, "Let the PC tap and type", "Use this phone with the PC's mouse and keyboard.",
                Ui.toggle(this, prefs.control(), (b, on) -> {
                    prefs.setControl(on);
                    PhoneService.settingsChanged();
                })));
        accessOn.addView(Ui.settingRow(this, R.drawable.ic_video, "Smooth video", "Up to 60 pictures a second. Off: a few screenshots a second.",
                Ui.toggle(this, prefs.video(), (b, on) -> prefs.setVideo(on))));
        accessOn.addView(Ui.settingRow(this, R.drawable.ic_pause, "Pause", "The PC can't see or use this phone.",
                Ui.toggle(this, prefs.paused(), (b, on) -> {
                    prefs.setPaused(on);
                    PhoneService.settingsChanged();
                })));
        accessOn.addView(Ui.text(this, "While your PC is looking, a notification says so. Banking apps and password "
                + "screens show black on the PC.", 12, Ui.MUTED, false));
        phone.addView(accessOn);
        root.addView(phone);

        LinearLayout about = Ui.card(this);
        about.addView(Ui.settingRow(this, R.drawable.ic_logout, "Connected to " + prefs.pcLabel(), prefs.server(), null));
        about.addView(Ui.button(this, "Forget this PC", false, v -> new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle("Forget " + prefs.pcLabel() + "?")
                .setMessage("This phone stops seeing the PC, and the PC stops seeing this phone. You can connect again with a new code.")
                .setPositiveButton("Forget", (d, w) -> {
                    prefs.unpair();
                    PhoneService.settingsChanged();
                    build();
                })
                .setNegativeButton("Cancel", null)
                .show()));
        root.addView(about);
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            refresh();
            main.postDelayed(this, 1000);
        }
    };

    /**
     * Whether Android may have marked this app "restricted" (Android 13+, installed from a downloaded file). An app
     * cannot read that mark, so this goes by who installed it: Mirra Setup and the Play Store never cause it.
     */
    private boolean restricted() {
        if (Build.VERSION.SDK_INT < 33) return false;
        try {
            String by = getPackageManager().getInstallSourceInfo(getPackageName()).getInitiatingPackageName();
            return !"app.samantha.setup".equals(by) && !"com.android.vending".equals(by);
        } catch (Exception e) {
            return true;
        }
    }

    private boolean accessibilityOn() {
        if (PhoneService.instance != null) return true;
        String enabled = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        return enabled != null && enabled.contains(new ComponentName(this, PhoneService.class).flattenToString());
    }

    private void refresh() {
        if (!prefs.paired() || pcName == null) return;
        String o = online;
        pcName.setText(prefs.pcLabel());
        pcChipHolder.removeAllViews();
        if (o == null) pcChipHolder.addView(Ui.chip(this, "Checking...", 0xffd6d9e3));
        else if (o.isEmpty()) pcChipHolder.addView(Ui.chip(this, "Online", 0xff6ee7b7));
        else {
            pcChipHolder.addView(Ui.chip(this, "Can't reach it", 0xfffcd34d));
        }
        boolean on = accessibilityOn();
        accessOff.setVisibility(on ? View.GONE : View.VISIBLE);
        accessOn.setVisibility(on ? View.VISIBLE : View.GONE);
        restrictedBox.setVisibility(restricted() ? View.VISIBLE : View.GONE);
        if (!on) phoneStatus.setText("Off. Your PC can't see this phone yet.");
        else if (PhoneService.instance == null) phoneStatus.setText("Starting...");
        else phoneStatus.setText(PhoneService.status);
        if (o != null && !o.isEmpty()) phoneStatus.setText(o);
        if (Updater.newerOnPc(this, pcVersion) && !updating && !offered.equals(pcVersion)) {
            offered = pcVersion;
            offerUpdate(pcVersion);
        }
    }

    /** The pop-up: a newer Mirra is on the PC. */
    private void offerUpdate(String version) {
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle("Update available")
                .setMessage("Mirra " + version + " is ready (you have " + Updater.installedVersion(this) + "). "
                        + "It downloads from your PC in a few seconds.")
                .setPositiveButton("Update now", (d, w) -> update())
                .setNegativeButton("Later", null)
                .show();
    }

    /** While this screen is open: is the PC there, and does it have a newer app? */
    private void checkLoop() {
        while (visible) {
            if (!prefs.paired()) {
                online = null;
                pcVersion = "";
                if (!sleep(1000)) return;
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
            if (!sleep(4000)) return;
        }
    }

    private static boolean sleep(long ms) {
        try {
            Thread.sleep(ms);
            return true;
        } catch (InterruptedException e) {
            return false;
        }
    }

    private void update() {
        if (updating || !Updater.mayInstall(this)) {
            offered = "";   // ask again when the user comes back from allowing installs
            return;
        }
        updating = true;
        Toast.makeText(this, "Downloading the update from your PC...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                Updater.install(this, prefs.server(), prefs.token());
            } catch (Exception e) {
                main.post(() -> Toast.makeText(this, "The update did not download: " + Net.explain(e), Toast.LENGTH_LONG).show());
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
