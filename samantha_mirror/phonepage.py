"""`samantha-mirror phone`: open, on this PC, the page that shows the Android phone and lets you control it."""
import urllib.request
import webbrowser

from . import config, tailscale


def page_address(cfg: config.Config, with_token: bool = False) -> str:
    """Where this PC reaches its own server: loopback if it listens there, else its Tailscale address."""
    host = "127.0.0.1" if cfg.loopback else tailscale.tailscale_ip()
    url = f"http://{host}:{cfg.port}/phone"
    return f"{url}?token={cfg.token}" if with_token else url


def open_phone_page(only_print: bool = False) -> int:
    try:
        cfg = config.load()
        shown = page_address(cfg)
        opened = page_address(cfg, with_token=True)
    except (config.ConfigError, tailscale.BindError) as exc:
        print(f"Cannot open it: {exc}")
        return 1
    print(shown)
    if only_print:
        return 0
    try:
        urllib.request.urlopen(shown.rsplit("/phone", 1)[0] + "/", timeout=3).close()
    except Exception:
        print("Samantha is not running on this PC. Run `samantha-mirror start` (or `setup` the first time), then try again.")
        return 1
    webbrowser.open(opened)
    print("Opened in your browser. If no phone shows up, open Samantha on your Android phone > Settings > "
          "Use this phone from the PC.")
    return 0
