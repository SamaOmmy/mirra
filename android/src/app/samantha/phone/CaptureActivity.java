package app.samantha.phone;

import android.app.Activity;
import android.content.Intent;
import android.media.projection.MediaProjectionConfig;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;

/**
 * Invisible: asks Android for permission to record the screen (the "Start now" question, which PhoneService answers
 * by itself), then hands the permission to CaptureService.
 */
public class CaptureActivity extends Activity {
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        MediaProjectionManager mpm = getSystemService(MediaProjectionManager.class);
        Intent ask = Build.VERSION.SDK_INT >= 34
                ? mpm.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())   // whole screen only
                : mpm.createScreenCaptureIntent();
        PhoneService.expectConsent();
        startActivityForResult(ask, 1);
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result == RESULT_OK && data != null) {
            Intent start = new Intent(this, CaptureService.class)
                    .putExtra(CaptureService.EXTRA_CODE, result)
                    .putExtra(CaptureService.EXTRA_DATA, data);
            startForegroundService(start);
        } else {
            PhoneService.captureFailed("Screen recording was not allowed.");
        }
        finish();
        overridePendingTransition(0, 0);
    }
}
