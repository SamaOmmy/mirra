package app.samantha.phone;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;

/** The few building blocks every screen uses, in the same colours as the Samantha window on the PC. */
final class Ui {
    private Ui() {}

    static final int BG = 0xff101218;
    static final int CARD = 0xff191c24;
    static final int LINE = 0xff2a2f3b;
    static final int TEXT = 0xffeceef4;
    static final int MUTED = 0xff9aa1b1;
    static final int ACCENT = 0xff8b6cff;
    static final int OK = 0xff34d399;
    static final int WARN = 0xfffbbf24;
    static final int BAD = 0xfff87171;

    static int dp(Context c, float value) {
        return Math.round(value * c.getResources().getDisplayMetrics().density);
    }

    static GradientDrawable round(Context c, int color, float radiusDp, int strokeColor) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(c, radiusDp));
        if (strokeColor != 0) d.setStroke(dp(c, 1), strokeColor);
        return d;
    }

    static TextView text(Context c, String s, float sp, int color, boolean bold) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setLineSpacing(0, 1.15f);
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        return t;
    }

    static Button button(Context c, String s, boolean primary, View.OnClickListener onClick) {
        Button b = new Button(c);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(15);
        b.setTextColor(primary ? 0xffffffff : TEXT);
        b.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        b.setBackground(round(c, primary ? ACCENT : LINE, 12, 0));
        b.setStateListAnimator(null);
        b.setPadding(dp(c, 18), dp(c, 12), dp(c, 18), dp(c, 12));
        b.setMinHeight(dp(c, 48));
        b.setOnClickListener(onClick);
        return b;
    }

    /** A rounded panel that stacks its children. */
    static LinearLayout card(Context c) {
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(round(c, CARD, 16, LINE));
        box.setPadding(dp(c, 18), dp(c, 16), dp(c, 18), dp(c, 18));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(c, 14);
        box.setLayoutParams(lp);
        return box;
    }

    static Switch toggle(Context c, String s, boolean on, CompoundButton.OnCheckedChangeListener listener) {
        Switch sw = new Switch(c);
        sw.setText(s);
        sw.setTextSize(15);
        sw.setTextColor(TEXT);
        sw.setChecked(on);
        int[][] states = {{android.R.attr.state_checked}, {}};
        sw.setThumbTintList(new ColorStateList(states, new int[]{ACCENT, 0xffc9cdd6}));
        sw.setTrackTintList(new ColorStateList(states, new int[]{0x998b6cff, 0xff3a3f4b}));
        sw.setPadding(0, dp(c, 10), 0, dp(c, 10));
        sw.setOnCheckedChangeListener(listener);
        return sw;
    }

    static View gap(Context c, int dp) {
        View v = new View(c);
        v.setLayoutParams(new LinearLayout.LayoutParams(1, dp(c, dp)));
        return v;
    }

    static LinearLayout row(Context c) {
        LinearLayout r = new LinearLayout(c);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER_VERTICAL);
        return r;
    }

    static LinearLayout.LayoutParams weight(float w) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -2, w);
        return lp;
    }
}
