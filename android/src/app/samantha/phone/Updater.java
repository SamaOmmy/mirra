package app.samantha.phone;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.provider.Settings;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Updates this app from the PC it is paired with. The PC carries the app of its own version, so after the PC
 * updates itself the phone offers the matching app. Android asks the user to confirm every install.
 */
final class Updater {
    private Updater() {}

    static String installedVersion(Context c) {
        try {
            return c.getPackageManager().getPackageInfo(c.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "0";
        }
    }

    /** True when the PC (of version `pcVersion`) has a newer app than this one. */
    static boolean newerOnPc(Context c, String pcVersion) {
        return pcVersion != null && !pcVersion.isEmpty() && Net.compareVersions(pcVersion, installedVersion(c)) > 0;
    }

    /** Android's one-time "allow installs from this app" switch. False after opening it for the user. */
    static boolean mayInstall(Activity a) {
        if (a.getPackageManager().canRequestPackageInstalls()) return true;
        Toast.makeText(a, "Allow Samantha to install its updates, then tap Update again.", Toast.LENGTH_LONG).show();
        a.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + a.getPackageName())));
        return false;
    }

    /** Downloads the app from the PC and hands it to Android's installer. Runs on a worker thread. */
    static void install(Context c, String base, String token) throws IOException {
        File apk = new File(c.getCacheDir(), "update.apk");
        Net.download(base + "/api/phone/app.apk", token, apk);
        PackageInstaller installer = c.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(c.getPackageName());
        int id = installer.createSession(params);
        try (PackageInstaller.Session session = installer.openSession(id)) {
            try (InputStream in = new FileInputStream(apk); OutputStream out = session.openWrite("app", 0, apk.length())) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                session.fsync(out);
            }
            Intent done = new Intent(c, Done.class);
            PendingIntent pending = PendingIntent.getBroadcast(c, id, done,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
            session.commit(pending.getIntentSender());
        } finally {
            apk.delete();
        }
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
            } else if (status == PackageInstaller.STATUS_FAILURE_CONFLICT || status == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE) {
                Toast.makeText(c, "This update is signed differently from the installed app. Uninstall Samantha, "
                        + "then install it again from the link on your PC.", Toast.LENGTH_LONG).show();
            } else if (status != PackageInstaller.STATUS_SUCCESS && status != PackageInstaller.STATUS_FAILURE_ABORTED) {
                String why = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
                Toast.makeText(c, "The update was not installed" + (why == null ? "." : ": " + why), Toast.LENGTH_LONG).show();
            }
        }
    }
}
