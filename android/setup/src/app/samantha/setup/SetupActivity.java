package app.samantha.setup;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.InputStream;
import java.io.OutputStream;

/**
 * Installs the Mirra app this setup carries. Android 13 and newer block the Accessibility switch ("Restricted
 * setting") for apps installed from a downloaded file; an app installed through an installer session, like this,
 * is not blocked. A copy that was installed from a file has to be removed first: an update keeps the block.
 */
public class SetupActivity extends Activity {
    static final String SAMANTHA = "app.samantha.phone";
    private static final int BG = 0xff0b0d12, CARD = 0xff141721, LINE = 0xff262b3a, TEXT = 0xfff1f3f8,
            MUTED = 0xff8e96a8, ACCENT = 0xff7c5cff, ACCENT2 = 0xff22d3ee, OK = 0xff34d399;
    static volatile String message = "";
    private LinearLayout root;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
    }

    @Override
    protected void onResume() {
        super.onResume();
        build();
    }

    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private TextView text(String s, float sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setLineSpacing(0, 1.15f);
        t.setPadding(0, dp(4), 0, dp(4));
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        return t;
    }

    private Button button(String s, boolean primary, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(16);
        b.setTextColor(primary ? 0xffffffff : TEXT);
        GradientDrawable bg = primary
                ? new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{ACCENT, ACCENT2})
                : new GradientDrawable();
        if (!primary) {
            bg.setColor(0xff1c2030);
            bg.setStroke(dp(1), LINE);
        }
        bg.setCornerRadius(dp(16));
        b.setBackground(bg);
        b.setStateListAnimator(null);
        b.setMinHeight(dp(56));
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(12);
        b.setLayoutParams(lp);
        return b;
    }

    private LinearLayout card() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(CARD);
        bg.setCornerRadius(dp(22));
        bg.setStroke(dp(1), LINE);
        c.setBackground(bg);
        c.setPadding(dp(18), dp(16), dp(18), dp(18));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(16);
        c.setLayoutParams(lp);
        return c;
    }

    /** "" when Mirra is not installed, else how it was installed. */
    private String installedBy() {
        try {
            getPackageManager().getPackageInfo(SAMANTHA, 0);
        } catch (PackageManager.NameNotFoundException e) {
            return "";
        }
        try {
            String by = getPackageManager().getInstallSourceInfo(SAMANTHA).getInitiatingPackageName();
            return by == null ? "?" : by;
        } catch (Exception e) {
            return "?";
        }
    }

    private void build() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(28), dp(20), dp(40));
        android.widget.ImageView logo = new android.widget.ImageView(this);
        logo.setImageResource(R.drawable.logo);
        root.addView(logo, new LinearLayout.LayoutParams(dp(64), dp(64)));
        root.addView(text("Mirra Setup", 28, TEXT, true));
        root.addView(text("Installs the Mirra app so that Android lets you switch on \"Let this PC see and use my "
                + "phone\".", 15, MUTED, false));

        String by = installedBy();
        LinearLayout c = card();
        if (by.isEmpty()) {
            c.addView(text("Install Mirra", 19, TEXT, true));
            c.addView(text("Android asks once to allow Mirra Setup to install apps: switch that on, come back here "
                    + "and tap Install again.", 14, MUTED, false));
            c.addView(button("Install Mirra", true, v -> install()));
        } else if (by.equals(getPackageName()) || by.equals("com.android.vending")) {
            c.addView(text("Mirra is installed", 19, OK, true));
            c.addView(text("You can open it now. This setup app is no longer needed, so you can remove it.", 14, MUTED, false));
            c.addView(button("Open Mirra", true, v -> {
                Intent open = getPackageManager().getLaunchIntentForPackage(SAMANTHA);
                if (open != null) startActivity(open);
            }));
            c.addView(button("Remove Mirra Setup", false, v -> startActivity(
                    new Intent(Intent.ACTION_DELETE, Uri.parse("package:" + getPackageName())))));
        } else {
            c.addView(text("Mirra is already installed, but from a downloaded file", 19, TEXT, true));
            c.addView(text("Android blocks its Accessibility switch (\"Restricted setting\"), and updating it keeps that "
                    + "block. Remove it, then install it again from here. Afterwards, connect it to your PC again with a "
                    + "new code.", 14, MUTED, false));
            c.addView(button("1. Remove the old Mirra", true, v -> startActivity(
                    new Intent(Intent.ACTION_DELETE, Uri.parse("package:" + SAMANTHA)))));
            c.addView(text("Then this screen offers to install it.", 13, MUTED, false));
        }
        if (!message.isEmpty()) c.addView(text(message, 14, 0xfffbbf24, false));
        root.addView(c);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(BG);
        scroll.setFillViewport(true);
        scroll.addView(root);
        setContentView(scroll);
    }

    private void install() {
        if (!getPackageManager().canRequestPackageInstalls()) {
            Toast.makeText(this, "Allow Mirra Setup to install apps, then tap Install again.", Toast.LENGTH_LONG).show();
            startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName())));
            return;
        }
        message = "Installing...";
        build();
        new Thread(() -> {
            try {
                PackageInstaller installer = getPackageManager().getPackageInstaller();
                PackageInstaller.SessionParams params =
                        new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                params.setAppPackageName(SAMANTHA);
                int id = installer.createSession(params);
                try (PackageInstaller.Session session = installer.openSession(id)) {
                    try (InputStream in = getAssets().open("Mirra.apk"); OutputStream out = session.openWrite("app", 0, -1)) {
                        byte[] buf = new byte[65536];
                        int n;
                        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                        session.fsync(out);
                    }
                    PendingIntent done = PendingIntent.getBroadcast(this, id, new Intent(this, Done.class),
                            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
                    session.commit(done.getIntentSender());
                }
            } catch (Exception e) {
                message = "Could not install: " + e.getMessage();
                runOnUiThread(this::build);
            }
        }).start();
    }

    /** Android reports back here: ask the user to confirm, or say what went wrong. */
    public static final class Done extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent intent) {
            int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
            if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                @SuppressWarnings("deprecation")   // the typed version needs Android 13
                Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
                if (confirm != null) {
                    confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    c.startActivity(confirm);
                }
                return;
            }
            if (status == PackageInstaller.STATUS_SUCCESS) {
                message = "";
            } else if (status == PackageInstaller.STATUS_FAILURE_CONFLICT) {
                message = "Remove the old Mirra first, then install again.";
            } else if (status != PackageInstaller.STATUS_FAILURE_ABORTED) {
                String why = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
                message = "Not installed" + (why == null ? "." : ": " + why);
            } else {
                message = "";
            }
            Intent back = new Intent(c, SetupActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            c.startActivity(back);
        }
    }
}
