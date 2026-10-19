package app.samantha.phone;

import android.content.Context;
import android.content.SharedPreferences;

/** What the app remembers: which PC it is paired with, and the two switches. */
final class Prefs {
    private final SharedPreferences p;

    Prefs(Context context) {
        p = context.getApplicationContext().getSharedPreferences("samantha", Context.MODE_PRIVATE);
    }

    String server() { return p.getString("server", ""); }
    String token() { return p.getString("token", ""); }
    boolean paired() { return !server().isEmpty() && !token().isEmpty(); }
    /** May the PC tap, swipe and type? (Seeing the screen is separate: pause stops that too.) */
    boolean control() { return p.getBoolean("control", true); }
    boolean paused() { return p.getBoolean("paused", false); }

    void pair(String server, String token) {
        p.edit().putString("server", normalize(server)).putString("token", token.trim()).apply();
    }

    void unpair() { p.edit().remove("server").remove("token").apply(); }
    void setControl(boolean on) { p.edit().putBoolean("control", on).apply(); }
    void setPaused(boolean on) { p.edit().putBoolean("paused", on).apply(); }

    /** "100.64.0.5:8787" becomes "http://100.64.0.5:8787"; trailing slashes go. */
    static String normalize(String server) {
        String s = server.trim();
        if (s.isEmpty()) return s;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }
}
