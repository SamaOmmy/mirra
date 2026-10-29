package app.samantha.phone;

import android.app.Activity;
import android.content.Context;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowInsetsController;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;

/** Mirra's look on Android: the same colours as the Mirra window on the PC, and the few building blocks every screen uses. */
final class Ui {
    private Ui() {}

    // The palette of the current look (light or dark), set by theme() before a screen is built.
    static int BG, SURFACE, SURFACE2, LINE, TEXT, MUTED, ACCENT, ACCENT2, OK, WARN, BAD, RIPPLE, TRACK_OFF, THUMB_OFF;
    static boolean dark;

    static {
        palette(true);
    }

    /** Light or dark: the choice under Appearance in Mirra, else the phone's own setting. Call before building views. */
    static void theme(Activity a) {
        String choice = new Prefs(a).theme();
        boolean night = (a.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        palette(choice.equals("dark") || (!choice.equals("light") && night));
        Window w = a.getWindow();
        w.getDecorView().setBackgroundColor(BG);
        w.setStatusBarColor(BG);
        w.setNavigationBarColor(BG);
        int light = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
        WindowInsetsController bars = w.getInsetsController();
        if (bars != null) bars.setSystemBarsAppearance(dark ? 0 : light, light);
    }

    /** The dark look whatever the setting (the full-screen PC view, which is dark like a video player). */
    static void forceDark() {
        palette(true);
    }

    private static void palette(boolean night) {
        dark = night;
        BG = night ? 0xff0b0d12 : 0xfff5f6fa;
        SURFACE = night ? 0xff141721 : 0xffffffff;
        SURFACE2 = night ? 0xff1c2030 : 0xffeef0f7;
        LINE = night ? 0xff262b3a : 0xffdde1eb;
        TEXT = night ? 0xfff1f3f8 : 0xff151926;
        MUTED = night ? 0xff8e96a8 : 0xff5c6477;
        ACCENT = night ? 0xff7c5cff : 0xff6a4cf5;
        ACCENT2 = night ? 0xff22d3ee : 0xff0b8ea6;
        OK = night ? 0xff34d399 : 0xff0f9b6c;
        WARN = night ? 0xfffbbf24 : 0xffb4690e;
        BAD = night ? 0xfff87171 : 0xffd92d2d;
        RIPPLE = night ? 0x33ffffff : 0x1f000000;
        TRACK_OFF = night ? 0xff3a3f4b : 0xffc9cdd8;
        THUMB_OFF = night ? 0xffc9cdd6 : 0xffffffff;
    }

    /** Pop-ups in the same look. */
    static int dialog() {
        return dark ? android.R.style.Theme_DeviceDefault_Dialog_Alert : android.R.style.Theme_DeviceDefault_Light_Dialog_Alert;
    }

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
        return new RippleDrawable(ColorStateList.valueOf(RIPPLE), content, mask);
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
        sw.setThumbTintList(new ColorStateList(states, new int[]{0xffffffff, THUMB_OFF}));
        sw.setTrackTintList(new ColorStateList(states, new int[]{ACCENT, TRACK_OFF}));
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
