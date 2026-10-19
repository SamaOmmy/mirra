# Security

Samantha Screen Mirror shows your PC screen to another device, so it is built to be private by default.

## How it is protected

- **No cloud, no relay.** Traffic goes PC <-> phone inside your own [Tailscale](https://tailscale.com) network
  (WireGuard-encrypted). Nothing is exposed to the public internet. Do **not** use `tailscale funnel` with this app.
- **Network binding.** The server listens only on your Tailscale address (and, if you enable HTTPS, on `127.0.0.1`
  for Tailscale's proxy). It refuses to start if it cannot find an address in `100.64.0.0/10`. It never listens on
  `0.0.0.0` or your LAN address.
- **Access token.** Everything except the app's own static files needs a random secret token
  (`SM_TOKEN`, 32+ characters, generated for you). It is compared in constant time. 10 wrong attempts in 5 minutes
  lock that device out.
- **Cookie.** After the first sign-in the token is stored in an `HttpOnly`, `SameSite=Strict` cookie.
- **View only.** There is no mouse, keyboard or file access to the PC from the phone.
- **Sound is opt-in.** Whoever has the token can ask the PC for its sound, like the screen, but nothing is recorded
  until someone does, and `SM_AUDIO=0` removes the feature.
- **Phone on the PC (Android).** The companion app connects **out** to your PC with your token and listens for nothing,
  so the phone has no open port. It stays idle until a page on the PC is watching, shows a notification while it is,
  and has a control switch and a pause switch. It uses Android's Accessibility permission, which you grant once and
  can revoke at any time in Android settings. It cannot see banking-app or password screens (Android blocks them).

## What you should know

- Anyone who has the token (for example from the QR code or link) can see your screen, and **if you paired an Android phone**,
  see and use it too. Do not share or post it.
  To rotate it, change `SM_TOKEN` in your settings file and restart; every phone must sign in again.
- Anyone who can already run programs on your PC, or who has access to your Tailscale account, is outside what
  this app can protect against.
- The screen includes whatever is on it: passwords you type are visible while you type them, notifications
  included. Lock the PC or stop the server when you do not want to be viewed.
- Use Tailscale ACLs if your tailnet is shared with other people.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private
[security advisory](../../security/advisories/new) form for this repository, or contact the maintainer directly.
