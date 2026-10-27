package app.samantha.phone;

import android.content.Context;
import android.content.SharedPreferences;

/** What the app remembers: the PC it is paired with, and the switches. */
final class Prefs {
    private final SharedPreferences p;

    Prefs(Context context) {
        p = context.getApplicationContext().getSharedPreferences("samantha", Context.MODE_PRIVATE);
    }

    String server() { return p.getString("server", ""); }
    String token() { return p.getString("token", ""); }
    /** The PC's name as it told us when pairing (may be empty). */
    String pc() { return p.getString("pc", ""); }
    boolean paired() { return !server().isEmpty() && !token().isEmpty(); }
    /** May the PC tap, swipe and type? (Seeing the screen is separate: pause stops that too.) */
    boolean control() { return p.getBoolean("control", true); }
    boolean paused() { return p.getBoolean("paused", false); }
    /** Play the PC's sound while showing its screen. Off until switched on. */
    boolean sound() { return p.getBoolean("sound", false); }
    boolean lowData() { return p.getBoolean("low_data", false); }
    /** Show the PC upright instead of sideways. */
    boolean upright() { return p.getBoolean("upright", false); }

    void pair(String server, String token, String pc) {
        p.edit().putString("server", Net.normalize(server)).putString("token", token.trim())
                .putString("pc", pc == null ? "" : pc).apply();
    }

    void unpair() { p.edit().remove("server").remove("token").remove("pc").apply(); }
    void setPc(String pc) { if (pc != null && !pc.equals(pc())) p.edit().putString("pc", pc).apply(); }
    void setControl(boolean on) { p.edit().putBoolean("control", on).apply(); }
    void setPaused(boolean on) { p.edit().putBoolean("paused", on).apply(); }
    void setSound(boolean on) { p.edit().putBoolean("sound", on).apply(); }
    void setLowData(boolean on) { p.edit().putBoolean("low_data", on).apply(); }
    void setUpright(boolean on) { p.edit().putBoolean("upright", on).apply(); }

    /** A name for the PC to show: its own name, else its address. */
    String pcLabel() {
        if (!pc().isEmpty()) return pc();
        return Net.host(server());
    }
}
