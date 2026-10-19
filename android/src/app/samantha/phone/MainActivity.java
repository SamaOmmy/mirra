package app.samantha.phone;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

/** Pairing, the one permission to switch on, and two switches. Everything else happens on the PC. */
public class MainActivity extends Activity {
    private Prefs prefs;
    private TextView pairing;
    private TextView access;
    private TextView link;
    private Switch control;
    private Switch pause;
    private LinearLayout manual;
    private EditText serverField;
    private EditText tokenField;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            refresh();
            handler.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = new Prefs(this);
        handleLink(getIntent());
        buildUi();
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleLink(intent);
        refresh();
    }

    @Override
    protected void onResume() {
        super.onResume();
        handler.post(tick);
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(tick);
        super.onPause();
    }

    /** samanthaphone://pair?server=...&token=... from the link on the Samantha page. */
    private void handleLink(Intent intent) {
        Uri uri = intent == null ? null : intent.getData();
        if (uri == null || !"samanthaphone".equals(uri.getScheme())) return;
        String server = uri.getQueryParameter("server");
        String token = uri.getQueryParameter("token");
        if (server == null || token == null || server.isEmpty() || token.length() < 16) {
            Toast.makeText(this, "That pairing link is not complete. Open it again from the Samantha page.", Toast.LENGTH_LONG).show();
            return;
        }
        prefs.pair(server, token);
        PhoneService.settingsChanged();
        Toast.makeText(this, "Paired with " + Prefs.normalize(server), Toast.LENGTH_LONG).show();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private TextView text(String s, int sp, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        if (bold) t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        t.setPadding(0, dp(6), 0, dp(6));
        return t;
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(20), dp(20), dp(32));

        root.addView(text("Samantha Phone", 24, true));
        root.addView(text("Lets the Samantha Screen Mirror app on your PC show this phone and use it with the mouse "
                + "and keyboard. It connects out to your PC over Tailscale and never accepts connections itself.", 14, false));

        root.addView(text("1. Pair with your PC", 18, true));
        pairing = text("", 15, false);
        root.addView(pairing);
        root.addView(text("On this phone, open the Samantha page, go to Settings > Use this phone from the PC and tap "
                + "\"Pair this app\".", 13, false));
        Button type = new Button(this);
        type.setText("Type the address and token instead");
        type.setOnClickListener(v -> manual.setVisibility(manual.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE));
        root.addView(type);
        manual = new LinearLayout(this);
        manual.setOrientation(LinearLayout.VERTICAL);
        manual.setVisibility(View.GONE);
        serverField = new EditText(this);
        serverField.setHint("PC address, e.g. https://pc.tail1234.ts.net");
        serverField.setSingleLine();
        serverField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        tokenField = new EditText(this);
        tokenField.setHint("Access token (from the PC)");
        tokenField.setSingleLine();
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        Button save = new Button(this);
        save.setText("Save");
        save.setOnClickListener(v -> {
            if (serverField.getText().length() == 0 || tokenField.getText().length() < 16) {
                Toast.makeText(this, "Enter the address and the full token.", Toast.LENGTH_LONG).show();
                return;
            }
            prefs.pair(serverField.getText().toString(), tokenField.getText().toString());
            tokenField.setText("");
            manual.setVisibility(View.GONE);
            PhoneService.settingsChanged();
            refresh();
        });
        manual.addView(serverField);
        manual.addView(tokenField);
        manual.addView(save);
        root.addView(manual);
        Button unpair = new Button(this);
        unpair.setText("Forget this PC");
        unpair.setOnClickListener(v -> {
            prefs.unpair();
            PhoneService.settingsChanged();
            refresh();
        });
        root.addView(unpair);

        root.addView(text("2. Allow it to see and use the screen", 18, true));
        access = text("", 15, false);
        root.addView(access);
        Button open = new Button(this);
        open.setText("Open Accessibility settings");
        open.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        root.addView(open);
        root.addView(text("Choose \"Samantha Phone\", switch it on and confirm. You do this once. If the switch is greyed out "
                + "(Android 13 and newer do that for apps installed from outside the Play Store): open App info below, "
                + "tap the three dots at the top right, choose \"Allow restricted settings\", then try again.", 13, false));
        Button info = new Button(this);
        info.setText("Open App info");
        info.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:" + getPackageName()))));
        root.addView(info);

        root.addView(text("3. You are in control", 18, true));
        link = text("", 15, false);
        root.addView(link);
        control = new Switch(this);
        control.setText("Let the PC tap, swipe and type");
        control.setChecked(prefs.control());
        control.setOnCheckedChangeListener((CompoundButton b, boolean on) -> {
            prefs.setControl(on);
            PhoneService.settingsChanged();
        });
        root.addView(control);
        pause = new Switch(this);
        pause.setText("Pause: the PC cannot see or use this phone");
        pause.setChecked(prefs.paused());
        pause.setOnCheckedChangeListener((CompoundButton b, boolean on) -> {
            prefs.setPaused(on);
            PhoneService.settingsChanged();
        });
        root.addView(pause);
        root.addView(text("While your PC page is watching, Android shows a notification so you always know. "
                + "Turning the Accessibility switch off stops everything. Some screens (banking apps, password prompts) "
                + "are blocked by Android and show black.", 13, false));

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
    }

    private void refresh() {
        pairing.setText(prefs.paired() ? "Paired with " + prefs.server() : "Not paired yet.");
        boolean on = PhoneService.instance != null;
        access.setText(on ? "Accessibility is on." : "Accessibility is off, so the PC cannot see or use this phone yet.");
        link.setText(on ? PhoneService.status : "Waiting for the Accessibility switch.");
        if (control.isChecked() != prefs.control()) control.setChecked(prefs.control());
        if (pause.isChecked() != prefs.paused()) pause.setChecked(prefs.paused());
    }
}
