import { useState, type FormEvent } from "react";
import { api } from "./api";
import Help from "./Help";

export default function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(token.trim());
      onDone();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.startsWith("429")) setError("Too many wrong tries from this phone. Wait 5 minutes, then scan the QR code on your PC.");
      else if (msg === "Wrong token") setError("That token isn't right. Easiest fix: scan the QR code on your PC with this phone's camera.");
      else setError("Can't reach your PC. Check that Tailscale is switched on in this phone (see Need help? below).");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login" onSubmit={submit}>
      <img src="/icon-192.png" alt="" width={72} height={72} />
      <h1>Mirra</h1>
      <p className="muted">
        See your PC's screen on this phone. <strong>Easiest:</strong> scan the QR code shown by Mirra on
        your PC. Or paste the access token below. You only sign in once per device.
      </p>
      <input
        type="password" autoComplete="current-password" placeholder="Access token"
        value={token} onChange={(e) => setToken(e.target.value)} autoFocus
      />
      {error && <p className="error" role="alert">{error}</p>}
      <button type="submit" className="primary" disabled={busy || token.trim().length === 0}>
        {busy ? "Connecting…" : "Connect"}
      </button>
      <details className="more">
        <summary>Need help? Where do I find the QR code?</summary>
        <Help />
      </details>
    </form>
  );
}
