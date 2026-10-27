import { useEffect, useState } from "react";
import { api, Unauthorized } from "./api";
import Login from "./Login";
import Viewer from "./Viewer";

type Auth = "checking" | "in" | "out";

// The QR code opens /?token=... The server normally signs us in and redirects, but a cached copy of this
// page (service worker) can answer first and skip that. So the app also signs in from the link itself, once,
// and takes the token out of the address bar so it isn't left in the history.
const linkToken = new URLSearchParams(location.search).get("token");
if (linkToken) history.replaceState(null, "", location.pathname);
const signedInFromLink: Promise<unknown> = linkToken ? api.login(linkToken).catch(() => {}) : Promise.resolve();

export default function App() {
  const [auth, setAuth] = useState<Auth>("checking");

  useEffect(() => {
    signedInFromLink.then(() => api.state()).then(() => setAuth("in")).catch((e) => setAuth(e instanceof Unauthorized ? "out" : "in"));
  }, []);

  if (auth === "checking") return <div className="center muted">Loading…</div>;
  if (auth === "out") return <Login onDone={() => setAuth("in")} />;
  return <Viewer onSignedOut={() => setAuth("out")} />;
}
