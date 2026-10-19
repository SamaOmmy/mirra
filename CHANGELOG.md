# Changelog

## Unreleased

New
- **Sound from the PC on the phone.** Off by default. Switch it on per phone in Settings > Sound; *Use less data*
  makes it mono at half the rate. The PC only records while someone listens; `SM_AUDIO=0` forbids it. Windows only
  (uses the speakers' loopback).
- **Your Android phone on the PC, with control.** A small companion app, *Samantha Phone*, lets the PC show the phone
  and tap, swipe and type on it. No Developer options and no cable: you install the app from your own PC's Samantha
  page, pair it and switch on one Accessibility permission, once. It uses Accessibility screenshots instead of screen
  recording, so Android never asks "start recording?" again (slower: a few pictures per second). The phone connects out
  to the PC and listens for nothing; the PC page is `/phone` (`samantha-mirror phone` opens it). The app is built with
  the plain Android SDK tools (`python android/build.py`) and ships inside the download.
- `doctor` reports on sound and on the phone app.

Changes
- The server now allows two streams per viewer (picture and sound), so up to `2 x SM_MAX_CLIENTS + 4` threads.

## 0.4.1

Fixes
- **Updating failed with "could not move the old version out of the way"** when `samantha-mirror update` was run from
  inside the program's folder (which is what the README says to do), and probably when double-clicking the exe.
  Windows will not rename a folder that a program has open as its current directory. The update now moves the
  folder's *contents* instead, so it works from anywhere, and still rolls back if anything goes wrong.
  Going from an older version to this one still uses the older swap, so run that one update from a different
  folder (see the README, "Updating"). Updates after that work from anywhere.

## 0.4.0

New
- **60 fps.** A *Smooth* preset (60 fps). The capture loop now keeps a fixed frame schedule on a high-resolution clock
  (it used a clock that only ticks every ~15 ms on Windows, so a 60 fps cap delivered about 50). Measured with a
  60 fps animation on screen: 59.7 fps over the real stream, 16.8 ms median and about 20 ms 95th-percentile gap
  between frames; a 30 fps cap now gives exactly 30.

Fixes
- An update could fail to swap folders because the task's 5-minute trigger relaunched the server mid-swap. The swap now
  disables the task while it works and puts it back as it found it (a server you stopped with `stop` stays stopped).

## 0.3.3

Fixes
- **Scanning the QR code sometimes still asked for the access token.** Once the app had been opened on a phone, its
  offline cache answered the page load before the PC could sign the phone in. Page loads now go to the PC first
  (the cache is only used when the PC cannot be reached), and the app also signs itself in from the link and
  removes the token from the address bar.
  After updating, open the app once on the phone (it refreshes itself), then scan again.

## 0.3.2

Fixes
- **Terminal windows flashing open and closed, over and over.** The server runs with no window, but every time it
  asked Tailscale, PowerShell or git something, Windows opened a console window for that helper. While Tailscale was
  off this happened every few seconds, and the 5-minute restart trigger kept relaunching the server. All helper
  programs now run fully hidden, and a test guards against new ones that are not.
- **The server kept coming back after being killed.** Waiting for Tailscale no longer ends the process (it waits
  quietly, however long that takes), so nothing is relaunched in a loop. A second copy now closes immediately
  instead of fighting the first, and the task no longer has its own extra restart rule.
- The log no longer fills with a "retrying" line every few seconds.

New
- `samantha-mirror stop` stops the server and keeps it stopped (also after a restart) until `samantha-mirror start`.
  `doctor` says when it was stopped on purpose.

## 0.3.1

Fixes
- **Server not running after a PC restart** (the phone said it could not reach the PC). At logon Tailscale can know
  its address before Windows has attached it to the network adapter; the server gave up instead of waiting.
  It now retries for up to 10 minutes, and a watchdog rebuilds the listener if it ever stops answering
  (for example after a Tailscale restart or update).
- The start-at-logon task now also checks every 5 minutes and starts the server if it is not running.
- Over HTTPS, one device's wrong tries could lock out every device, and the login cookie was not marked `Secure`
  (waitress discards `X-Forwarded-*` headers unless the proxy is trusted).
- The app now says *why* it cannot connect: "can't reach your PC" (Tailscale or network) versus "your PC is
  reachable but the mirror isn't running".

New
- `samantha-mirror update` (and `--check`): installs new releases from GitHub, for both the git install and the
  .exe download (checksum-verified, with rollback). The .exe asks on double-click when an update exists.
- The app shows "Update available" in Settings. The PC checks GitHub every 12 hours (`SM_UPDATE_CHECK=0` turns it off).
  Updating is started on the PC only, never from the phone.
- The app reloads itself once after an update installs a new version.
- `doctor` shows whether you are up to date.

## 0.3.0

- Renamed to **Samantha Screen Mirror**; Python package is now `samantha_mirror`, command is `samantha-mirror`.
- New command line: `setup` (guided first run), `link` (QR code + phone steps), `doctor` (health check),
  `autostart install|remove|status`, `uninstall`.
- `install.ps1` one-step installer.
- Settings and token live in `%APPDATA%\SamanthaScreenMirror` (or the project folder when run from a checkout; `SM_HOME` overrides).
- Optional HTTPS through `tailscale serve`, so the phone can install the app as a real PWA.
- Much faster capture: DXGI Desktop Duplication (fallback: mss) and OpenCV encoding.
  About 29 fps at 1440x810 and about 14 ms median latency in testing.
- React web app: login, pinch-zoom, live settings, screenshots, install help, keeps the phone awake while viewing,
  clear message when the PC cannot be reached.
- "My PCs" list in the app for switching between several PCs.
- Windows .exe build (PyInstaller) with a windowless service twin, built by a release workflow; double-clicking
  the exe runs the guided setup.
- Tests and CI.

## 0.1.0

- First view-only version: MJPEG stream over Tailscale with token auth.
