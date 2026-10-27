package app.samantha.phone;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.view.GestureDetector;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;

/**
 * Shows the PC's screen, fitted to the phone. Pinch to zoom, drag to look around while zoomed, double-tap to fit
 * again, single tap to show or hide the bars. (The PC is view-only: nothing here is sent to the PC.)
 */
final class ScreenView extends View {
    interface Listener {
        void onSingleTap();
    }

    private final Object lock = new Object();
    private Bitmap shown;      // what onDraw draws
    private Bitmap spare;      // the next picture is decoded into this one
    private final Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Matrix matrix = new Matrix();
    private float zoom = 1f, panX, panY;
    private final ScaleGestureDetector scaler;
    private final GestureDetector gestures;
    private Listener listener;

    ScreenView(Context c) {
        super(c);
        setBackgroundColor(0xff000000);
        scaler = new ScaleGestureDetector(c, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override
            public boolean onScale(ScaleGestureDetector d) {
                float before = zoom;
                zoom = Math.max(1f, Math.min(6f, zoom * d.getScaleFactor()));
                float f = zoom / before;
                // keep the point between the fingers where it is
                float cx = d.getFocusX() - getWidth() / 2f, cy = d.getFocusY() - getHeight() / 2f;
                panX = cx - (cx - panX) * f;
                panY = cy - (cy - panY) * f;
                clampPan();
                invalidate();
                return true;
            }
        });
        gestures = new GestureDetector(c, new GestureDetector.SimpleOnGestureListener() {
            @Override
            public boolean onSingleTapConfirmed(MotionEvent e) {
                if (listener != null) listener.onSingleTap();
                return true;
            }

            @Override
            public boolean onDoubleTap(MotionEvent e) {
                if (zoom > 1.01f) {
                    resetZoom();
                } else {
                    zoom = 2.5f;
                    float cx = e.getX() - getWidth() / 2f, cy = e.getY() - getHeight() / 2f;
                    panX = -cx * (zoom - 1);
                    panY = -cy * (zoom - 1);
                    clampPan();
                    invalidate();
                }
                return true;
            }

            @Override
            public boolean onScroll(MotionEvent e1, MotionEvent e2, float dx, float dy) {
                if (zoom <= 1.01f) return false;
                panX -= dx;
                panY -= dy;
                clampPan();
                invalidate();
                return true;
            }
        });
    }

    void setListener(Listener l) {
        listener = l;
    }

    boolean zoomed() {
        return zoom > 1.01f;
    }

    void resetZoom() {
        zoom = 1f;
        panX = panY = 0;
        invalidate();
    }

    /** A bitmap the decoder may overwrite (not the one on screen), or null. */
    Bitmap spare() {
        synchronized (lock) {
            return spare;
        }
    }

    /** Show a freshly decoded picture; the previous one becomes the spare. */
    void show(Bitmap next) {
        synchronized (lock) {
            if (next != shown) {
                spare = shown;
                shown = next;
            }
        }
        postInvalidateOnAnimation();
    }

    int[] pictureSize() {
        synchronized (lock) {
            return shown == null ? null : new int[]{shown.getWidth(), shown.getHeight()};
        }
    }

    private float fit(Bitmap b) {
        return Math.min((float) getWidth() / b.getWidth(), (float) getHeight() / b.getHeight());
    }

    private void clampPan() {
        int[] size = pictureSize();
        if (size == null) return;
        float base = Math.min((float) getWidth() / size[0], (float) getHeight() / size[1]);
        float w = size[0] * base * zoom, h = size[1] * base * zoom;
        float maxX = Math.max(0, (w - getWidth()) / 2f), maxY = Math.max(0, (h - getHeight()) / 2f);
        panX = Math.max(-maxX, Math.min(maxX, panX));
        panY = Math.max(-maxY, Math.min(maxY, panY));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        synchronized (lock) {
            if (shown == null || getWidth() == 0) return;
            float s = fit(shown) * zoom;
            matrix.reset();
            matrix.postScale(s, s);
            matrix.postTranslate((getWidth() - shown.getWidth() * s) / 2f + panX,
                    (getHeight() - shown.getHeight() * s) / 2f + panY);
            canvas.drawBitmap(shown, matrix, paint);
        }
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        scaler.onTouchEvent(e);
        if (!scaler.isInProgress()) gestures.onTouchEvent(e);
        return true;
    }
}
