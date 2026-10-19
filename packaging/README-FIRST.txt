Samantha Screen Mirror
======================

See your PC screen on your phone, privately, over Tailscale.

1. Double-click  samantha-mirror.exe
   It guides you through setup (Tailscale, your secret token, start-at-logon) and
   shows a QR code.

2. On your phone: install the free Tailscale app, sign in with the SAME account as
   this PC, switch it on, then scan the QR code.

3. Next time, just open the app on your phone. The server starts by itself when you
   log in to Windows.

Windows may say "Windows protected your PC" the first time (the program is not
code-signed). Click "More info" > "Run anyway". The source code is public, so you can
also build it yourself: see the project page.

Other commands (open PowerShell in this folder):
  .\samantha-mirror.exe link      show the QR code again
  .\samantha-mirror.exe doctor    check that everything works
  .\samantha-mirror.exe phone     Android: open the page that shows your phone on this PC and lets you
                                  control it (set the phone up first: see the project page)
  .\samantha-mirror.exe uninstall remove start-at-logon and the HTTPS setup

Do not move or delete this folder after setup: start-at-logon points to it.
