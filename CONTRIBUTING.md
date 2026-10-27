# Contributing

Thanks for helping! This is a small project; keep changes focused.

## Setup

```powershell
git clone <your fork>
cd samantha-screen-mirror
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Checks (CI runs the same)

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
cd web; npm ci; npm run build     # only if you changed the web app
```

## The browser page (iPhone)

Source is in `web/` (React + TypeScript + Vite). `npm run build` writes into `samantha_mirror/web/`, which **is
committed** so end users do not need Node. If you change `web/`, rebuild and commit the result; CI fails if
the built files are out of date.

Live reload against a running server: `$env:SM_TARGET="http://<tailscale-ip>:8787"; npm run dev`.

## The PC window and the Android app

- The Samantha window is `samantha_mirror/desktop.py` (Tkinter, part of Python). Run it with
  `.\.venv\Scripts\python.exe -m samantha_mirror app`.
- The Android app is plain Java in `android/`, built without Gradle by `python android/build.py` (needs a JDK 17+
  and the Android SDK). `tests/test_android.py` builds it and runs its networking code against a real server on the
  PC's JVM; it is skipped when the tools are missing.

## Guidelines

- Security first: do not weaken the Tailscale-only binding or token checks. Add a test for any change to auth,
  routing or the network address logic.
- The PC is **view-only from the phone by design**. Pull requests that add remote control of the PC (mouse, keyboard,
  file access) will not be accepted. (Controlling the Android phone from the PC is the other direction and is fine.)
- The setup wizard should stay safe to re-run and must never overwrite another app's Tailscale Serve entry.
- Never commit `.env`, tokens, or screenshots of a real desktop.

## Ideas that would help

macOS/Linux capture backends, video encoding for smoother motion, translations.
