import { useEffect, useState } from "react";

/**
 * Hearing the PC's sound on this phone. Off unless the person switches it on in Settings.
 * The choice is remembered on this phone only (it is a listening preference, not a PC setting).
 *
 * off        sound is switched off
 * connecting asking the PC for sound
 * playing    you should hear it
 * tap        the browser needs one tap on the page before it lets us play sound
 * error      the PC said no (see `error`)
 */
export type AudioStatus = "off" | "connecting" | "playing" | "tap" | "error";

export interface AudioPref {
  on: boolean;
  /** Mono at half the sample rate: a quarter of the data. */
  lowData: boolean;
}

const KEY = "sm.audio";
const CUSHION = 0.15;   // seconds of sound kept queued to ride out network jitter
const MAX_AHEAD = 0.6;  // more queued than this means we are behind: skip ahead instead of lagging
const MAX_BACKOFF = 15000;

export function loadAudioPref(): AudioPref {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "{}");
    return { on: v.on === true, lowData: v.lowData === true };
  } catch {
    return { on: false, lowData: false };
  }
}

export function saveAudioPref(pref: AudioPref) {
  try { localStorage.setItem(KEY, JSON.stringify(pref)); } catch { /* private mode: it just won't be remembered */ }
}

let ctx: AudioContext | null = null;

/** Create/resume the audio engine. Browsers only allow this from a tap or click, so call it from one. */
export function unlockAudio(): boolean {
  const Ctor: typeof AudioContext | undefined = window.AudioContext || (window as any).webkitAudioContext;
  if (!Ctor) return false;
  ctx ??= new Ctor({ latencyHint: "interactive" });
  if (ctx.state !== "running") void ctx.resume().catch(() => {});
  return true;
}

class Refused extends Error {
  constructor(message: string, readonly retry: boolean) { super(message); }
}

export function useAudio(pref: AudioPref) {
  const [status, setStatus] = useState<AudioStatus>("off");
  const [error, setError] = useState("");
  const { on, lowData } = pref;

  useEffect(() => {
    if (!on) { setStatus("off"); setError(""); return; }
    if (!unlockAudio() && !ctx) { setStatus("error"); setError("This browser can't play sound."); return; }

    let stopped = false;
    let abort: AbortController | null = null;
    let retryTimer = 0;
    let backoff = 1000;
    const audio = ctx!;

    let open = false; // true while the PC is sending sound
    const showState = () => { if (open) setStatus(audio.state === "running" ? "playing" : "tap"); };

    // Until the browser lets us play, wait for the next tap anywhere on the page.
    const tapEvents = ["pointerup", "touchend", "click", "keydown"];
    const onTap = () => { unlockAudio(); };
    tapEvents.forEach((t) => window.addEventListener(t, onTap, { capture: true, passive: true }));
    audio.addEventListener("statechange", showState);

    const play = async () => {
      if (stopped || document.hidden) return;
      abort = new AbortController();
      setStatus("connecting");
      try {
        const r = await fetch(`/api/audio?q=${lowData ? "low" : "normal"}`, {
          credentials: "same-origin", cache: "no-store", signal: abort.signal,
        });
        if (!r.ok || !r.body) {
          const body = await r.json().catch(() => ({}));
          throw new Refused(body.error ?? (r.status === 503 ? "Too many devices are listening." : `The PC answered ${r.status}.`),
            r.status !== 409);
        }
        const rate = Number(r.headers.get("X-Audio-Rate"));
        const channels = Number(r.headers.get("X-Audio-Channels"));
        if (!rate || !channels) throw new Refused("The PC sent sound in a format this app doesn't know.", false);
        setError("");
        open = true;
        showState();
        backoff = 1000;

        const reader = r.body.getReader();
        const frameBytes = 2 * channels;
        let rest = new Uint8Array(0);
        let next = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          let bytes = value;
          if (rest.length) { bytes = new Uint8Array(rest.length + value.length); bytes.set(rest); bytes.set(value, rest.length); }
          const usable = bytes.length - (bytes.length % frameBytes);
          rest = bytes.slice(usable);
          if (!usable || audio.state !== "running") continue; // not allowed to play yet: drop it rather than queue it

          const frames = usable / frameBytes;
          const view = new DataView(bytes.buffer, bytes.byteOffset, usable);
          const buffer = audio.createBuffer(channels, frames, rate);
          for (let c = 0; c < channels; c++) {
            const out = buffer.getChannelData(c);
            for (let i = 0; i < frames; i++) out[i] = view.getInt16((i * channels + c) * 2, true) / 32768;
          }
          const now = audio.currentTime;
          if (next < now + 0.02) next = now + CUSHION;   // first sound, or we ran dry: restart with a cushion
          else if (next > now + MAX_AHEAD) continue;      // too far behind: drop this piece
          const node = audio.createBufferSource();
          node.buffer = buffer;
          node.connect(audio.destination);
          node.start(next);
          next += buffer.duration;
        }
      } catch (e) {
        open = false;
        if (stopped || (e as Error).name === "AbortError") return;
        const refused = e instanceof Refused ? e : null;
        if (refused) { setStatus("error"); setError(refused.message); if (!refused.retry) return; }
      }
      open = false;
      if (stopped) return;
      retryTimer = window.setTimeout(play, backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF);
    };

    // Don't keep a sound connection open for a page nobody is looking at.
    const onVisibility = () => {
      if (document.hidden) { abort?.abort(); clearTimeout(retryTimer); setStatus("connecting"); }
      else { clearTimeout(retryTimer); play(); }
    };
    document.addEventListener("visibilitychange", onVisibility);
    play();

    return () => {
      stopped = true;
      abort?.abort();
      clearTimeout(retryTimer);
      document.removeEventListener("visibilitychange", onVisibility);
      audio.removeEventListener("statechange", showState);
      tapEvents.forEach((t) => window.removeEventListener(t, onTap, { capture: true } as EventListenerOptions));
    };
  }, [on, lowData]);

  return { status, error };
}
