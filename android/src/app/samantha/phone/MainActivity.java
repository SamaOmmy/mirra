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
            "https://github.com/" + Updater.REPO + "/releases/latest/download/" + Updater.SETUP_FILE;
    private static final int PICK_FILES = 7;
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
    private TextView tsStatus, pcHelp;
    private Button tsButton, openTailscale;
    private View lowDataRow;
    private volatile String online;       // null while unknown, "" when the PC answers, else the problem
    private volatile String pcVersion = "";
    private static volatile String gitHubVersion = "";   // the newest release on GitHub, "" while unknown
    private static long gitHubChecked;                    // when GitHub was last asked (uptime ms)
    private String offered = "";          // the update version already offered in a pop-up
    private boolean updating;
    private int checks;                   // the newest checkLoop runs; older ones stop

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
        int generation = ++checks;
        new Thread(() -> checkLoop(generation), "mirra-check").start();
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
    // -- not paired yet: two steps, each checked by the app itself ---------------------------------------
    private static final String TAILSCALE = "com.tailscale.ipn";

    private void buildPairing() {
        LinearLayout hero = Ui.hero(this);
        hero.addView(Ui.text(this, "Connect to your PC", 22, 0xffffffff, true));
        hero.addView(Ui.text(this, "Two steps. Mirra ticks them off as you go.", 15, 0xe6ffffff, false));
        root.addView(hero);

        LinearLayout one = Ui.card(this);
        one.addView(stepTitle("1", "Tailscale on this phone"));
        tsStatus = Ui.text(this, "", 14, Ui.MUTED, false);
        tsStatus.setPadding(0, Ui.dp(this, 6), 0, 0);
        one.addView(tsStatus);
        tsButton = Ui.button(this, "", true, v -> tailscaleAction());
        one.addView(tsButton);
        root.addView(one);

        LinearLayout two = Ui.card(this);
        two.addView(stepTitle("2", "Scan the code on your PC"));
        two.addView(Ui.text(this, "1.  On your PC, open Mirra. Its Home page shows a QR code.\n"
                + "2.  Point this phone's camera at it and tap the link.\n"
                + "3.  Tap \"Open Mirra and connect\". Done.", 14, Ui.TEXT, false));
        LinearLayout typed = new LinearLayout(this);
        typed.setOrientation(LinearLayout.VERTICAL);
        typed.setVisibility(View.GONE);
        Button showTyped = Ui.button(this, "No camera? Type it in", false, v -> {
            typed.setVisibility(View.VISIBLE);
            v.setVisibility(View.GONE);
        });
        two.addView(showTyped);
        typed.addView(caption("PC name (or address)"));
        addressField = field("As shown on the PC, e.g.  my-pc", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        String old = prefs.server();
        if (!old.isEmpty()) addressField.setText(Net.host(old));
        typed.addView(addressField);
        typed.addView(caption("Code"));
        codeField = field("6 digits", InputType.TYPE_CLASS_NUMBER);
        codeField.setImeOptions(EditorInfo.IME_ACTION_GO);
        codeField.setOnEditorActionListener((v, action, event) -> {
            pairFromFields();
            return true;
        });
        typed.addView(codeField);
        connect = Ui.button(this, "Connect", true, v -> pairFromFields());
        typed.addView(connect);
        two.addView(typed);
        pairMessage = Ui.text(this, "", 14, Ui.WARN, false);
        pairMessage.setPadding(0, Ui.dp(this, 10), 0, 0);
        two.addView(pairMessage);
        root.addView(two);
    }

    private LinearLayout stepTitle(String number, String title) {
        LinearLayout row = Ui.row(this);
        TextView badge = Ui.text(this, number, 15, 0xffffffff, true);
        badge.setGravity(android.view.Gravity.CENTER);
        badge.setBackground(Ui.gradient(this, Ui.ACCENT, Ui.ACCENT2, 15));
        row.addView(badge, new LinearLayout.LayoutParams(Ui.dp(this, 30), Ui.dp(this, 30)));
        TextView t = Ui.title(this, title);
        t.setPadding(Ui.dp(this, 12), 0, 0, 0);
        row.addView(t, Ui.weight(1));
        return row;
    }

    private boolean tailscaleInstalled() {
        try {
            getPackageManager().getPackageInfo(TAILSCALE, 0);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** Tailscale (or another VPN) is switched on. */
    private boolean vpnOn() {
        try {
            android.net.ConnectivityManager cm = getSystemService(android.net.ConnectivityManager.class);
            android.net.NetworkCapabilities caps = cm.getNetworkCapabilities(cm.getActiveNetwork());
            return caps != null && caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN);
        } catch (Exception e) {
            return false;
        }
    }

    private void tailscaleAction() {
        if (!tailscaleInstalled()) {
            open("https://play.google.com/store/apps/details?id=" + TAILSCALE);
        } else {
            Intent i = getPackageManager().getLaunchIntentForPackage(TAILSCALE);
            if (i != null) startActivity(i);
        }
    }

    private void refreshTailscale() {
        if (tsStatus == null) return;
        if (!tailscaleInstalled()) {
            tsStatus.setText("Not installed yet. It is free: install it, then sign in with the same account as on your PC.");
            tsStatus.setTextColor(Ui.WARN);
            tsButton.setText("Get Tailscale");
            tsButton.setVisibility(View.VISIBLE);
        } else if (!vpnOn()) {
            tsStatus.setText("Installed, but switched off. Open it, sign in with the same account as on your PC, and switch it on.");
            tsStatus.setTextColor(Ui.WARN);
            tsButton.setText("Open Tailscale");
            tsButton.setVisibility(View.VISIBLE);
        } else {
            tsStatus.setText("\u2713  Tailscale is on.");
            tsStatus.setTextColor(Ui.OK);
            tsButton.setVisibility(View.GONE);
        }
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
    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK_FILES || result != RESULT_OK || data == null) return;
        java.util.List<Uri> uris = new java.util.ArrayList<>();
        if (data.getClipData() != null) {
            for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri());
        } else if (data.getData() != null) {
            uris.add(data.getData());
        }
        if (Transfer.sendToPc(this, uris)) {
            Toast.makeText(this, (uris.size() == 1 ? "Sending to " : "Sending " + uris.size() + " files to ")
                    + prefs.pcLabel() + "...", Toast.LENGTH_SHORT).show();
        }
    }

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
        pcHelp = Ui.text(this, "", 14, 0xffffffff, false);
        pcHelp.setPadding(0, Ui.dp(this, 8), 0, 0);
        pcHelp.setVisibility(View.GONE);
        hero.addView(pcHelp);
        openTailscale = Ui.button(this, "Open Tailscale", false, v -> tailscaleAction());
        openTailscale.setVisibility(View.GONE);
        hero.addView(openTailscale);
        Button show = Ui.button(this, "Show my PC", false, v -> startActivity(new Intent(this, ViewerActivity.class)));
        show.setBackground(Ui.ripple(Ui.round(this, 0xffffffff, 16, 0), Ui.round(this, 0xffffffff, 16, 0)));
        show.setTextColor(0xff1d1650);
        show.setTextSize(17);
        show.setMinHeight(Ui.dp(this, 58));
        hero.addView(show);
        root.addView(hero);

        LinearLayout files = Ui.card(this);
        files.addView(Ui.settingRow(this, R.drawable.ic_file, "Files", "Send photos and files to " + prefs.pcLabel()
                + ". In any app you can also tap Share, then Mirra. On the PC they go to Downloads\\Mirra.", null));
        files.addView(Ui.button(this, "Send files to the PC", false, v -> {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
            startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("*/*").putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true), PICK_FILES);
        }));
        root.addView(files);

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
                + "You do this once:", 14, Ui.MUTED, false));
        accessOff.addView(Ui.text(this, "1.  Tap Turn it on below.\n2.  In the list, tap Mirra.\n"
                + "3.  Switch on \"Use Mirra\".\n4.  Tap Allow.", 15, Ui.TEXT, false));
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
        offerUpdateIfAny();
        refreshTailscale();
        if (!prefs.paired() || pcName == null) return;
        String o = online;
        pcName.setText(prefs.pcLabel());
        pcChipHolder.removeAllViews();
        if (o == null) pcChipHolder.addView(Ui.chip(this, "Checking...", 0xffd6d9e3));
        else if (o.isEmpty()) pcChipHolder.addView(Ui.chip(this, "Online", 0xff6ee7b7));
        else {
            pcChipHolder.addView(Ui.chip(this, "Can't reach it", 0xfffcd34d));
        }
        boolean unreachable = o != null && !o.isEmpty();
        boolean vpn = vpnOn();
        pcHelp.setVisibility(unreachable ? View.VISIBLE : View.GONE);
        pcHelp.setText(!vpn ? "Tailscale is off on this phone. Switch it on." :
                "Check that the PC is on and awake, and that Mirra is on there (Home page on the PC).");
        openTailscale.setVisibility(unreachable && !vpn ? View.VISIBLE : View.GONE);
        boolean on = accessibilityOn();
        accessOff.setVisibility(on ? View.GONE : View.VISIBLE);
        accessOn.setVisibility(on ? View.VISIBLE : View.GONE);
        restrictedBox.setVisibility(restricted() ? View.VISIBLE : View.GONE);
        if (!on) phoneStatus.setText("Off. Your PC can't see this phone yet.");
        else if (PhoneService.instance == null) phoneStatus.setText("Starting...");
        else phoneStatus.setText(PhoneService.status);
        if (o != null && !o.isEmpty()) phoneStatus.setText(o);
    }

    /** A newer Mirra on GitHub (or, when GitHub can't be reached, on the PC): offer it once. */
    private void offerUpdateIfAny() {
        String gitHub = gitHubVersion, pc = pcVersion;
        boolean fromGitHub = Updater.newer(this, gitHub) && (pc.isEmpty() || Net.compareVersions(gitHub, pc) >= 0);
        String version = fromGitHub ? gitHub : pc;
        if (updating || !Updater.newer(this, version) || offered.equals(version)) return;
        offered = version;
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle("Update available")
                .setMessage("Mirra " + version + " is ready (you have " + Updater.installedVersion(this) + "). "
                        + "It downloads in a few seconds.")
                .setPositiveButton("Update now", (d, w) -> update(version, fromGitHub))
                .setNegativeButton("Later", null)
                .show();
    }

    /** While this screen is open: is there a new release, is the PC there, and does it have a newer app? */
    private void checkLoop(int generation) {
        while (visible && generation == checks) {
            long now = android.os.SystemClock.elapsedRealtime();
            if (gitHubChecked == 0 || now - gitHubChecked > 10 * 60_000) {   // GitHub allows 60 asks an hour
                gitHubChecked = now;
                gitHubVersion = Updater.latestOnGitHub();
            }
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

    private void update(String version, boolean fromGitHub) {
        if (updating || !Updater.mayInstall(this)) {
            offered = "";   // ask again when the user comes back from allowing installs
            return;
        }
        updating = true;
        Toast.makeText(this, "Downloading Mirra " + version + "...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                if (fromGitHub) Updater.installFromGitHub(this, version);
                else Updater.installFromPc(this, prefs.server(), prefs.token());
            } catch (Exception e) {
                String why = fromGitHub ? "check the internet and try again (" + e.getMessage() + ")" : Net.explain(e);
                main.post(() -> Toast.makeText(this, "The update did not download: " + why, Toast.LENGTH_LONG).show());
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
