Samantha Screen Mirror
======================

Your PC on your phone, and your Android phone on your PC. Privately, over Tailscale.

1. Double-click  Samantha.exe
   The Samantha window opens. The first time it checks Tailscale and starts Samantha
   (it then starts by itself whenever you log in to Windows).

2. On your Android phone: install the free Tailscale app, sign in with the SAME
   account as this PC and switch it on. Then scan the QR code on Samantha's Home page
   to get the Samantha app, and type the PC address and code shown there.

3. In the phone app, "Show my PC" shows this PC. Under "My phone" in the Samantha
   window on the PC you see your phone and use it with the mouse and keyboard.

iPhone? There is no iPhone app, but Safari can watch the PC: in the Samantha window go
to Settings > iPhone or a web browser > Show the link, and scan it.

Windows may say "Windows protected your PC" the first time (the program is not
code-signed). Click "More info" > "Run anyway". The source code is public, so you can
also build it yourself: see the project page.

Updates: the Samantha window says when a new version is out (Update now). After the PC
updates, the phone app offers the matching update too.

For the command line (PowerShell in this folder):
  .\samantha-mirror.exe doctor    check that everything works
  .\samantha-mirror.exe update    update from the command line
  .\samantha-mirror.exe uninstall remove start-at-logon and the HTTPS setup

Do not move or delete this folder after setup: start-at-logon points to it.
