package app.samantha.phone;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;

/** Mirra's look on Android: the same colours as the Mirra window on the PC, and the few building blocks every screen uses. */
final class Ui {
    private Ui() {}

    static final int BG = 0xff0b0d12;
    static final int SURFACE = 0xff141721;
    static final int SURFACE2 = 0xff1c2030;
    static final int LINE = 0xff262b3a;
    static final int TEXT = 0xfff1f3f8;
    static final int MUTED = 0xff8e96a8;
    static final int ACCENT = 0xff7c5cff;
    static final int ACCENT2 = 0xff22d3ee;
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

    static GradientDrawable gradient(Context c, int from, int to, float radiusDp) {
        GradientDrawable d = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{from, to});
        d.setCornerRadius(dp(c, radiusDp));
        return d;
    }

    /** A pressed state that ripples. */
    static Drawable ripple(Drawable content, Drawable mask) {
        return new RippleDrawable(ColorStateList.valueOf(0x33ffffff), content, mask);
    }

    static TextView text(Context c, String s, float sp, int color, boolean bold) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setLineSpacing(0, 1.15f);
        t.setTypeface(Typeface.create(bold ? "sans-serif-medium" : "sans-serif", Typeface.NORMAL));
        return t;
    }

    static TextView title(Context c, String s) {
        TextView t = text(c, s, 18, TEXT, true);
        t.setPadding(0, 0, 0, dp(c, 4));
        return t;
    }

    /** The main action on a screen: a gradient pill. */
    static Button button(Context c, String s, boolean primary, View.OnClickListener onClick) {
        Button b = new Button(c);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(16);
        b.setTextColor(primary ? 0xffffffff : TEXT);
        b.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        Drawable bg = primary ? gradient(c, ACCENT, ACCENT2, 16) : round(c, SURFACE2, 16, LINE);
        b.setBackground(ripple(bg, round(c, 0xffffffff, 16, 0)));
        b.setStateListAnimator(null);
        b.setPadding(dp(c, 20), dp(c, 14), dp(c, 20), dp(c, 14));
        b.setMinHeight(dp(c, primary ? 56 : 50));
        b.setOnClickListener(onClick);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(c, 12);
        b.setLayoutParams(lp);
        return b;
    }

    /** A rounded panel that stacks its children. */
    static LinearLayout card(Context c) {
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(round(c, SURFACE, 22, LINE));
        box.setPadding(dp(c, 20), dp(c, 18), dp(c, 20), dp(c, 20));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(c, 14);
        box.setLayoutParams(lp);
        return box;
    }

    /** The big card at the top: a deep violet-to-teal gradient. */
    static LinearLayout hero(Context c) {
        LinearLayout box = card(c);
        box.setBackground(gradient(c, 0xff33238f, 0xff0c5566, 24));
        box.setPadding(dp(c, 22), dp(c, 22), dp(c, 22), dp(c, 22));
        return box;
    }

    static ImageView icon(Context c, int res, int tint, int sizeDp) {
        ImageView v = new ImageView(c);
        v.setImageResource(res);
        v.setImageTintList(ColorStateList.valueOf(tint));
        v.setLayoutParams(new LinearLayout.LayoutParams(dp(c, sizeDp), dp(c, sizeDp)));
        return v;
    }

    /** A setting: a tinted icon, a title with a line of explanation, and (optionally) a switch at the end. */
    static LinearLayout settingRow(Context c, int iconRes, String title, String detail, Switch toggle) {
        LinearLayout row = row(c);
        row.setPadding(0, dp(c, 10), 0, dp(c, 10));
        ImageView ic = icon(c, iconRes, ACCENT2, 22);
        LinearLayout badge = new LinearLayout(c);
        badge.setGravity(Gravity.CENTER);
        badge.setBackground(round(c, SURFACE2, 12, 0));
        badge.addView(ic);
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(dp(c, 42), dp(c, 42));
        blp.rightMargin = dp(c, 14);
        row.addView(badge, blp);
        LinearLayout texts = new LinearLayout(c);
        texts.setOrientation(LinearLayout.VERTICAL);
        texts.addView(text(c, title, 16, TEXT, true));
        if (detail != null) texts.addView(text(c, detail, 13, MUTED, false));
        row.addView(texts, weight(1));
        if (toggle != null) row.addView(toggle);
        return row;
    }

    static Switch toggle(Context c, boolean on, CompoundButton.OnCheckedChangeListener listener) {
        Switch sw = new Switch(c);
        sw.setChecked(on);
        int[][] states = {{android.R.attr.state_checked}, {}};
        sw.setThumbTintList(new ColorStateList(states, new int[]{0xffffffff, 0xffc9cdd6}));
        sw.setTrackTintList(new ColorStateList(states, new int[]{ACCENT, 0xff3a3f4b}));
        sw.setOnCheckedChangeListener(listener);
        return sw;
    }

    /** A small rounded label with a coloured dot, e.g. "Online". */
    static TextView chip(Context c, String s, int color) {
        TextView t = text(c, "●  " + s, 13, color, true);
        t.setBackground(round(c, 0x26ffffff, 50, 0));
        t.setPadding(dp(c, 12), dp(c, 5), dp(c, 12), dp(c, 5));
        return t;
    }

    static View gap(Context c, int dp) {
        View v = new View(c);
        v.setLayoutParams(new LinearLayout.LayoutParams(1, dp(c, dp)));
        return v;
    }

    static View divider(Context c) {
        View v = new View(c);
        v.setBackgroundColor(LINE);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, Math.max(1, dp(c, 1)));
        lp.topMargin = dp(c, 4);
        lp.bottomMargin = dp(c, 4);
        v.setLayoutParams(lp);
        return v;
    }

    static LinearLayout row(Context c) {
        LinearLayout r = new LinearLayout(c);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER_VERTICAL);
        return r;
    }

    static LinearLayout.LayoutParams weight(float w) {
        return new LinearLayout.LayoutParams(0, -2, w);
    }

    /** Old name kept for the viewer: a plain on/off switch with a label. */
    static Switch toggle(Context c, String s, boolean on, CompoundButton.OnCheckedChangeListener listener) {
        Switch sw = toggle(c, on, listener);
        sw.setText(s);
        sw.setTextSize(15);
        sw.setTextColor(TEXT);
        sw.setPadding(0, dp(c, 10), 0, dp(c, 10));
        return sw;
    }
}
