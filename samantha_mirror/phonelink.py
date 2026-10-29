"""Relay between the Android companion app and the PC page that shows and controls the phone.

The phone app connects *out* to this server (with the same token as everything else) and never listens for
connections. It long-polls for commands and posts screenshots; the PC page watches the latest screenshot and sends
taps, swipes and keys. Nothing is captured on the phone unless a page is watching it.
"""
import threading
import time
from collections import deque

MAX_FRAME = 3_000_000       # bytes in one phone screenshot (JPEG)
POLL_SECONDS = 25           # how long the phone's command request may wait
GONE_AFTER = POLL_SECONDS + 10   # the phone counts as disconnected after this much silence
MAX_QUEUE = 200
KEYS = {"back", "home", "recents", "notifications", "quicksettings", "wake", "lock", "power", "volup", "voldown"}
MAX_TEXT = 500
MAX_POINTS = 200
MAX_GESTURE_MS = 10_000
MAX_NOTIFICATIONS = 30      # the phone's newest notifications the Mirra window can show


class BadInput(ValueError):
    """An input event the page sent is not one we accept."""


def _unit(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise BadInput("coordinates must be numbers from 0 to 1")
    return float(value)


def parse_input(data) -> dict:
    """Validate a page's input event; returns the command to send to the phone."""
    if not isinstance(data, dict):
        raise BadInput("expected a JSON object")
    kind = data.get("t")
    if kind in ("tap", "long"):
        return {"t": kind, "x": _unit(data.get("x")), "y": _unit(data.get("y"))}
    if kind == "gesture":
        points = data.get("pts")
        ms = data.get("ms")
        if not isinstance(points, list) or not 2 <= len(points) <= MAX_POINTS:
            raise BadInput(f"a gesture needs 2 to {MAX_POINTS} points")
        if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not 1 <= ms <= MAX_GESTURE_MS:
            raise BadInput(f"ms must be 1 to {MAX_GESTURE_MS}")
        clean = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise BadInput("each point is [x, y]")
            clean.append([_unit(point[0]), _unit(point[1])])
        return {"t": "gesture", "pts": clean, "ms": int(ms)}
    if kind == "touch":
        if data.get("a") not in ("down", "move", "up"):
            raise BadInput("a touch is down, move or up")
        return {"t": "touch", "a": data["a"], "x": _unit(data.get("x")), "y": _unit(data.get("y"))}
    if kind == "scroll":
        dy = data.get("dy")
        if isinstance(dy, bool) or not isinstance(dy, (int, float)) or not -1 <= dy <= 1:
            raise BadInput("dy must be -1 to 1")
        return {"t": "scroll", "x": _unit(data.get("x")), "y": _unit(data.get("y")), "dy": float(dy)}
    if kind == "pinch":
        return {"t": "pinch", "x": _unit(data.get("x")), "y": _unit(data.get("y")), "in": data.get("in") is True}
    if kind == "key":
        if data.get("k") not in KEYS:
            raise BadInput(f"key must be one of {', '.join(sorted(KEYS))}")
        return {"t": "key", "k": data["k"]}
    if kind == "text":
        text = data.get("s")
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
            raise BadInput(f"text must be 1 to {MAX_TEXT} characters")
        return {"t": "text", "s": text}
    raise BadInput("unknown event type")


class PhoneHub:
    def __init__(self):
        self._cond = threading.Condition()
        self._frame = None            # latest JPEG
        self._seq = 0
        self._size = (0, 0)
        self._info: dict = {}
        self._seen = 0.0              # last time the phone talked to us
        self._frame_at = 0.0
        self._commands: deque = deque(maxlen=MAX_QUEUE)
        self._watchers = 0
        self._token = 0               # changes when a newer phone request replaces an older one
        self._notifications: deque = deque(maxlen=MAX_NOTIFICATIONS)
        self._notified = 0
        self._battery: dict = {}

    # -- the phone ----------------------------------------------------------------------------
    def hello(self, info: dict) -> None:
        """The phone app says who it is (device name, app version, whether control is allowed)."""
        with self._cond:
            self._info = {k: info[k] for k in ("device", "version", "control", "width", "height") if k in info}
            self._seen = time.monotonic()
            self._commands.clear()
            self._commands.append({"t": "watch", "on": self._watchers > 0})   # tell it whether anyone is looking
            self._cond.notify_all()

    def push_frame(self, jpeg: bytes, width: int, height: int) -> None:
        with self._cond:
            self._frame, self._size = jpeg, (width, height)
            self._seq += 1
            self._seen = self._frame_at = time.monotonic()
            self._cond.notify_all()

    def next_commands(self, timeout: float = POLL_SECONDS) -> list:
        """What the phone should do next. Waits up to `timeout` seconds for something to do."""
        with self._cond:
            self._seen = time.monotonic()
            self._token += 1
            mine = self._token
            self._cond.notify_all()      # an older request from the phone, if any, ends now
            if not self._commands:
                self._cond.wait(timeout)
            if mine != self._token:      # a newer request from the phone took over
                return []
            commands = list(self._commands)
            self._commands.clear()
            self._seen = time.monotonic()
            return commands

    def battery(self, level, charging) -> None:
        """The phone's battery, sent with every command request (level 0-100, or None when it can't tell)."""
        with self._cond:
            if type(level) is int and 0 <= level <= 100:
                self._battery = {"level": level, "charging": bool(charging)}

    def notify(self, data) -> None:
        """A notification on the phone, for the Mirra window to show. Raises BadInput for anything malformed."""
        if not isinstance(data, dict):
            raise BadInput("expected a JSON object")
        app, title, text = (data.get(k, "") for k in ("app", "title", "text"))
        if not all(isinstance(v, str) for v in (app, title, text)) or not (title or text):
            raise BadInput("a notification is app, title and text (strings)")
        with self._cond:
            self._notified += 1
            self._notifications.appendleft({"id": self._notified, "app": app[:60], "title": title[:120],
                                            "text": text[:400], "at": time.time()})

    # -- the page -----------------------------------------------------------------------------
    def add_watcher(self) -> None:
        with self._cond:
            self._watchers += 1
            if self._watchers == 1:
                self._command({"t": "watch", "on": True})

    def remove_watcher(self) -> None:
        with self._cond:
            self._watchers = max(0, self._watchers - 1)
            if self._watchers == 0:
                self._command({"t": "watch", "on": False})

    def _command(self, command: dict) -> None:   # lock held
        self._commands.append(command)
        self._cond.notify_all()

    def send_input(self, event: dict) -> bool:
        """Queue an already validated input event. False when no phone is connected or it forbids control."""
        with self._cond:
            if not self._connected() or not self._info.get("control", True):
                return False
            self._command(event)
            return True

    def send_file(self, item: dict) -> bool:
        """Tell the phone a file is waiting for it (see transfer.Outbox). False when no phone is connected."""
        with self._cond:
            if not self._connected():
                return False
            self._command({"t": "file", "id": item["id"], "name": item["name"], "size": item["size"]})
            return True

    def connected(self) -> bool:
        with self._cond:
            return self._connected()

    def wait_frame(self, last_seq: int, timeout: float = 1.0):
        """(seq, jpeg) when there is a newer screenshot, else None."""
        with self._cond:
            if self._seq == last_seq or self._frame is None:
                self._cond.wait(timeout)
            if self._frame is None or self._seq == last_seq:
                return None
            return self._seq, self._frame

    def _connected(self) -> bool:
        return self._seen > 0 and time.monotonic() - self._seen < GONE_AFTER

    def state(self) -> dict:
        with self._cond:
            now = time.monotonic()
            return {
                "connected": self._connected(),
                "device": self._info.get("device", ""),
                "app_version": self._info.get("version", ""),
                "control": bool(self._info.get("control", True)),
                "watchers": self._watchers,
                "width": self._size[0], "height": self._size[1],
                "seq": self._seq,
                "frame_age": round(now - self._frame_at, 1) if self._frame_at else None,
                "battery": dict(self._battery) if self._connected() and self._battery else None,
                "notifications": list(self._notifications),
            }
