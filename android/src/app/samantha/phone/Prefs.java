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
    /** Share this screen as smooth video (screen recording) rather than a few screenshots a second. */
    boolean video() { return p.getBoolean("video", true); }
    /** Video quality the PC asked for: the long side in pixels (0 = the full screen), bits per second, frames. */
    int maxSize() { return p.getInt("max_size", 1920); }
    int bitrate() { return p.getInt("bitrate", 8_000_000); }
    int fps() { return p.getInt("fps", 60); }

    /** The PC's live link port: what it told us, else its web port + 1. */
    int relayPort(String base) {
        int port = p.getInt("relay_port", 0);
        return port > 0 ? port : Link.defaultPort(base);
    }

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
    void setVideo(boolean on) { p.edit().putBoolean("video", on).apply(); }
    void setRelayPort(int port) { if (port > 0 && port != p.getInt("relay_port", 0)) p.edit().putInt("relay_port", port).apply(); }

    void setQuality(int maxSize, int bitrate, int fps) {
        p.edit().putInt("max_size", Math.max(0, Math.min(4096, maxSize)))
                .putInt("bitrate", Math.max(500_000, Math.min(40_000_000, bitrate)))
                .putInt("fps", Math.max(10, Math.min(120, fps))).apply();
    }

    /** A name for the PC to show: its own name, else its address. */
    String pcLabel() {
        if (!pc().isEmpty()) return pc();
        return Net.host(server());
    }
}
