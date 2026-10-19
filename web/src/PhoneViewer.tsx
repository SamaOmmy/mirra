import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { api, Unauthorized, type PhoneInput, type PhoneState } from "./api";

const POLL_MS = 1500;
const TAP_MOVE_PX = 8;      // moving less than this while pressed is a tap, not a swipe
const LONG_PRESS_MS = 500;
const MAX_POINTS = 40;

type Point = [number, number];

/** Where a pointer is on the phone's picture, as fractions 0..1, or null when it is outside the picture. */
function toUnit(img: HTMLImageElement, clientX: number, clientY: number): Point | null {
  const box = img.getBoundingClientRect();
  if (!img.naturalWidth || !img.naturalHeight || !box.width || !box.height) return null;
  // The picture is letterboxed inside the element (object-fit: contain): find the part that is drawn.
  const scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight);
  const w = img.naturalWidth * scale;
  const h = img.naturalHeight * scale;
  const x = (clientX - (box.left + (box.width - w) / 2)) / w;
  const y = (clientY - (box.top + (box.height - h) / 2)) / h;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return [x, y];
}

function thin(points: Point[]): Point[] {
  if (points.length <= MAX_POINTS) return points;
  const step = (points.length - 1) / (MAX_POINTS - 1);
  return Array.from({ length: MAX_POINTS }, (_, i) => points[Math.round(i * step)]);
}

export default function PhoneViewer({ onSignedOut }: { onSignedOut: () => void }) {
  const [state, setState] = useState<PhoneState | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [error, setError] = useState("");
  const [viewOnly, setViewOnly] = useState(false);
  const [streamKey, setStreamKey] = useState(0);
  const [dot, setDot] = useState<{ x: number; y: number } | null>(null);
  const [typed, setTyped] = useState("");
  const img = useRef<HTMLImageElement>(null);
  const press = useRef<{ id: number; at: number; from: Point; path: Point[]; startPx: [number, number] } | null>(null);
  const wheel = useRef<{ x: number; y: number; dy: number; timer: number } | null>(null);
  const pendingText = useRef({ text: "", timer: 0 });
  const lastSeq = useRef({ seq: -1, at: 0 });
  const [fps, setFps] = useState(0);

  const send = useCallback(async (event: PhoneInput) => {
    try {
      setError("");
      await api.phoneInput(event);
    } catch (e) {
      if (e instanceof Unauthorized) onSignedOut();
      else setError((e as Error).message);
    }
  }, [onSignedOut]);

  useEffect(() => {
    let stopped = false;
    const poll = async () => {
      try {
        const s = await api.phoneState();
        if (stopped) return;
        setUnreachable(false);
        setState(s);
        const now = performance.now();
        const last = lastSeq.current;
        if (last.at && s.seq !== last.seq) setFps(Math.round(((s.seq - last.seq) * 1000) / (now - last.at)));
        else if (last.at) setFps(0);
        lastSeq.current = { seq: s.seq, at: now };
      } catch (e) {
        if (e instanceof Unauthorized) onSignedOut();
        else if (!stopped) setUnreachable(true);
      }
    };
    poll();
    const timer = window.setInterval(poll, POLL_MS);
    return () => { stopped = true; clearInterval(timer); };
  }, [onSignedOut]);

  // The picture stream only exists while a phone is connected; a new connection means a new stream.
  const connected = !!state?.connected;
  useEffect(() => { if (connected) setStreamKey((k) => k + 1); }, [connected]);

  const canControl = connected && !!state?.control && !viewOnly;

  // -- mouse -------------------------------------------------------------------------------
  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!canControl || !img.current || e.button !== 0) return;
    const at = toUnit(img.current, e.clientX, e.clientY);
    if (!at) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    e.currentTarget.focus();
    press.current = { id: e.pointerId, at: performance.now(), from: at, path: [at], startPx: [e.clientX, e.clientY] };
    setDot({ x: e.clientX, y: e.clientY });
  };

  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const p = press.current;
    if (!p || p.id !== e.pointerId || !img.current) return;
    const at = toUnit(img.current, e.clientX, e.clientY);
    if (at) p.path.push(at);
    setDot({ x: e.clientX, y: e.clientY });
  };

  const onUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const p = press.current;
    if (!p || p.id !== e.pointerId) return;
    press.current = null;
    setDot(null);
    const held = performance.now() - p.at;
    const moved = Math.hypot(e.clientX - p.startPx[0], e.clientY - p.startPx[1]);
    if (moved < TAP_MOVE_PX) {
      send({ t: held >= LONG_PRESS_MS ? "long" : "tap", x: p.from[0], y: p.from[1] });
    } else if (p.path.length >= 2) {
      send({ t: "gesture", pts: thin(p.path), ms: Math.round(Math.min(3000, Math.max(80, held))) });
    }
  };

  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (!canControl || !img.current) return;
    const at = toUnit(img.current, e.clientX, e.clientY);
    if (!at) return;
    const w = wheel.current;
    if (w) { w.dy += e.deltaY; return; }
    // Collect the wheel turns of the next 80 ms into one swipe: scrolling down swipes the finger up.
    const entry = { x: at[0], y: at[1], dy: e.deltaY, timer: 0 };
    entry.timer = window.setTimeout(() => {
      wheel.current = null;
      const travel = Math.max(-0.5, Math.min(0.5, entry.dy / 600));
      const endY = Math.max(0.02, Math.min(0.98, entry.y - travel));
      if (Math.abs(endY - entry.y) > 0.01) send({ t: "gesture", pts: [[entry.x, entry.y], [entry.x, endY]], ms: 200 });
    }, 80);
    wheel.current = entry;
  };

  // -- keyboard ----------------------------------------------------------------------------
  const flushText = useCallback(() => {
    const pending = pendingText.current;
    clearTimeout(pending.timer);
    if (pending.text) send({ t: "text", s: pending.text });
    pending.text = "";
  }, [send]);

  const queueText = useCallback((text: string) => {
    const pending = pendingText.current;
    pending.text += text;
    clearTimeout(pending.timer);
    pending.timer = window.setTimeout(flushText, 120);
  }, [flushText]);

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!canControl) return;
    if (e.key === "Escape") { send({ t: "key", k: "back" }); e.preventDefault(); return; }
    if (e.key === "Enter") { queueText("\n"); e.preventDefault(); return; }
    if (e.key === "Backspace") { queueText("\b"); e.preventDefault(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") {
      navigator.clipboard?.readText().then((t) => { if (t) queueText(t.slice(0, 500)); }).catch(() => {});
      e.preventDefault();
      return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { queueText(e.key); e.preventDefault(); }
  };

  const sendTyped = () => {
    if (!typed) return;
    send({ t: "text", s: typed.slice(0, 500) });
    setTyped("");
  };

  // -- what to say -------------------------------------------------------------------------
  let overlay: React.ReactNode = null;
  if (unreachable) {
    overlay = <><strong>Can't reach the Samantha server.</strong><span className="muted">Retrying automatically.</span></>;
  } else if (state && !connected) {
    overlay = (
      <>
        <strong>No phone is connected.</strong>
        <span className="muted">
          On your Android phone: open Samantha, go to <b>Settings &gt; Use this phone from the PC</b> and follow the three
          steps (install the app, pair it, switch on Accessibility). You only do that once.
          {state.app_available ? "" : " This copy of Samantha does not include the phone app yet."}
        </span>
      </>
    );
  } else if (state && connected && state.frame_age === null) {
    overlay = <><strong>Connected to {state.device}.</strong><span className="muted">Waiting for the first picture…</span></>;
  }

  return (
    <div className="phone-page">
      <header className="phone-bar">
        <span className={`dot ${connected ? "ok" : "bad"}`} />
        <span className="grow">
          {connected ? state?.device || "Phone" : "Phone"}
          {connected && <span className="muted"> · {fps} fps · app {state?.app_version}</span>}
          {connected && !state?.control && <span className="warn-text"> · view only: control is off in the phone app</span>}
        </span>
        <label className="check inline">
          <input type="checkbox" checked={viewOnly} onChange={(e) => setViewOnly(e.target.checked)} />
          View only
        </label>
        <a className="btn" href="/">PC screen on phone</a>
      </header>

      <div className="phone-body">
        <div
          className={`phone-stage ${canControl ? "live" : ""}`}
          tabIndex={0}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
          onWheel={onWheel} onKeyDown={onKey}
          aria-label="Your phone's screen. Click to tap, drag to swipe, type to enter text."
        >
          {connected && (
            <img ref={img} key={streamKey} src={`/api/phone/stream?t=${streamKey}`} alt="Your phone's screen" draggable={false}
                 onError={() => window.setTimeout(() => setStreamKey((k) => k + 1), 2000)} />
          )}
          {dot && <span className="touch-dot" style={{ left: dot.x, top: dot.y }} />}
          {overlay && <div className="overlay center-overlay">{overlay}</div>}
        </div>

        <aside className="phone-keys">
          <button disabled={!canControl} onClick={() => send({ t: "key", k: "back" })} title="Back (Esc)">◀ Back</button>
          <button disabled={!canControl} onClick={() => send({ t: "key", k: "home" })}>● Home</button>
          <button disabled={!canControl} onClick={() => send({ t: "key", k: "recents" })}>▢ Apps</button>
          <button disabled={!canControl} onClick={() => send({ t: "key", k: "notifications" })}>Notifications</button>
          <button disabled={!canControl} onClick={() => send({ t: "key", k: "quicksettings" })}>Quick settings</button>
          <button disabled={!canControl} onClick={() => send({ t: "key", k: "wake" })}>Wake screen</button>
          <form className="type-box" onSubmit={(e) => { e.preventDefault(); sendTyped(); }}>
            <input
              value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type or paste text for the phone"
              disabled={!canControl} maxLength={500} aria-label="Text to type on the phone"
            />
            <button disabled={!canControl || !typed}>Send</button>
          </form>
          <p className="muted small">
            Click to tap, hold to long-press, drag to swipe, scroll with the wheel. Click the picture, then type on your
            keyboard to type on the phone. Esc is Back.
          </p>
          {error && <p className="error" role="alert">{error}</p>}
        </aside>
      </div>
    </div>
  );
}
