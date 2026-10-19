import { useEffect, useState } from "react";
import { api, type PhoneState } from "./api";

/** Settings section for the reverse direction: seeing and controlling this (Android) phone from the PC. */
export default function PhoneSetup() {
  const [state, setState] = useState<PhoneState | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stopped = false;
    const load = () => api.phoneState().then((s) => { if (!stopped) setState(s); }).catch(() => {});
    load();
    const timer = window.setInterval(load, 3000);
    return () => { stopped = true; clearInterval(timer); };
  }, []);

  const pair = async () => {
    try {
      setError("");
      const { token } = await api.phonePair();
      location.href = `samanthaphone://pair?server=${encodeURIComponent(location.origin)}&token=${encodeURIComponent(token)}`;
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const android = /Android/i.test(navigator.userAgent);

  return (
    <section className="phone-setup">
      <label>Use this phone from the PC</label>
      <p className="muted small">
        Lets you see this phone on your PC and use it with the mouse and keyboard. Android only. One-time setup, no
        Developer options needed.
      </p>
      {!android && <p className="muted small">Open this screen on your Android phone to set it up.</p>}
      {state?.connected ? (
        <p className="ok-text">Connected: {state.device}. On the PC, open <code>{location.origin}/phone</code> or run <code>samantha-mirror phone</code>.</p>
      ) : (
        <ol className="steps small">
          <li>
            {state && !state.app_available ? (
              <span className="muted">This copy of Samantha does not include the phone app.</span>
            ) : (
              <a className="btn" href="/api/phone/app.apk">Download the app</a>
            )}{" "}
            Open the file to install it (Android asks you to allow installs from this browser, once).
          </li>
          <li><button disabled={!android} onClick={pair}>Pair this app</button> Opens the app and links it to this PC.</li>
          <li>In the app, tap <b>Open Accessibility settings</b>, choose <b>Samantha Phone</b> and switch it on.</li>
        </ol>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
