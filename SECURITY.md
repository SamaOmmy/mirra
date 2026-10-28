# Security

Mirra (formerly Samantha Screen Mirror) shows your PC screen on your phone, and your Android phone on your PC, so it is
built to be private by default.

## How it is protected

- **No cloud, no relay.** Traffic goes PC <-> phone inside your own [Tailscale](https://tailscale.com) network
  (WireGuard-encrypted). Nothing is exposed to the public internet. Do **not** use `tailscale funnel` with this app.
- **Network binding.** The server listens only on your Tailscale address (and, if you enable HTTPS, on `127.0.0.1`
  for Tailscale's proxy). It refuses to start if it cannot find an address in `100.64.0.0/10`. It never listens on
  `0.0.0.0` or your LAN address.
- **Access token.** Everything except the browser page's own static files needs a random secret token
  (`SM_TOKEN`, 32+ characters, generated for you). It is compared in constant time. 10 wrong attempts in 5 minutes
  lock that device out.
- **Pairing code.** The phone app gets the token by sending the 6-digit code that the Samantha window on the PC shows
  when you ask for one. A code works for 10 minutes, 5 wrong codes throw it away, and wrong codes count towards the
  same lockout as wrong tokens. Only someone who can see your PC screen (or who already has the token) can get a code.
- **Cookie.** After the first sign-in the token is stored in an `HttpOnly`, `SameSite=Strict` cookie.
- **View only.** There is no mouse, keyboard or file access to the PC from the phone.
- **Sound is opt-in.** Whoever has the token can ask the PC for its sound, like the screen, but nothing is recorded
  until someone does, and `SM_AUDIO=0` removes the feature.
- **Phone on the PC (Android).** The phone app connects **out** to your PC with your token and listens for nothing,
  so the phone has no open port. It stays idle until the Samantha window on the PC shows the phone, shows a
  notification while it does, and has a control switch and a pause switch. It uses Android's Accessibility permission,
  which you grant once and can revoke at any time in Android settings. It cannot see banking-app or password screens
  (Android blocks them).
- **Live phone link.** The phone's screen (H.264 video) and the touches for it go over a plain TCP port next to the
  web port (SM_PORT + 1), on the same addresses only, with the same token, the same lockout and a size limit on every
  message. It only forwards bytes between the phone and the Mirra window; nothing is decoded on the server.
- **Screen recording.** To send video, the phone app starts Android's screen recording each time the Mirra window on
  the PC shows the phone, and answers Android's "Start now?" question itself through its Accessibility permission (only
  during the few seconds after it asked). A notification shows while it records; it stops when the window closes.
- **Pairing page.** The QR code on the PC opens `/join` on the PC: a page without secrets (the code in its address came
  from the PC screen and runs out), and `/download/setup` serves Mirra Setup, which holds no secrets either.
- **App updates.** The phone app installs updates from this project's GitHub releases (over HTTPS; it checks that the
  file holds Mirra of the announced version), or else from the PC it is paired with (over the same token-protected
  connection). Either way Android checks that every update is signed with the same key as the installed app and asks
  you to confirm it.

## What you should know

- Anyone who has the token (for example from the QR code or link) can see your screen, and **if you paired an Android phone**,
  see and use it too. Do not share or post it.
  To rotate it, use **Settings > Sign out all phones** in the Samantha window; every phone must pair again.
- Anyone who can already run programs on your PC, or who has access to your Tailscale account, is outside what
  this app can protect against.
- The screen includes whatever is on it: passwords you type are visible while you type them, notifications
  included. Lock the PC or stop the server when you do not want to be viewed.
- Use Tailscale ACLs if your tailnet is shared with other people.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private
[security advisory](../../security/advisories/new) form for this repository, or contact the maintainer directly.
