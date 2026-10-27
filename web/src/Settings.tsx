import { useEffect, useRef, useState } from "react";
import { api, type MonitorsResponse, type ServerState, type Settings as S } from "./api";
import Devices from "./Devices";
import Help from "./Help";
import { unlockAudio, type AudioPref, type AudioStatus } from "./useAudio";

const PRESETS: { name: string; hint: string; values: Pick<S, "fps" | "quality" | "scale"> }[] = [
  { name: "Data saver", hint: "Mobile data", values: { fps: 15, quality: 50, scale: 0.5 } },
  { name: "Balanced", hint: "Default", values: { fps: 30, quality: 70, scale: 0.75 } },
  { name: "Sharp", hint: "Wi-Fi", values: { fps: 30, quality: 85, scale: 1 } },
  { name: "Smooth", hint: "60 fps, Wi-Fi", values: { fps: 60, quality: 65, scale: 0.75 } },
];

interface Props {
  onClose: () => void;
  onSignOut: () => void;
  current?: S;
  server?: ServerState | null;
  audio: AudioPref;
  audioStatus: AudioStatus;
  onAudio: (pref: AudioPref) => void;
}

export default function Settings({ onClose, onSignOut, current, server, audio, audioStatus, onAudio }: Props) {
  const [info, setInfo] = useState<MonitorsResponse | null>(null);
  const [s, setS] = useState<S | null>(current ?? null);
  const [error, setError] = useState("");
  const timer = useRef<number>(0);
  const pending = useRef<Partial<S>>({});

  useEffect(() => { api.monitors().then(setInfo).catch((e) => setError(e.message)); }, []);
  useEffect(() => { if (!s && current) setS(current); }, [current, s]);
  useEffect(() => () => clearTimeout(timer.current), []);

  // Send changes after a short pause so dragging a slider doesn't spam the server.
  function change(changes: Partial<S>) {
    setS((prev) => (prev ? { ...prev, ...changes } : prev));
    pending.current = { ...pending.current, ...changes };
    clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      const send = pending.current;
      pending.current = {};
      try {
        setError("");
        await api.settings(send);
      } catch (e) {
        setError((e as Error).message);
      }
    }, 250);
  }

  const preset = s && PRESETS.find((p) => p.values.fps === s.fps && p.values.quality === s.quality && p.values.scale === s.scale);

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label="Settings" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h2>Settings</h2>
          <button onClick={onClose}>Done</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {!s || !info ? <p className="muted">Loading…</p> : (
          <>
            <label>Quality preset</label>
            <div className="seg">
              {PRESETS.map((p) => (
                <button key={p.name} className={preset === p ? "on" : ""} onClick={() => change(p.values)}>
                  {p.name}<small>{p.hint}</small>
                </button>
              ))}
            </div>

            <label htmlFor="mon">Screen</label>
            <select id="mon" value={s.monitor} onChange={(e) => change({ monitor: Number(e.target.value) })}>
              {info.monitors.map((m) => <option key={m.index} value={m.index}>{m.label} ({m.width}×{m.height})</option>)}
            </select>

            <Slider label="Frame rate" unit=" fps" value={s.fps} range={info.limits.fps} step={1} onChange={(fps) => change({ fps })} />
            <Slider label="JPEG quality" unit="" value={s.quality} range={info.limits.quality} step={5} onChange={(quality) => change({ quality })} />
            <Slider label="Resolution" unit="%" value={Math.round(s.scale * 100)} range={[10, 100]} step={5} onChange={(v) => change({ scale: v / 100 })} />

            <label className="check">
              <input type="checkbox" checked={s.cursor} onChange={(e) => change({ cursor: e.target.checked })} />
              Show mouse pointer
            </label>
            <p className="muted small">These settings apply to everyone watching and reset when the server restarts.</p>

            <label>Sound</label>
            <label className="check">
              <input
                type="checkbox" checked={audio.on} disabled={server?.audio?.enabled === false}
                onChange={(e) => { if (e.target.checked) unlockAudio(); onAudio({ ...audio, on: e.target.checked }); }}
              />
              Hear this PC's sound on this phone
            </label>
            {audio.on && (
              <label className="check">
                <input type="checkbox" checked={audio.lowData} onChange={(e) => onAudio({ ...audio, lowData: e.target.checked })} />
                Use less data (mono)
              </label>
            )}
            <p className="muted small">
              {server?.audio?.enabled === false
                ? "Sound is switched off on the PC."
                : audio.on && audioStatus === "tap"
                  ? "Tap anywhere on the screen once to let your browser play sound."
                  : "Off by default. Only this phone is affected. Needs about 1.5 Mbit/s (a quarter of that with less data)."}
            </p>
          </>
        )}
        <Devices />
        {server?.update && (
          <p className="update-note">
            <strong>Update available: v{server.update.latest}.</strong> On your PC, run{" "}
            <code>samantha-mirror update</code> (or open the app there and choose Update).{" "}
            <a href={server.update.url} target="_blank" rel="noreferrer">What's new</a>
          </p>
        )}
        <Help compact />
        <p className="muted small about">
          Samantha Screen Mirror {server?.version ? `v${server.version}` : ""}
          {server?.capture ? ` · capture: ${server.capture}` : ""}
        </p>
        <button className="danger" onClick={onSignOut}>Forget this device</button>
      </div>
    </div>
  );
}

function Slider({ label, unit, value, range, step, onChange }: {
  label: string; unit: string; value: number; range: [number, number]; step: number; onChange: (v: number) => void;
}) {
  return (
    <>
      <label>{label}<span className="muted"> {value}{unit}</span></label>
      <input type="range" min={range[0]} max={range[1]} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </>
  );
}
