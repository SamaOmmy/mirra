"""`samantha-mirror setup`: gets a new user from nothing to a working phone link."""
import shutil
import subprocess
import time
import urllib.request
import webbrowser

from . import APP_NAME, autostart, config, tailscale
from .qr import render


def say(text: str = "") -> None:
    print(text, flush=True)


def ask(question: str, default: bool = True, assume_yes: bool = False) -> bool:
    if assume_yes:
        return default
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{question} [{hint}] ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def step(n: int, total: int, title: str) -> None:
    say(f"\n[{n}/{total}] {title}")


def _wait(check, seconds: int, what: str) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        print(".", end="", flush=True)
        time.sleep(2)
    say(f"\n  Timed out waiting for {what}.")
    return False


def _tailscale_ready(yes: bool) -> dict | None:
    """Make sure Tailscale is installed and signed in. Returns its status, or None to stop."""
    if not tailscale.find_cli():
        say("  Tailscale is not installed. It is the private network that lets your phone reach this PC")
        say("  from anywhere, without opening anything to the internet. It is free for personal use.")
        if shutil.which("winget") and ask("  Install it now with winget? (Windows will ask for permission)", True, yes):
            subprocess.run(["winget", "install", "--id", "Tailscale.Tailscale", "-e",
                            "--accept-package-agreements", "--accept-source-agreements"])
        else:
            say(f"  Download and install it from {tailscale.DOWNLOAD_URL}")
            if not yes:
                webbrowser.open(tailscale.DOWNLOAD_URL)
        if not _wait(lambda: tailscale.find_cli() is not None, 180, "Tailscale to be installed"):
            say("  Install Tailscale, then run `samantha-mirror setup` again.")
            return None

    st = tailscale.status()
    if tailscale.backend_state(st) != "Running":
        say("  Tailscale is installed but not signed in / connected.")
        say("  Open Tailscale from the system tray (or Start menu) and sign in. Waiting...")
        if not _wait(lambda: tailscale.backend_state(tailscale.status()) == "Running", 300, "Tailscale to connect"):
            return None
        st = tailscale.status()
    say(f"  Tailscale is running as '{tailscale.dns_name(st) or tailscale.tailscale_ip()}'.")
    return st


def phone_instructions(url: str, https: bool) -> None:
    say("\nOn your phone:")
    say("  1. Install the Tailscale app and sign in with the SAME account as this PC:")
    say(f"       Android: {tailscale.PLAY_STORE_URL}")
    say(f"       iPhone:  {tailscale.APP_STORE_URL}")
    say("  2. Make sure Tailscale is switched on in the phone.")
    say("  3. Android: use the Samantha app. Open Samantha on this PC (the Samantha shortcut, or")
    say("     `samantha-mirror app`): its Home page has the app download and a code to connect.")
    say("     iPhone (or any browser): point the camera at the QR code above and tap the link. It signs you in.")
    if https:
        say("     Then Share > Add to Home Screen.")


def best_url(cfg: config.Config, st: dict | None = None) -> tuple[str, bool]:
    """(base address, is_https) to give the phone."""
    try:
        st = st or tailscale.status()
        https = tailscale.https_url(st, cfg.port) if tailscale.https_enabled(st) else None
        if https:
            return https.rstrip("/"), True
    except tailscale.BindError:
        pass
    return f"http://{tailscale.tailscale_ip()}:{cfg.port}", False


def show_link() -> int:
    try:
        cfg = config.load()
        base, https = best_url(cfg)
    except (config.ConfigError, tailscale.BindError) as exc:
        say(f"ERROR: {exc}")
        return 1
    url = f"{base}/?token={cfg.token}"
    say(render(url))
    say(f"\n{url}")
    say("\nAnyone with this link can see your screen. Don't share or post it.")
    say(f"Your token (the part after token=) is saved in: {config.env_path()}")
    phone_instructions(url, https)
    return 0


def _server_up(url: str) -> bool:
    try:
        return urllib.request.urlopen(url, timeout=3).status == 200
    except Exception:
        return False


def setup(yes: bool = False) -> int:
    total = 5
    say(f"{APP_NAME} setup")
    say("=" * (len(APP_NAME) + 6))

    step(1, total, "Tailscale (private network between your PC and phone)")
    st = _tailscale_ready(yes)
    if st is None:
        return 1

    step(2, total, "Your access token")
    created = config.ensure_env()
    say(f"  {'Created' if created else 'Found'} settings file: {config.env_path()}")
    if created:
        say("  A random secret token was generated. It is what lets your phone in.")
    cfg = config.load()

    step(3, total, "HTTPS (lets the phone install it as a real app)")
    if tailscale.https_enabled(st):
        if ask("  Turn on Tailscale HTTPS for this app? (stays inside your private network)", True, yes):
            try:
                url = tailscale.enable_https(st, cfg.port)
                config.set_env_value("SM_LOOPBACK", "1")
                say(f"  HTTPS address: {url}")
            except tailscale.BindError as exc:
                say(f"  Could not enable HTTPS: {exc}\n  Continuing without it.")
    else:
        say("  HTTPS isn't enabled on your tailnet yet, so the phone can use the app in the browser")
        say("  but can't install it as a full app. To turn it on (one time, 1 minute):")
        say(f"    1. Open {tailscale.ADMIN_DNS_URL}")
        say("    2. Make sure MagicDNS is on, then click 'Enable HTTPS'.")
        say("    3. Run `samantha-mirror setup` again.")
        if not yes and ask("  Open that page now?", False, yes):
            webbrowser.open(tailscale.ADMIN_DNS_URL)

    step(4, total, "Start automatically")
    started = False
    if ask("  Start Samantha Screen Mirror hidden whenever you log in to Windows?", True, yes):
        try:
            autostart.install(start_now=True)
            started = True
            say("  Done. It starts at every logon and is running now.")
        except RuntimeError as exc:
            say(f"  Could not set it up: {exc}")
    if not started:
        say("  OK. Start it yourself with `samantha-mirror run` whenever you want to use it.")

    step(5, total, "Check and link your phone")
    cfg = config.load()  # re-read: SM_LOOPBACK may have changed
    if started:
        _wait(lambda: _server_up(f"http://{tailscale.tailscale_ip()}:{cfg.port}/"), 30, "the server to start")
        say("")
    say(f"  Server is {'running' if _server_up(f'http://{tailscale.tailscale_ip()}:{cfg.port}/') else 'NOT running yet'}.")
    say("")
    show_link()
    say("\nSetup finished. Run `samantha-mirror doctor` if anything doesn't work.")
    return 0
