# Samantha Screen Mirror

See your Windows PC screen live on your phone, from anywhere, privately. No accounts, no cloud, no port forwarding:
the picture goes straight from your PC to your phone through your own [Tailscale](https://tailscale.com) network.

## What is this for?

Samantha Screen Mirror lets you **look at your Windows PC's screen from your phone, wherever you are**. Typical uses:

- Check on a **long download, render, export, backup or install** without walking back to the desk
- Keep an eye on a **home or work PC** that is running something while you are out
- **Read something** on the big screen from the couch or another room (zoom in with two fingers)
- Quickly grab a **screenshot** of what the PC is showing

What it is **not**: it does not let you click or type on the PC (the PC is view-only on purpose, which makes it much
safer), it is not for sharing your screen with other people, and it is not a cloud service. Your screen goes
straight from your PC to your own phone through [Tailscale](https://tailscale.com), a free private network, and
nobody else (including this project) can see it.

## Features

- **Installable app** (PWA) with pinch-zoom, screenshots, quality presets and a screen picker
- **Fast**: up to **60 fps** (the *Smooth* preset) with GPU capture. Measured on a 60 Hz screen: 59.7 fps over the
  real stream at 1440x810, 16.8 ms median gap between frames. The default is 30 fps to be gentle on batteries and data.
- **Sound, if you want it**: hear the PC's sound on the phone. Off by default; each phone switches it on for itself
  in Settings, and the PC records nothing while nobody listens.
- **The other way round (Android)**: see your **phone on the PC** and use it with the mouse and keyboard, with a small
  companion app. No Developer options, no cable. See [Your phone on the PC](#your-phone-on-the-pc-android).
- **Private**: only reachable inside your tailnet, protected by a secret token. The PC is **view-only** from the phone
- **Easy setup**: one script installs everything and shows a QR code for your phone

<p align="center">
  <img src="docs/screenshots/login.png" width="230" alt="Sign-in screen">
  <img src="docs/screenshots/viewer.png" width="230" alt="Live view of the PC screen">
  <img src="docs/screenshots/settings.png" width="230" alt="Settings: presets, screen picker, sliders">
</p>

*(Screenshots use a demo picture, not a real desktop.)*

> Status: early. Windows only for now. You cannot control the PC from the phone; you can control an Android phone from the PC.

## Quick start

You need: a Windows 10/11 PC, a phone (Android or iPhone), and a free Tailscale account.
The phone needs **no download from us**: it uses the free Tailscale app plus this app in its browser
(installable to the home screen). Only the PC needs the installer below.

### Option A: download (no Python, no PowerShell)

1. Download `SamanthaScreenMirror-windows.zip` from the [Releases](../../releases) page and unzip it somewhere permanent.
2. Double-click `samantha-mirror.exe` and follow the prompts. (Windows may warn about an unrecognised app because
   the program is not code-signed: choose *More info > Run anyway*.)
3. Do step 3 below on your phone.

### Option B: from source

1. **Get the code** (or download the ZIP and unpack it):
   ```powershell
   git clone https://github.com/SamaOmmy/samantha-screen-mirror
   cd samantha-screen-mirror
   ```
2. **Run the installer** in PowerShell:
   ```powershell
   .\install.ps1
   ```
   It installs Python if needed (with your permission), then guides you through:
   Tailscale (offers to install it) -> your secret token -> optional HTTPS -> start-at-logon -> a **QR code**.
3. **On your phone** (both options): install the free Tailscale app, sign in with the *same account* as the PC, switch it on,
   then scan the QR code. You are looking at your PC. Use the browser menu to **Install app**.

From then on, just open the app on your phone. The server starts by itself when you log in to Windows.

**Lost the QR code, or signing in another phone?** On the **PC**: double-click `samantha-mirror.exe` again (Option A),
or in PowerShell run `.\.venv\Scripts\samantha-mirror link` from the project folder (Option B). It shows the QR code
again. Then scan it with the phone camera.

## Commands

All of these run **on the PC** (never on the phone). Open PowerShell (press the Windows key, type `PowerShell`, press
Enter), go to the program's folder, then:

- Option A (downloaded zip): `.\samantha-mirror.exe <command>`
- Option B (from source): `.\.venv\Scripts\samantha-mirror <command>`

For example `.\samantha-mirror.exe doctor`. Below, `samantha-mirror` stands for whichever of those you use.

| Command | What it does |
|---|---|
| `samantha-mirror setup` | Guided first-time setup (safe to run again) |
| `samantha-mirror link` | Show the phone link and QR code |
| `samantha-mirror doctor` | Check everything and say how to fix problems |
| `samantha-mirror run` | Start the server in this window (Ctrl+C stops it) |
| `samantha-mirror stop` | Stop the server and keep it stopped (also after a restart) |
| `samantha-mirror start` | Start it again and let it start at logon again |
| `samantha-mirror phone` | Open the page that shows your Android phone on this PC and lets you control it (see below) |
| `samantha-mirror autostart install/remove/status` | Start hidden at every Windows logon |
| `samantha-mirror update` | Check for and install a new version |
| `samantha-mirror uninstall` | Remove autostart and the HTTPS setup (keeps your settings) |

## How it works

```
phone (Tailscale app + browser/PWA)  --WireGuard-->  your PC: Samantha Screen Mirror
                                                        |- grabs the screen (DXGI GPU capture)
                                                        |- encodes JPEGs only when the picture changes
                                                        `- serves the app + stream, token required
```

- The server listens **only** on your Tailscale address (`100.x.y.z`); it refuses to start otherwise.
- Capture runs only while someone is watching.
- Optional HTTPS comes from `tailscale serve` (a Tailscale feature that stays inside your tailnet). It is what
  lets the phone offer a real **Install app**. Without it the app still works in the browser.

See [SECURITY.md](SECURITY.md) for the full threat model.

## Using the app

Tap the screen to show/hide the bars. Pinch to zoom, drag to pan, double-tap to reset.
**Settings** has presets (Data saver / Balanced / Sharp), a screen picker (multi-monitor), fps / quality /
resolution sliders and a pointer toggle. **Screenshot** saves a full-resolution PNG. The phone screen stays on while you watch.
**My PCs** (in Settings) bookmarks your other PCs so you can switch between them; each PC has its own address and
sign-in.

| Preset | Size | fps | Roughly (constant motion) |
|---|---|---|---|
| Data saver | 960x540 | 15 | 0.5 MB/s |
| Balanced (default) | 1440x810 | 30 | 3 MB/s |
| Sharp | 1920x1080 | 30 | 5 MB/s |
| Smooth | 1440x810 | 60 | 6 MB/s |

*Smooth* shows motion as it happens, but it sends twice the data, so use it on Wi-Fi, and an older phone may not
be able to draw 60 pictures a second (the fps shown at the top of the app tells you what your phone really gets).
A 60 Hz screen cannot show more than 60 fps; a faster screen is still captured at up to 60.

A still screen costs almost nothing because frames are only sent when something changes.

### Sound

**Settings > Sound > Hear this PC's sound on this phone.** It is off until you switch it on, it is remembered
per phone, and it is not a PC-wide setting, so one phone listening does not make another one listen. With it on, the
phone plays whatever the PC plays (the PC's own speakers keep playing too). The first time after opening the app your
browser may ask for one tap on the screen before it lets any page play sound. *Use less data (mono)* sends a quarter
of the data. Sound needs about 1.5 Mbit/s, and it can run a fraction of a second behind the picture,
so it is for listening, not for lip-sync. On an iPhone, the silent switch mutes it. The PC records nothing while
nobody listens. To forbid sound completely, set `SM_AUDIO=0` on the PC.

## Your phone on the PC (Android)

The other direction: **look at your Android phone on the PC and use it with the mouse and keyboard.** Click to tap,
hold to long-press, drag to swipe, scroll with the wheel, and type on the PC keyboard. It needs a small companion app,
**Samantha Phone**, on the phone. There is **no Developer mode, no USB debugging, no cable**, and nothing extra to
install on the PC. Android only (iPhones do not allow this), Android 11 or newer.

**Set it up once** (on the phone, in the Samantha app you already use):

1. **Settings > Use this phone from the PC > Download the app**, then open the downloaded file to install it. Android
   asks once to allow installs from your browser.
2. Tap **Pair this app**. It opens Samantha Phone and links it to this PC (the app stores your PC's address and token).
3. In Samantha Phone, tap **Open Accessibility settings**, choose **Samantha Phone** and switch it on. On Android 13 and
   newer the switch can be greyed out for apps installed outside the Play Store: open *App info*, tap the three dots,
   choose *Allow restricted settings*, then switch it on.

Then, on the PC, run `samantha-mirror phone` (or open the `/phone` page of your Samantha address). The phone shows up and
you control it with the mouse. Nothing is asked again after step 3: no "start recording" question, ever.

**Why Accessibility and not "screen recording"?** Android asks "Start recording your screen?" for every session and
does not let any app remember the answer (since Android 14 each recording needs a fresh yes). The Accessibility permission
is granted once and also includes taking screenshots, so the app uses that. The price is speed: Android allows a few
screenshots per second, so the picture is smoother than a slideshow but far from video. It is meant for operating the
phone, not for watching films on it.

**How it stays private**

- The phone app **connects out** to your PC through Tailscale, with your token. It never listens for connections, so
  nothing can reach into the phone.
- It does nothing until a page on the PC is open. While one is watching, Android shows a notification on the phone.
- In the app, **"Let the PC tap, swipe and type"** (on by default) and **Pause** are one switch away, and turning off the
  Accessibility switch stops everything. The PC page also has a **View only** box.
- Anyone who has your token can use this the same way you can, so keep it private (see [SECURITY.md](SECURITY.md)).

**Limits.** Banking apps and password prompts are blocked by Android and show black. A swipe is sent when you let go of the
mouse, not live while you drag. Typing works in normal text fields. The phone's sound does not come to the PC. Pairing
links the app to **one** PC; to change PCs, pair again.

## Settings file

Created by `setup`: `%APPDATA%\SamanthaScreenMirror\.env` (or the project folder when you run from a checkout;
set `SM_HOME` to use another folder). Defaults are shown below; you rarely need to touch them.

| Variable | Default | Meaning |
|---|---|---|
| `SM_TOKEN` | generated | Access secret, min 16 chars. **Keep private.** |
| `SM_PORT` | 8787 | Port on the Tailscale address |
| `SM_MONITOR` | 1 | Monitor to start with (0 = all combined) |
| `SM_FPS` | 30 | Max frames per second (1-60) |
| `SM_JPEG_QUALITY` | 70 | 10-95 |
| `SM_SCALE` | 0.75 | 0.1-1.0 size of the stream |
| `SM_MAX_CLIENTS` | 3 | Max simultaneous viewers |
| `SM_CURSOR` | 1 | Draw the mouse pointer on the stream |
| `SM_CAPTURE` | auto | `auto` (DXGI, falls back to mss), `dxgi`, or `mss` |
| `SM_UPDATE_CHECK` | 1 | Look for new releases on GitHub every 12 hours (only contacts api.github.com) |
| `SM_AUDIO` | 1 | Let phones listen to this PC's sound (each phone must also switch it on). `0` forbids it |
| `SM_LOOPBACK` | 0 | Also listen on 127.0.0.1 (set by `setup` when you enable HTTPS) |

The app's Settings sheet changes fps / quality / size / screen live (shared by all viewers; reset on restart).

## Updating

When a new version is released, the app shows **Update available** in Settings. On the PC:

```powershell
samantha-mirror update          # asks first; add -y to skip the question, --check to only look
```

It works for both install types: a git install fast-forwards to the new release and refreshes its packages; the
.exe download is fetched from the Releases page, verified against its SHA-256 checksum, and swapped in (your
settings and token are kept; a failed swap restores the old version). The server restarts by itself. Double-clicking
`samantha-mirror.exe` also offers the update. The PC checks GitHub every 12 hours; `SM_UPDATE_CHECK=0` turns that
off. Updates are only ever started on the PC, never from the phone.

**Updating from v0.4.0 or older (one time):** those versions cannot swap their own folder while a window is open
inside it. Run that one update from a different folder, for example in PowerShell:
`cd $HOME`, then run `samantha-mirror.exe update` using its full path (for example `& "D:\Apps\SamanthaScreenMirror\samantha-mirror.exe" update`).
From v0.4.1 on, it works from anywhere.

## Troubleshooting

Start with `samantha-mirror doctor`. Common causes:

- **Phone says "Can't reach your PC"**: Tailscale is off on the phone, or the PC is asleep / not signed in to Windows.
  Set Windows to never sleep while plugged in (Settings > System > Power).
- **"Your PC is reachable, but the mirror isn't running"**: the server isn't up. It starts at logon and retries by
  itself (and the start-at-logon task re-checks every 5 minutes), so wait a minute after a restart. If it
  persists, run `samantha-mirror doctor` and look at `samantha-mirror.log` in your settings folder.
- **"PC screen unavailable"**: the PC is locked or showing a secure prompt (UAC). It recovers when you unlock.
- **No "Install app" option**: you opened the plain `http://100.x...` address. Run `samantha-mirror setup`, enable
  HTTPS in your Tailscale admin console if asked, and use the `https://...ts.net` address.
- **Page does not load at all**: a Windows Firewall rule may be needed for the plain-HTTP address. In an
  Administrator PowerShell:
  ```powershell
  New-NetFirewallRule -DisplayName "Samantha Screen Mirror (Tailscale only)" -Direction Inbound `
    -Protocol TCP -LocalPort 8787 -RemoteAddress 100.64.0.0/10 -Action Allow
  ```
- **I want it off for now**: run `samantha-mirror stop` on the PC. Killing it in Task Manager only works until the
  next automatic check (within 5 minutes); `stop` keeps it off, `start` turns it back on.
- **Choppy on mobile data**: pick the *Data saver* preset.
- **No sound on the phone**: switch it on in Settings > Sound, then tap the screen once. Check the phone's volume
  and (iPhone) the silent switch. `samantha-mirror doctor` shows whether the PC can record its sound.
- **The phone page says "No phone is connected"**: on the phone, open Samantha Phone. It should say *Connected*. If it
  says Accessibility is off, switch it on (see *Set it up once*). If it can't reach the PC, check that Tailscale is on in
  the phone and that you paired with this PC's address. The phone app also stops when you set it to *Pause*.
- **The Accessibility switch is greyed out**: Android 13+ blocks it for apps installed from outside the Play Store until
  you open *App info*, tap the three dots and choose *Allow restricted settings*.

## Limitations

- Windows only (the capture and autostart code is Windows-specific). Ports to macOS/Linux are welcome.
- The PC is view-only from the phone **by design** (no remote control of the PC, now or later). Controlling an
  Android phone from the PC is the other direction and is separate (see above). iPhones can't be shown on the PC.
- Sound is raw uncompressed audio (no codec), so it needs Wi-Fi-like bandwidth, and its delay is roughly 0.2 to 0.3 seconds.
- The picture is a JPEG stream, not video. Unchanged frames cost nothing, so documents and desktops are very
  light; full-screen video or games over a slow connection will look choppy (use the *Data saver* preset).
  H.264 video was evaluated and left out on purpose: the good software encoder (x264) is GPL, which would change this
  project's MIT license for the downloadable build, and hardware encoders only exist on some GPUs.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Quick version: `pip install -e ".[dev]"`, then `ruff check .` and `pytest`.
The .exe download is built by CI when a version tag (e.g. `v0.3.0`) is pushed; locally:
`pip install pyinstaller` then `pyinstaller packaging/samantha.spec --noconfirm`.
The web app is React + Vite in `web/`; its build output in `samantha_mirror/web/` is committed.

```
samantha_mirror/
  cli.py        commands          wizard.py   guided setup + QR
  runner.py     start the server  doctor.py   health checks
  server.py     Flask routes      tailscale.py  find the address, HTTPS via tailscale serve
  capture.py    screen -> JPEG    autostart.py  Task Scheduler   updater.py   check/install releases
  auth.py       token + lockout   config.py     settings
  web/          built web app (from web/)
web/            React + TypeScript source
packaging/      PyInstaller spec for the Windows .exe download
tests/          pytest
```

## License

[MIT](LICENSE)
