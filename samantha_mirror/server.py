"""Flask app.

Public: the web app's own files (no secrets in them) and POST /api/login.
Everything else (/stream, /api/*) needs the token.
"""
import io
from pathlib import Path

import mss
from flask import Flask, Response, abort, jsonify, make_response, redirect, request, send_from_directory
from PIL import Image

from . import __version__, updater
from .audio import AudioError, AudioSource, to_low_data
from .auth import COOKIE, Auth
from .capture import FrameSource
from .config import LIMITS, Config
from .phonelink import MAX_FRAME, POLL_SECONDS, BadInput, PhoneHub, parse_input

BOUNDARY = "frame"
COOKIE_MAX_AGE = 30 * 24 * 3600
WEB_DIR = Path(__file__).resolve().parent / "web"
PUBLIC_ENDPOINTS = {"index", "phone_page", "static", "login"}
PHONE_APP = Path(__file__).resolve().parent / "phone_app" / "SamanthaPhone.apk"


def _monitors():
    with mss.MSS() as sct:
        return [
            {"index": i, "width": m["width"], "height": m["height"],
             "label": "All monitors" if i == 0 else f"Monitor {i}"}
            for i, m in enumerate(sct.monitors)
        ]


def _parse_settings(data, monitor_count):
    """Validate a settings update. Returns (changes, error)."""
    if not isinstance(data, dict):
        return None, "expected a JSON object"
    changes = {}
    for key, value in data.items():
        if key == "cursor":
            if not isinstance(value, bool):
                return None, "cursor must be true or false"
            changes[key] = value
        elif key == "monitor":
            if type(value) is not int or not 0 <= value < monitor_count:
                return None, f"monitor must be an integer 0-{monitor_count - 1}"
            changes[key] = value
        elif key in LIMITS:
            lo, hi = LIMITS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None, f"{key} must be a number"
            value = float(value) if key == "scale" else int(value)
            if not lo <= value <= hi:
                return None, f"{key} must be between {lo} and {hi}"
            changes[key] = value
        else:
            return None, f"unknown setting {key!r}"
    return changes, None


def create_app(cfg: Config, sound: AudioSource | None = None, phone: PhoneHub | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = MAX_FRAME + 4096
    phone = phone or PhoneHub()
    auth = Auth(cfg.token)
    sound = sound or AudioSource(enabled=cfg.audio)
    source = FrameSource(cfg.monitor, cfg.fps, cfg.jpeg_quality, cfg.scale, cfg.cursor, cfg.capture)

    def client_ip():
        # Behind `tailscale serve`, waitress (told to trust only the local proxy, see runner.py)
        # already puts the real client address in remote_addr and the real scheme in is_secure.
        return request.remote_addr or "?"

    def set_cookie(resp, token):
        resp.set_cookie(COOKIE, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Strict",
                        secure=request.is_secure, path="/")
        return resp

    @app.before_request
    def require_token():
        ip = client_ip()
        if auth.locked_out(ip):
            abort(429)
        # Opening the page with ?token=... sets the cookie and drops the token from the URL.
        if request.endpoint == "index" and request.args.get("token"):
            if auth.valid(request.args["token"]):
                return set_cookie(redirect("/"), request.args["token"])
            auth.record_failure(ip)
            return None  # fall through to the login screen
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None
        ok, _ = auth.check(request)
        if not ok:
            auth.record_failure(ip)
            abort(401)

    @app.after_request
    def security_headers(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' blob:; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'"
        )
        return resp

    @app.errorhandler(401)
    @app.errorhandler(404)
    @app.errorhandler(429)
    @app.errorhandler(503)
    def plain_error(err):
        return Response(err.name, status=err.code, mimetype="text/plain")

    # -- web app -------------------------------------------------------------
    @app.get("/")
    def index():
        if not (WEB_DIR / "index.html").exists():
            return Response("Web app not built. Run: cd web && npm install && npm run build",
                            status=500, mimetype="text/plain")
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/phone")
    def phone_page():
        """The page that shows and controls the phone: the same web app, which looks at the address."""
        return index()

    @app.post("/api/login")
    def login():
        data = request.get_json(silent=True) or {}
        token = data.get("token", "") if isinstance(data, dict) else ""
        if not isinstance(token, str) or not auth.valid(token.strip()):
            auth.record_failure(client_ip())
            return jsonify(error="Wrong token"), 401
        return set_cookie(make_response(jsonify(ok=True)), token.strip())

    @app.post("/api/logout")
    def logout():
        resp = make_response(jsonify(ok=True))
        resp.delete_cookie(COOKIE, path="/")
        return resp

    # -- API -----------------------------------------------------------------
    @app.get("/api/state")
    def state():
        # Polled by the page: its frame counters show whether the stream is stuck.
        return jsonify(source.state() | {"settings": source.settings(), "version": __version__,
                                                    "update": updater.cached_info(), "audio": sound.state()})

    @app.get("/api/monitors")
    def monitors():
        return jsonify(monitors=_monitors(), limits=LIMITS, max_clients=cfg.max_clients)

    @app.post("/api/settings")
    def settings():
        changes, error = _parse_settings(request.get_json(silent=True), len(_monitors()))
        if error:
            return jsonify(error=error), 400
        source.configure(**changes)
        return jsonify(source.settings())

    @app.get("/api/screenshot")
    def screenshot():
        """Full-resolution PNG of the selected monitor, independent of the stream settings."""
        index = source.settings()["monitor"]
        with mss.MSS() as sct:
            if index >= len(sct.monitors):
                abort(404)
            shot = sct.grab(sct.monitors[index])
        buf = io.BytesIO()
        Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX").save(buf, "PNG")
        resp = Response(buf.getvalue(), mimetype="image/png")
        resp.headers["Content-Disposition"] = 'attachment; filename="screenshot.png"'
        return resp

    @app.get("/stream")
    def stream():
        if source.client_count() >= cfg.max_clients:
            abort(503)
        source.add_client()

        def generate():
            last = -1
            idle = 0
            try:
                while True:
                    item = source.wait_frame(last)
                    if item is None:
                        # Nothing new. A long silence while capture is failing ends the
                        # stream so the page retries; on a static screen, resend the frame
                        # now and then so a vanished viewer is noticed (the write fails).
                        idle += 1
                        if idle >= 6 and source.state()["error"]:
                            return
                        if idle % 2 == 0:
                            item = source.wait_frame(-1, timeout=0)
                        if item is None:
                            continue
                    else:
                        idle = 0
                    last, jpeg = item
                    yield (
                        b"--" + BOUNDARY.encode() + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                        + jpeg + b"\r\n"
                    )
            finally:
                source.remove_client()

        resp = make_response(Response(generate(), mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}"))
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    @app.get("/api/audio")
    def audio():
        """The PC's sound as raw 16-bit PCM. Only phones that switched sound on in their settings ask for it."""
        low = request.args.get("q") == "low"
        if sound.listener_count() >= cfg.max_clients:
            abort(503)
        try:
            rate, channels, generation = sound.add_listener()
        except AudioError as exc:
            return jsonify(error=str(exc)), 409
        if low:
            rate, out_channels = rate // 2, 1
        else:
            out_channels = channels

        def silence(milliseconds):
            return bytes(2 * out_channels * (rate * milliseconds // 1000))

        def generate():
            last, quiet = -1, 0
            try:
                yield silence(10)  # the response only starts once something is written: don't wait for the PC to make a sound
                while True:
                    items = sound.wait(last, generation)
                    if items is None:
                        return  # speakers changed or recording stopped: the page reconnects
                    if not items:
                        # Silence: send a few milliseconds of it now and then so a vanished phone is noticed.
                        quiet += 1
                        if quiet % 2 == 0:
                            yield silence(20)
                        continue
                    quiet = 0
                    for seq, pcm in items:
                        last = seq
                        yield to_low_data(pcm, channels) if low else pcm
            finally:
                sound.remove_listener()

        resp = Response(generate(), mimetype="application/octet-stream")
        resp.headers["X-Audio-Rate"] = str(rate)
        resp.headers["X-Audio-Channels"] = str(out_channels)
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    # -- Android phone: companion app <-> relay <-> this PC's page -------------------------------
    @app.get("/api/phone/state")
    def phone_state():
        return jsonify(phone.state() | {"app_available": PHONE_APP.exists()})

    @app.get("/api/phone/pair")
    def phone_pair():
        """What the phone app needs to link up with this PC. Sent only to a device that already has the token."""
        return jsonify(token=cfg.token)

    @app.get("/api/phone/app.apk")
    def phone_app():
        if not PHONE_APP.exists():
            return jsonify(error="This copy of Samantha does not include the Android app."), 404
        return send_from_directory(PHONE_APP.parent, PHONE_APP.name, as_attachment=True,
                                   mimetype="application/vnd.android.package-archive")

    @app.post("/api/phone/hello")
    def phone_hello():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="expected a JSON object"), 400
        info = {"device": str(data.get("device", ""))[:80], "version": str(data.get("version", ""))[:20],
                "control": data.get("control") is not False}
        for key in ("width", "height"):
            if type(data.get(key)) is int and 0 < data[key] < 20000:
                info[key] = data[key]
        phone.hello(info)
        return jsonify(ok=True, poll=POLL_SECONDS)

    @app.get("/api/phone/commands")
    def phone_commands():
        return jsonify(phone.next_commands())

    @app.post("/api/phone/frame")
    def phone_frame():
        jpeg = request.get_data()
        if not jpeg.startswith(b"\xff\xd8"):
            return jsonify(error="expected a JPEG"), 400
        width, height = request.headers.get("X-Width", type=int, default=0), request.headers.get("X-Height", type=int, default=0)
        phone.push_frame(jpeg, width, height)
        return jsonify(ok=True)

    @app.get("/api/phone/stream")
    def phone_stream():
        if phone.state()["watchers"] >= cfg.max_clients:
            abort(503)
        phone.add_watcher()

        def generate():
            last, idle = -1, 0
            try:
                while True:
                    item = phone.wait_frame(last)
                    if item is None:
                        idle += 1
                        if idle % 8 or last < 0:     # now and then repeat the picture so a vanished page is noticed
                            continue
                        item = phone.wait_frame(-1, timeout=0)
                        if item is None:
                            continue
                    else:
                        idle = 0
                    last, jpeg = item
                    yield (b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                           + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            finally:
                phone.remove_watcher()

        resp = make_response(Response(generate(), mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}"))
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    @app.post("/api/phone/input")
    def phone_input():
        try:
            event = parse_input(request.get_json(silent=True))
        except BadInput as exc:
            return jsonify(error=str(exc)), 400
        if not phone.send_input(event):
            return jsonify(error="The phone is not connected, or it does not allow control."), 409
        return jsonify(ok=True)

    return app
