import { useInstall } from "./useInstall";

const PLAY = "https://play.google.com/store/apps/details?id=com.tailscale.ipn";
const APPLE = "https://apps.apple.com/app/tailscale/id1470499037";

/** Plain-language help, used on the sign-in screen (full) and in Settings (compact). */
export default function Help({ compact = false }: { compact?: boolean }) {
  const inst = useInstall();
  return (
    <div className="help">
      {!compact && (
        <>
          <h3>How do I sign in?</h3>
          <p className="muted">
            <strong>Android phone?</strong> Use the Samantha app instead of this page: on your PC, open Samantha. Its
            Home page has the download and a code to connect.
          </p>
          <p className="muted">On an iPhone or in another browser, the sign-in code lives on the PC:</p>
          <ol>
            <li>
              <strong>On your PC</strong>, open <strong>Samantha</strong>, go to <strong>Settings</strong> and choose{" "}
              <strong>Show the link</strong> (under <em>iPhone or a web browser</em>). It shows a <strong>QR code</strong>.
            </li>
            <li>
              <strong>On this phone</strong>, open the camera and point it at the QR code on the PC screen. Tap the link
              that appears. You are signed in. (No camera? Type the token from the <code>.env</code> file instead.)
            </li>
          </ol>

          <h3>"Can't reach your PC"?</h3>
          <ul>
            <li>
              This phone needs the free <strong>Tailscale</strong> app, <strong>signed in to the same account as the PC</strong>
              {" "}and switched <strong>on</strong>:{" "}
              <a href={PLAY} target="_blank" rel="noreferrer">Android</a> · <a href={APPLE} target="_blank" rel="noreferrer">iPhone</a>
            </li>
            <li>The PC must be switched on, awake and signed in to Windows (not asleep or at the lock screen).</li>
            <li>Still stuck? On the PC run <code>samantha-mirror doctor</code>. It checks everything and tells you the fix.</li>
          </ul>
        </>
      )}
      <h3>Install as an app</h3>
      {inst.installed ? (
        <p className="muted">You are using the installed app.</p>
      ) : inst.canPrompt ? (
        <button className="primary" onClick={inst.install}>Install app</button>
      ) : inst.ios ? (
        <p className="muted">In Safari, tap the Share button, then <strong>Add to Home Screen</strong>.</p>
      ) : !inst.secure ? (
        <p className="muted">
          Your browser only offers a full install over HTTPS. On the PC, run <code>samantha-mirror setup</code> and say yes
          to HTTPS, then open the PC's <code>https://…ts.net</code> address on this phone. Until then you can still use the
          browser menu → <strong>Add to Home screen</strong>.
        </p>
      ) : (
        <p className="muted">Use the browser menu → <strong>Install app</strong> or <strong>Add to Home screen</strong>.</p>
      )}
    </div>
  );
}
