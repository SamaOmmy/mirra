# Changelog

## 0.6.4

- The project moved to **github.com/SamaOmmy/mirra**. Both apps now look for updates there (the old address
  forwards to it).

## 0.6.3

- **The phone app updates straight from GitHub**, like the PC: when a new version is published, Mirra on the phone
  shows the *Update available* pop-up by itself, even when the PC is off or not updated yet. (Before, the phone
  only got updates through the PC.) If GitHub can't be reached, it still takes the matching version from the PC.

## 0.6.2

New
- **Step-by-step guides that tick themselves off.** On the PC, Home walks through connecting a phone in four steps
  (Tailscale, scan the code, switch on, open the phone window); the right side shows only what to do now, and moves on
  by itself when Mirra sees a step done. On the phone, Mirra checks that Tailscale is installed and switched on and
  says exactly what is missing; turning on phone control has numbered steps; when the PC can't be reached it says why
  and offers to open Tailscale. Mirra Setup shows its two steps the same way. Settings on the PC has a short Help.
- **More responsive phone window**: a dot shows your touch at once, the mouse wheel scrolls exactly (no runaway
  fling), Ctrl + wheel pinches to zoom, typing goes out faster, steadier frame pacing (fine Windows timers), sharper
  default picture (10 Mbit/s), and a simpler toolbar (Back, Home, Recent apps, volume, screenshot, and More).
- The Mirra window only redraws what changed (no flicker, less CPU).

## 0.6.1

Fixes
- **Mirra Setup could not install Mirra** ("Could not install: Mirra.apk"): the app inside Setup was packed
  under its old name.

## 0.6.0: Mirra

Samantha Screen Mirror is now **Mirra**, with a new logo, a new look and much more.

New
- **The phone on the PC like the real thing**: its own phone-shaped window, **smooth video** (the phone's hardware
  H.264 encoder, up to 60 pictures a second, sharp up to the phone's full resolution) instead of 2 to 3 screenshots a
  second. The mouse is a **live finger** (drag, scroll, draw), right click is Back, middle click Home, Ctrl+V pastes,
  and a toolbar has Back, Home, Recent apps, Notifications, volume, lock, screenshot and picture quality. Android's
  "Start recording?" question is answered by the app itself, so nobody taps it; without recording, it falls back to
  screenshots. The video goes over a new live link on the next port (8788), with the same token and protection.
- **Connect a phone with one scan**: the QR code on the PC opens a page from your own PC that opens Mirra and
  connects it, or downloads Mirra Setup from the PC first. No typing, no GitHub.
- **Update pop-ups** in both apps when a new version is out (Update now / Later).
- **A Windows installer**, `Mirra-for-Windows-Setup.exe`: double-click, Next, done (per user, no admin rights).
- **New design** for both apps: the Mirra window (CustomTkinter: sidebar, cards, switches, segmented choices, Windows
  icons) and the Android app (gradient hero card, setting rows with icons, adaptive icon with Android 13 themed icon).
- Clear download names: `Mirra-for-Windows-Setup.exe`, `Mirra-for-Windows.zip`, `Mirra-for-Android-Setup.apk`.

Changes
- The window program is `Mirra.exe`; older shortcuts are pointed at it and renamed *Mirra*. Settings stay where they
  were. Older versions update through `SamanthaScreenMirror-windows.zip`, still published for them.

## 0.5.2

Fixes
- **"Restricted setting" on Android 13 and newer.** Android blocks the Accessibility switch for an app installed from a
  downloaded file, and many phones hide the "Allow restricted settings" option that should unblock it. The new
  **Samantha Setup** app installs Samantha through Android's installer, which Android does not restrict, so the switch
  simply works. The QR code in the Samantha window now downloads Setup. A copy of Samantha that was installed from a
  file says so and offers Setup; Setup removes that copy and installs it again (pair with the PC again afterwards).

## 0.5.1

Fixes
- **Updates no longer give up on a slow or flaky connection.** A download that stalls or drops is picked up again
  where it stopped (or restarted if the server can't resume), up to 12 times, instead of failing with "the read
  operation timed out". The checksum is still verified before anything is installed.

## 0.5.0

Two apps, both ways: **Samantha** on the PC and **Samantha** on Android.

New
- **The Samantha window on the PC** (`Samantha.exe`, the shortcuts open it). First-time setup, on/off, connecting a
  phone, seeing and using your Android phone, sound, signing out all phones and updates are all in one window. No
  console, no commands. Your old Desktop, Start Menu and pinned taskbar shortcuts are pointed at it automatically.
- **The Samantha app for Android** shows your PC (full screen, pinch to zoom, landscape with a Rotate button, quality
  presets, screen picker, screenshots) and plays the PC's sound if you switch it on. The same app lets the PC see and
  use the phone (one Accessibility permission, granted once; never a "start recording?" question). No browser needed.
- **Pairing with a code.** The Samantha window shows the PC's address and a 6-digit code (valid 10 minutes); type
  them into the phone app. No QR codes or tokens to copy.
- **Sound from the PC on the phone.** Off by default; each phone switches it on in its app. The PC records nothing
  while nobody listens, and Settings in the Samantha window can forbid it (`SM_AUDIO=0`).
- **Updates for both apps.** The window says when a new version is out and installs it with one click (then reopens).
  After the PC updates, the phone app offers the matching version from the PC; Android asks once to allow it.
- **Faster phone picture on the PC**: about 3 pictures a second instead of 2 (the upload of one overlaps taking the next).
- The Android app is also its own download on the Releases page (`SamanthaPhone.apk`).

Changes
- The browser page stays only for iPhones and other browsers (Settings > iPhone or a web browser in the window).
  Its Android setup section and the `/phone` page are gone, and so is `samantha-mirror phone`.
- Double-clicking `samantha-mirror.exe` opens the window. The command line still works for everything.
- `doctor` treats HTTPS as optional (only the iPhone browser page uses it) and reports the included Android app.
- The server allows two streams per viewer (picture and sound), so up to `2 x SM_MAX_CLIENTS + 4` threads.

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
