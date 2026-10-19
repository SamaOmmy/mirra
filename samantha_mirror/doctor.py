"""`samantha-mirror doctor`: checks everything the app depends on and says how to fix what's wrong."""
import platform
import sys
import urllib.request

from . import __version__, autostart, config, tailscale, updater

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}


def _check(results, level, name, detail="", fix=""):
    results.append((level, name, detail, fix))


def run() -> int:
    r = []

    _check(r, OK if platform.system() == "Windows" else FAIL, "Windows",
           platform.platform(), "Samantha Screen Mirror currently supports Windows only.")
    _check(r, OK if sys.version_info >= (3, 10) else FAIL, "Python 3.10+", platform.python_version(),
           "Install a newer Python from https://www.python.org/downloads/")

    # Tailscale
    st = None
    if not tailscale.find_cli():
        _check(r, FAIL, "Tailscale installed", "", f"Install it from {tailscale.DOWNLOAD_URL}, then run `samantha-mirror setup`.")
    else:
        try:
            st = tailscale.status()
            state = tailscale.backend_state(st)
            _check(r, OK if state == "Running" else FAIL, "Tailscale connected", state,
                   "Open Tailscale from the system tray and sign in / turn it on.")
        except tailscale.BindError as exc:
            _check(r, FAIL, "Tailscale connected", str(exc), "Start the Tailscale app.")
    ip = None
    if st and tailscale.backend_state(st) == "Running":
        try:
            ip = tailscale.tailscale_ip()
            _check(r, OK, "Tailscale address", ip)
        except tailscale.BindError as exc:
            _check(r, FAIL, "Tailscale address", str(exc))

    # Settings
    cfg = None
    try:
        cfg = config.load()
        _check(r, OK, "Settings and token", str(config.env_path()))
    except config.ConfigError as exc:
        _check(r, FAIL, "Settings and token", str(exc), "Run `samantha-mirror setup`.")

    # HTTPS
    if st and cfg:
        if not tailscale.https_enabled(st):
            _check(r, WARN, "HTTPS (for installing as an app)", "not enabled on your tailnet",
                   f"Enable it at {tailscale.ADMIN_DNS_URL}, then run `samantha-mirror setup`. The app still works in the browser.")
        else:
            url = tailscale.https_url(st, cfg.port)
            if url and cfg.loopback:
                _check(r, OK, "HTTPS (for installing as an app)", url)
            else:
                _check(r, WARN, "HTTPS (for installing as an app)", "available but not set up",
                       "Run `samantha-mirror setup` and say yes to HTTPS.")

    # Capture
    try:
        import mss
        with mss.MSS() as sct:
            count = len(sct.monitors) - 1
        _check(r, OK, "Screen capture", f"{count} monitor(s) found")
    except Exception as exc:
        _check(r, FAIL, "Screen capture", str(exc))
    try:
        import dxcam  # noqa: F401
        _check(r, OK, "Fast capture (DXGI)", "available")
    except Exception as exc:
        _check(r, WARN, "Fast capture (DXGI)", f"not available ({exc})", "Falls back to a slower method. Try: pip install dxcam")
    try:
        import cv2  # noqa: F401
        _check(r, OK, "Fast encoder (OpenCV)", "available")
    except Exception:
        _check(r, WARN, "Fast encoder (OpenCV)", "not installed", "Slower but works. Try: pip install opencv-python-headless")

    # Sound (optional: each phone switches it on for itself)
    if cfg and not cfg.audio:
        _check(r, OK, "PC sound for phones", "switched off (SM_AUDIO=0)")
    else:
        try:
            from .audio import Loopback
            _check(r, OK, "PC sound for phones", f"available ({Loopback().default_name()})")
        except Exception as exc:
            _check(r, WARN, "PC sound for phones", f"not available ({exc})",
                   "Only needed if you want to hear the PC on your phone. Check that the PC has a speaker or headphones selected.")

    # Server
    if ip and cfg:
        try:
            code = urllib.request.urlopen(f"http://{ip}:{cfg.port}/", timeout=3).status
            _check(r, OK if code == 200 else WARN, "Server responding", f"http://{ip}:{cfg.port}/ -> {code}")
        except Exception:
            _check(r, FAIL, "Server responding", f"nothing answers on {ip}:{cfg.port}",
                   "On this PC run `samantha-mirror start` (or `samantha-mirror setup` the first time).")
    state = autostart.status()
    if state == "disabled":
        _check(r, WARN, "Starts automatically at logon", "stopped on purpose (`samantha-mirror stop`)",
               "To turn it back on, run `samantha-mirror start`")
    else:
        _check(r, OK if state != "missing" else WARN, "Starts automatically at logon", state,
               "Optional: `samantha-mirror autostart install`")

    # Android phone on this PC (optional)
    from .server import PHONE_APP
    _check(r, OK, "Phone on this PC (Android, optional)",
           "the phone app is included" if PHONE_APP.exists() else "this copy has no phone app (see the README to build it)")

    try:
        newer = updater.available()
        if newer:
            _check(r, WARN, "Up to date", f"v{__version__}, newer v{newer.version} is available", "Run `samantha-mirror update`")
        else:
            _check(r, OK, "Up to date", f"v{__version__}")
    except updater.UpdateError:
        _check(r, OK, "Up to date", f"v{__version__} (could not check for newer versions)")

    width = max(len(name) for _, name, _, _ in r)
    for level, name, detail, fix in r:
        print(f"{MARK[level]} {name.ljust(width)}  {detail}")
        if fix and level != OK:
            print(f"       -> {fix}")
    failed = sum(1 for level, *_ in r if level == FAIL)
    warned = sum(1 for level, *_ in r if level == WARN)
    print(f"\n{'Everything looks good.' if not failed else f'{failed} problem(s) to fix.'}"
          f"{f' {warned} optional suggestion(s).' if warned else ''}")
    return 1 if failed else 0
