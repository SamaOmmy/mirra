"""The page the QR code in the Mirra window opens on a phone: one tap connects the phone app.

The QR code holds http://<this PC>:<port>/join?c=<pairing code>. The page has one big button: an Android "intent"
link that opens the Mirra app with the PC's address and the code, so the app pairs by itself. If Mirra is not
installed, the same button downloads Mirra Setup from this PC instead (the link's fallback), so nobody needs GitHub.
The page holds nothing secret: the code in it came from the address the phone was given, and it runs out.
"""
import base64
import html
import re
from pathlib import Path
from urllib.parse import quote

ASSETS = Path(__file__).resolve().parent / "assets"
PACKAGE = "app.samantha.phone"
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'none'"


def valid_code(code) -> bool:
    return isinstance(code, str) and re.fullmatch(r"\d{6}", code) is not None


def intent_link(host: str, port: int, code: str, setup_url: str) -> str:
    """Opens Mirra and pairs it; without Mirra installed, the browser goes to setup_url instead."""
    query = f"host={quote(host)}&port={port}&code={code}"
    return (f"intent://pair?{query}#Intent;scheme=mirra;package={PACKAGE};"
            f"S.browser_fallback_url={quote(setup_url, safe='')};end")


def _logo() -> str:
    try:
        return "data:image/png;base64," + base64.b64encode((ASSETS / "mirra-64.png").read_bytes()).decode()
    except OSError:
        return ""


def page(pc: str, host: str, port: int, code: str | None) -> str:
    setup = f"http://{host}:{port}/download/setup"
    if code and valid_code(code):
        main = (f'<a class="btn" href="{html.escape(intent_link(host, port, code, setup))}">Open Mirra and connect</a>'
                f'<p class="small">If Mirra is not on this phone yet, this button downloads Mirra Setup. Open the '
                f'download, install it, open Mirra Setup and tap <b>Install Mirra</b>. Then come back here and tap '
                f'the button again. The code works for 10 minutes.</p>')
    else:
        main = ('<p>This link has no code. On the PC, open Mirra and scan the code on its Home page again.</p>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect to Mirra</title>
<style>
  body {{ margin:0; min-height:100vh; background:#0b0d12; color:#f1f3f8; font:16px/1.5 system-ui,sans-serif;
         display:flex; align-items:center; justify-content:center; }}
  .card {{ max-width:420px; margin:24px; padding:28px 24px; border-radius:24px; text-align:center;
          background:linear-gradient(135deg,#33238f,#0c5566); }}
  img {{ width:64px; height:64px; }}
  h1 {{ font-size:26px; margin:12px 0 4px; }}
  .btn {{ display:block; margin:22px 0 12px; padding:16px; border-radius:16px; background:#fff; color:#1d1650;
         font-weight:600; font-size:18px; text-decoration:none; }}
  .small {{ font-size:14px; color:#dfe3ee; }}
  .alt {{ margin-top:14px; font-size:14px; }} .alt a {{ color:#a5f3fc; }}
</style></head><body><div class="card">
<img src="{_logo()}" alt="">
<h1>Mirra</h1>
<p>Connect this phone to <b>{html.escape(pc)}</b>.</p>
{main}
<p class="alt"><a href="{html.escape(setup)}">Download Mirra Setup</a></p>
</div></body></html>"""
