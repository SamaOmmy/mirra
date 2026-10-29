package app.samantha.phone;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/** Share > Mirra in any app: the shared files go to the paired PC (Transfer). Shows nothing but a short message. */
public class ShareActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        List<Uri> uris = shared(getIntent());
        Prefs prefs = new Prefs(this);
        if (!prefs.paired()) {
            Toast.makeText(this, "Connect Mirra to your PC first: open Mirra and scan the code on the PC.", Toast.LENGTH_LONG).show();
        } else if (uris.isEmpty()) {
            Toast.makeText(this, "Mirra can send files and photos to your PC, not this.", Toast.LENGTH_LONG).show();
        } else if (Transfer.sendToPc(this, uris)) {
            Toast.makeText(this, (uris.size() == 1 ? "Sending to " : "Sending " + uris.size() + " files to ")
                    + prefs.pcLabel() + "...", Toast.LENGTH_SHORT).show();
        }
        finish();
    }

    @SuppressWarnings("deprecation")   // the typed getParcelable versions need Android 13
    static List<Uri> shared(Intent intent) {
        List<Uri> uris = new ArrayList<>();
        if (intent == null) return uris;
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            Uri one = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (one != null) uris.add(one);
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction())) {
            ArrayList<Uri> many = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (many != null) uris.addAll(many);
        }
        if (uris.isEmpty() && intent.getClipData() != null) {   // some apps put them only here
            for (int i = 0; i < intent.getClipData().getItemCount(); i++) {
                Uri uri = intent.getClipData().getItemAt(i).getUri();
                if (uri != null) uris.add(uri);
            }
        }
        return uris;
    }
}
