package app.samantha.phone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.webkit.MimeTypeMap;

import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URLEncoder;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Files both ways (samantha_mirror/transfer.py). Share > Mirra in any app sends files to the PC, which saves them in
 * Downloads\Mirra. Files the PC sends arrive over the usual command link and are saved in this phone's Downloads.
 * A notification says how it went. One file at a time, so a big batch does not swamp a slow connection.
 */
final class Transfer {
    private Transfer() {}

    private static final String CHANNEL = "files";
    private static final ExecutorService ONE_AT_A_TIME = Executors.newSingleThreadExecutor();
    private static int nextId = 100;

    /** Sends files to the paired PC in the background. False when there is no PC to send to. */
    static boolean sendToPc(Context context, List<Uri> uris) {
        Context c = context.getApplicationContext();
        Prefs prefs = new Prefs(c);
        if (!prefs.paired() || uris.isEmpty()) return false;
        String pc = prefs.pcLabel();
        ONE_AT_A_TIME.execute(() -> {
            int id = nextId++, sent = 0;
            String last = "", error = null;
            for (Uri uri : uris) {
                String name = displayName(c, uri);
                notify(c, id, "Sending " + name + " to " + pc + "...", null, true, null);
                try {
                    upload(c, prefs, uri, name);
                    sent++;
                    last = name;
                } catch (IOException | RuntimeException e) {
                    error = name + ": " + Net.explain(e);
                }
            }
            if (error != null) {
                notify(c, id, sent == 0 ? "Not sent to " + pc : "Sent " + sent + " of " + uris.size() + " to " + pc, error, false, null);
            } else {
                notify(c, id, (sent == 1 ? "Sent " + last : "Sent " + sent + " files") + " to " + pc,
                        "On the PC: Downloads\\Mirra", false, null);
            }
        });
        return true;
    }

    private static void upload(Context c, Prefs prefs, Uri uri, String name) throws IOException {
        long size = size(c, uri);
        HttpURLConnection conn = Net.open("POST", prefs.server() + "/api/phone/upload", prefs.token(), 120000);
        try {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/octet-stream");
            conn.setRequestProperty("X-File-Name", URLEncoder.encode(name, "UTF-8").replace("+", "%20"));
            if (size >= 0) conn.setFixedLengthStreamingMode(size);
            else conn.setChunkedStreamingMode(256 * 1024);
            try (InputStream in = c.getContentResolver().openInputStream(uri); OutputStream out = conn.getOutputStream()) {
                if (in == null) throw new IOException("the file can't be read");
                copy(in, out);
            }
            Net.check(conn);
        } finally {
            conn.disconnect();
        }
    }

    /** The PC has a file for this phone: save it in Downloads. Runs on the command link's thread, so it hands off. */
    static void receive(Context context, Prefs prefs, JSONObject command) {
        Context c = context.getApplicationContext();
        String name = command.optString("name", "file");
        String url = prefs.server() + "/api/phone/files/" + command.optString("id");
        String token = prefs.token(), pc = prefs.pcLabel();
        ONE_AT_A_TIME.execute(() -> {
            int id = nextId++;
            notify(c, id, "Receiving " + name + " from " + pc + "...", null, true, null);
            ContentResolver resolver = c.getContentResolver();
            Uri item = null;
            try {
                ContentValues values = new ContentValues();
                values.put(MediaStore.Downloads.DISPLAY_NAME, name);
                values.put(MediaStore.Downloads.MIME_TYPE, mimeType(name));
                values.put(MediaStore.Downloads.IS_PENDING, 1);
                item = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (item == null) throw new IOException("there is no room in Downloads");
                HttpURLConnection conn = Net.stream(url, token, 60000);
                try (InputStream in = conn.getInputStream(); OutputStream out = resolver.openOutputStream(item)) {
                    if (out == null) throw new IOException("Downloads can't be written");
                    copy(in, out);
                } finally {
                    conn.disconnect();
                }
                values.clear();
                values.put(MediaStore.Downloads.IS_PENDING, 0);
                resolver.update(item, values, null, null);
                Intent open = new Intent(Intent.ACTION_VIEW).setDataAndType(item, mimeType(name))
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                notify(c, id, "Got " + name + " from " + pc, "Saved in Downloads. Tap to open.", false, open);
            } catch (IOException | RuntimeException e) {
                if (item != null) resolver.delete(item, null, null);
                notify(c, id, "Could not receive " + name, Net.explain(e), false, null);
            }
        });
    }

    static String displayName(Context c, Uri uri) {
        try (Cursor cursor = c.getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) return cursor.getString(0);
        } catch (RuntimeException ignored) {
            // some apps share files without a name
        }
        String last = uri.getLastPathSegment();
        return last == null || last.isEmpty() ? "file" : last;
    }

    private static long size(Context c, Uri uri) {
        try (Cursor cursor = c.getContentResolver().query(uri, new String[]{OpenableColumns.SIZE}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) return cursor.getLong(0);
        } catch (RuntimeException ignored) {
            // unknown: sent without a length
        }
        return -1;
    }

    private static String mimeType(String name) {
        int dot = name.lastIndexOf('.');
        String type = dot < 0 ? null : MimeTypeMap.getSingleton().getMimeTypeFromExtension(name.substring(dot + 1).toLowerCase());
        return type == null ? "application/octet-stream" : type;
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[256 * 1024];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    }

    private static void notify(Context c, int id, String title, String text, boolean ongoing, Intent tap) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Files", NotificationManager.IMPORTANCE_DEFAULT));
        Notification.Builder n = new Notification.Builder(c, CHANNEL)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(title)
                .setOngoing(ongoing)
                .setOnlyAlertOnce(true)
                .setAutoCancel(!ongoing);
        if (text != null) n.setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text));
        if (ongoing) n.setProgress(0, 0, true);
        if (tap != null) n.setContentIntent(PendingIntent.getActivity(c, id, tap, PendingIntent.FLAG_IMMUTABLE));
        nm.notify(id, n.build());
    }
}
