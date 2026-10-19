"""Command line: samantha-mirror [run|setup|link|doctor|start|stop|phone|autostart|update|uninstall]"""
import argparse
import sys

from . import APP_NAME, __version__


def _utf8_console() -> None:
    # The QR code uses block characters; the default Windows console encoding can't print them.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _double_clicked() -> int:
    """Packaged .exe opened by double-click: set up the first time, show the phone link afterwards."""
    from . import autostart, config
    from .wizard import setup, show_link
    configured = config.env_path().exists() and autostart.status() != "missing"
    if configured:
        from .updater import UpdateError, available, run_update
        from .wizard import ask
        try:
            newer = available()
        except UpdateError:
            newer = None  # offline: skip the update offer
        if newer:
            print(f"A new version is available: v{newer.version} (you have v{__version__}).")
            if ask("Update now?", True):
                return run_update(yes=True)  # this window closes while the new version installs
    if configured and autostart.status() == "disabled":
        print("Note: the server is stopped on purpose. Run `samantha-mirror start` in this folder to turn it back on.\n")
    code = show_link() if configured else setup()
    if configured:
        print("\nAndroid phone? To see it on this PC and use it with your mouse and keyboard, run: samantha-mirror phone")
    try:
        input("\nPress Enter to close this window...")
    except EOFError:
        pass
    return code


def main(argv=None) -> int:
    _utf8_console()
    p = argparse.ArgumentParser(prog="samantha-mirror", description=f"{APP_NAME}: see your PC screen on your phone, over Tailscale.")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="start the server (default)")
    s = sub.add_parser("setup", help="guided first-time setup")
    s.add_argument("-y", "--yes", action="store_true", help="accept the defaults without asking")
    sub.add_parser("link", help="show the phone link and QR code")
    sub.add_parser("doctor", help="check that everything is working")
    a = sub.add_parser("autostart", help="start automatically when you log in")
    a.add_argument("action", choices=["install", "remove", "status"])
    u = sub.add_parser("update", help="check for a new version and install it")
    u.add_argument("--check", action="store_true", help="only say whether an update is available")
    u.add_argument("-y", "--yes", action="store_true", help="install without asking")
    sub.add_parser("stop", help="stop the server and keep it stopped (until you run `start`)")
    sub.add_parser("start", help="start the server again (and let it start at logon)")
    ph = sub.add_parser("phone", help="open the page that shows your Android phone on this PC and lets you control it")
    ph.add_argument("--url", action="store_true", help="only print the address of the page")
    sub.add_parser("uninstall", help="remove autostart and the HTTPS setup (keeps your settings)")

    args = p.parse_args(argv)
    if args.cmd is None and getattr(sys, "frozen", False):
        return _double_clicked()  # the packaged .exe was opened with no command
    cmd = args.cmd or "run"

    if cmd == "run":
        from .runner import run_server
        return run_server()
    if cmd == "setup":
        from .wizard import setup
        return setup(args.yes)
    if cmd == "link":
        from .wizard import show_link
        return show_link()
    if cmd == "doctor":
        from .doctor import run
        return run()
    if cmd == "autostart":
        from . import autostart
        if args.action == "install":
            autostart.install()
            print("Installed and started. It will also start at every logon.")
        elif args.action == "remove":
            autostart.remove()
            print("Removed.")
        else:
            print(f"Autostart: {autostart.status()}")
        return 0
    if cmd == "stop":
        from . import autostart
        if autostart.status() == "missing":
            print("Nothing to stop: start-at-logon is not set up. (A copy started with `run` stops with Ctrl+C.)")
            return 0
        autostart.pause()
        print("Stopped. It will stay stopped, including after a restart, until you run `samantha-mirror start`.")
        return 0
    if cmd == "start":
        from . import autostart
        if autostart.status() == "missing":
            print("Start-at-logon is not set up yet. Run `samantha-mirror setup` first.")
            return 1
        try:
            autostart.resume()
        except RuntimeError as exc:
            print(f"Could not start it: {exc}")
            return 1
        print("Started. It will also start at every logon again.")
        return 0
    if cmd == "phone":
        from .phonepage import open_phone_page
        return open_phone_page(only_print=args.url)
    if cmd == "update":
        from .updater import run_update
        return run_update(args.check, args.yes)
    if cmd == "uninstall":
        from . import autostart, config, tailscale
        autostart.remove()
        try:
            tailscale.disable_https(tailscale.status(), config.load().port)
        except Exception:
            pass
        print(f"Removed autostart and the HTTPS setup. Your settings are kept in {config.data_dir()}.")
        return 0
    return 2
