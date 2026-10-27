"""Turns the mouse and keyboard on the Samantha window into taps, swipes and typing for the phone.

Positions are fractions (0..1) of the phone picture, which is what the phone app expects.
"""
LONG_PRESS_MS = 500     # holding still this long is a long press
MOVE_SLOP = 0.015       # moving less than this (fraction of the picture) still counts as a tap
MAX_POINTS = 120        # the server accepts up to 200
MIN_STEP_MS = 16
WHEEL_DISTANCE = 0.22   # one wheel notch moves the content this far
WHEEL_MS = 220


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class Pointer:
    """One press of the mouse button, from down to up. `up()` returns the event to send, or None."""

    def __init__(self):
        self._points: list[tuple[float, float, float]] = []   # (x, y, time in ms)
        self._moved = False

    @property
    def active(self) -> bool:
        return bool(self._points)

    def down(self, x: float, y: float, ms: float) -> None:
        self._points = [(_clamp(x), _clamp(y), ms)]
        self._moved = False

    def move(self, x: float, y: float, ms: float) -> None:
        if not self._points:
            return
        x0, y0, _ = self._points[0]
        x, y = _clamp(x), _clamp(y)
        if abs(x - x0) > MOVE_SLOP or abs(y - y0) > MOVE_SLOP:
            self._moved = True
        if ms - self._points[-1][2] >= MIN_STEP_MS:
            self._points.append((x, y, ms))

    def up(self, x: float, y: float, ms: float) -> dict | None:
        if not self._points:
            return None
        self.move(x, y, ms)
        points, self._points = self._points, []
        x0, y0, t0 = points[0]
        held = ms - t0
        if not self._moved:
            return {"t": "long" if held >= LONG_PRESS_MS else "tap", "x": round(x0, 4), "y": round(y0, 4)}
        x, y = _clamp(x), _clamp(y)
        if points[-1][:2] != (x, y):
            points.append((x, y, ms))
        if len(points) > MAX_POINTS:   # keep the shape, drop points evenly
            step = (len(points) - 1) / (MAX_POINTS - 1)
            points = [points[round(i * step)] for i in range(MAX_POINTS)]
        return {"t": "gesture", "pts": [[round(px, 4), round(py, 4)] for px, py, _ in points],
                "ms": int(max(50, min(10_000, held)))}


def wheel(x: float, y: float, notches: float) -> dict:
    """Scrolling the wheel: a short swipe. Wheel down (negative notches) shows what is further down."""
    distance = max(-0.6, min(0.6, notches * WHEEL_DISTANCE))
    start = _clamp(y)
    start = max(0.1, min(0.9, start))
    end = max(0.02, min(0.98, start + distance))
    return {"t": "gesture", "pts": [[round(_clamp(x), 4), round(start, 4)], [round(_clamp(x), 4), round(end, 4)]],
            "ms": WHEEL_MS}


KEYS = {"Escape": ("key", "back")}
CHARACTERS = {"BackSpace": "\b", "Return": "\n", "KP_Enter": "\n", "Tab": "\t"}


def key(keysym: str, char: str) -> tuple[str, str] | None:
    """('text', characters) or ('key', name) for a key press on the window, or None to ignore it."""
    if keysym in KEYS:
        return KEYS[keysym]
    if keysym in CHARACTERS:
        return "text", CHARACTERS[keysym]
    if char and (char.isprintable() and char not in "\r\n"):
        return "text", char
    return None
