package app.samantha.phone;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.provider.Settings;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Updates this app from the newest release on GitHub, like Mirra on the PC does. The release carries Mirra Setup,
 * which has this app inside it, so the update is taken out of that file. If GitHub can't be reached, the PC this
 * phone is paired with also carries the app of its own version. Android checks that an update is signed like the
 * installed app, and asks the user to confirm every install.
 */
final class Updater {
    private Updater() {}

    static final String REPO = "SamaOmmy/samantha-screen-mirror";
    static final String LATEST = "https://api.github.com/repos/" + REPO + "/releases/latest";
    static final String DOWNLOAD = "https://github.com/" + REPO + "/releases/download/";
    static final String SETUP_FILE = "Mirra-for-Android-Setup.apk";   // the release file (packaging/build-release.ps1)
    static final String INSIDE_SETUP = "assets/Mirra.apk";             // where Setup carries the app (android/build.py)

    static String installedVersion(Context c) {
        try {
            return c.getPackageManager().getPackageInfo(c.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "0";
        }
    }

    /** True when `version` is newer than this app. */
    static boolean newer(Context c, String version) {
        return version != null && !version.isEmpty() && Net.compareVersions(version, installedVersion(c)) > 0;
    }

    /** The newest released version on GitHub, or "" when it can't be told (no internet, or no phone file in it). */
    static String latestOnGitHub() {
        try {
            JSONObject release = new JSONObject(new String(Net.get(LATEST, null), "UTF-8"));
            JSONArray assets = release.optJSONArray("assets");
            for (int i = 0; assets != null && i < assets.length(); i++) {
                if (SETUP_FILE.equals(assets.getJSONObject(i).optString("name"))) {
                    return release.optString("tag_name", "").replaceFirst("^v", "");
                }
            }
        } catch (Exception ignored) {
            // offline, or GitHub is busy: the next check tries again
        }
        return "";
    }

    /** Android's one-time "allow installs from this app" switch. False after opening it for the user. */
    static boolean mayInstall(Activity a) {
        if (a.getPackageManager().canRequestPackageInstalls()) return true;
        Toast.makeText(a, "Allow Mirra to install its updates, then tap Update again.", Toast.LENGTH_LONG).show();
        a.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + a.getPackageName())));
        return false;
    }

    /** Downloads Mirra `version` from GitHub and hands it to Android's installer. Runs on a worker thread. */
    static void installFromGitHub(Context c, String version) throws IOException {
        File setup = new File(c.getCacheDir(), "setup.apk"), apk = new File(c.getCacheDir(), "update.apk");
        try {
            Net.download(DOWNLOAD + "v" + version + "/" + SETUP_FILE, null, setup);
            try (ZipFile zip = new ZipFile(setup)) {
                ZipEntry entry = zip.getEntry(INSIDE_SETUP);
                if (entry == null) throw new IOException("the download has no Mirra in it");
                try (InputStream in = zip.getInputStream(entry); OutputStream out = new FileOutputStream(apk)) {
                    copy(in, out);
                }
            }
            PackageInfo info = c.getPackageManager().getPackageArchiveInfo(apk.getPath(), 0);
            if (info == null || !c.getPackageName().equals(info.packageName) || !version.equals(info.versionName)) {
                throw new IOException("the download is not Mirra " + version);
            }
            commit(c, apk);
        } finally {
            setup.delete();
            apk.delete();
        }
    }

    /** Downloads the app from the PC and hands it to Android's installer. Runs on a worker thread. */
    static void installFromPc(Context c, String base, String token) throws IOException {
        File apk = new File(c.getCacheDir(), "update.apk");
        try {
            Net.download(base + "/api/phone/app.apk", token, apk);
            commit(c, apk);
        } finally {
            apk.delete();
        }
    }

    private static void commit(Context c, File apk) throws IOException {
        PackageInstaller installer = c.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(c.getPackageName());
        int id = installer.createSession(params);
        try (PackageInstaller.Session session = installer.openSession(id)) {
            try (InputStream in = new FileInputStream(apk); OutputStream out = session.openWrite("app", 0, apk.length())) {
                copy(in, out);
                session.fsync(out);
            }
            Intent done = new Intent(c, Done.class);
            PendingIntent pending = PendingIntent.getBroadcast(c, id, done,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
            session.commit(pending.getIntentSender());
        }
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
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
                Toast.makeText(c, "This update is signed differently from the installed app. Uninstall Mirra, "
                        + "then install it again from the link on your PC.", Toast.LENGTH_LONG).show();
            } else if (status != PackageInstaller.STATUS_SUCCESS && status != PackageInstaller.STATUS_FAILURE_ABORTED) {
                String why = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
                Toast.makeText(c, "The update was not installed" + (why == null ? "." : ": " + why), Toast.LENGTH_LONG).show();
            }
        }
    }
}
