import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import Settings from "./Settings";
import { loadAudioPref, saveAudioPref, useAudio, type AudioPref } from "./useAudio";
import { useStream, type Status } from "./useStream";
import { useWakeLock } from "./useWakeLock";
import { useZoom } from "./useZoom";

const LABEL: Record<Status, string> = {
  connecting: "Connecting…",
  live: "Live",
  retrying: "Reconnecting…",
  "capture-error": "PC screen unavailable",
};

export default function Viewer({ onSignedOut }: { onSignedOut: () => void }) {
  const { src, status, server, fps, unreachable, onLoad, onError, reconnect } = useStream(onSignedOut);
  const [barVisible, setBarVisible] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const [audioPref, setAudioPref] = useState<AudioPref>(loadAudioPref);
  const audio = useAudio(audioPref);
  const changeAudio = useCallback((pref: AudioPref) => { saveAudioPref(pref); setAudioPref(pref); }, []);
  useWakeLock(status === "live");
  const zoom = useZoom(stage, () => setBarVisible((v) => !v));

  useEffect(() => {
    const onChange = () => setFullscreen(!!(document.fullscreenElement || (document as any).webkitFullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("webkitfullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("webkitfullscreenchange", onChange);
    };
  }, []);

  const toggleFullscreen = useCallback(async () => {
    const el: any = document.documentElement;
    const doc: any = document;
    if (fullscreen) return (doc.exitFullscreen || doc.webkitExitFullscreen).call(doc);
    const req = el.requestFullscreen || el.webkitRequestFullscreen;
    // iPhone Safari has no Fullscreen API for pages: hiding the bars is the best we can do.
    if (!req) return setBarVisible(false);
    try { await req.call(el); } catch { /* fall through to just hiding the bars */ }
    setBarVisible(false);
  }, [fullscreen]);

  const signOut = async () => {
    await api.logout().catch(() => {});
    onSignedOut();
  };

  const live = status === "live";
  const size = server && server.width ? `${server.width}×${server.height}` : "";

  return (
    <div className="viewer">
      <div ref={stage} className="stage">
        {src && (
          <img
            src={src} alt="Your PC screen" draggable={false}
            onLoad={onLoad} onError={onError}
            style={{ transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})` }}
          />
        )}
        {unreachable === "network" && (
          <div className="overlay">
            <strong>Can't reach your PC.</strong>
            <span className="muted">
              Check that Tailscale is switched on in this phone, and that the PC is on and awake.
              Retrying automatically.
            </span>
          </div>
        )}
        {unreachable === "server" && (
          <div className="overlay">
            <strong>Your PC is reachable, but the mirror isn't running on it.</strong>
            <span className="muted">
              It starts by itself when the PC signs in to Windows, so give it a minute after a restart.
              If it stays like this, run <code>samantha-mirror doctor</code> on the PC. Retrying automatically.
            </span>
          </div>
        )}
        {!unreachable && status === "capture-error" && (
          <div className="overlay">
            <strong>The PC screen can't be captured right now.</strong>
            <span className="muted">{server?.error || "It may be locked or showing a secure prompt."} Retrying automatically.</span>
          </div>
        )}
      </div>

      <header className={`bar top ${barVisible ? "" : "hidden"}`}>
        <span className={`dot ${live ? "ok" : status === "capture-error" ? "warn" : "bad"}`} />
        <span className="grow">
          {LABEL[status]}
          {live && <span className="muted"> · {fps} fps{size && ` · ${size}`}</span>}
          {audio.status === "playing" && <span className="muted"> · sound on</span>}
          {audio.status === "tap" && <span className="warn-text"> · tap the screen for sound</span>}
          {audio.status === "error" && <span className="warn-text"> · no sound: {audio.error}</span>}
        </span>
        {zoom.scale > 1 && <button onClick={zoom.reset}>Reset zoom</button>}
      </header>

      <footer className={`bar bottom ${barVisible ? "" : "hidden"}`}>
        <button onClick={() => setShowSettings(true)}>Settings{server?.update && <span className="badge" title="Update available" />}</button>
        <a className="btn" href="/api/screenshot" download="screenshot.png">Screenshot</a>
        <button onClick={reconnect}>Reconnect</button>
        <button onClick={toggleFullscreen}>{fullscreen ? "Exit full" : "Fullscreen"}</button>
      </footer>

      {showSettings && <Settings onClose={() => setShowSettings(false)} onSignOut={signOut} current={server?.settings} server={server}
        audio={audioPref} audioStatus={audio.status} onAudio={changeAudio} />}
    </div>
  );
}
