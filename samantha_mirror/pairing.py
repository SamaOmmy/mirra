"""Pairing a phone app with this PC by a short code instead of typing the long token.

The Samantha window on the PC asks for a code and shows it. The phone app sends that code once and gets the
token back. A code works for a few minutes only, for any number of phones while it lasts, and a handful of
wrong tries throws it away (on top of the per-address lockout every wrong token already gets).
"""
import hmac
import secrets
import threading
import time

CODE_SECONDS = 10 * 60
MAX_WRONG = 5
DIGITS = 6


class Pairing:
    def __init__(self):
        self._lock = threading.Lock()
        self._code: str | None = None
        self._until = 0.0
        self._wrong = 0
        self._paired: list[dict] = []

    def new_code(self) -> dict:
        with self._lock:
            self._code = "".join(secrets.choice("0123456789") for _ in range(DIGITS))
            self._until = time.monotonic() + CODE_SECONDS
            self._wrong = 0
            return {"code": self._code, "expires_in": CODE_SECONDS}

    def cancel(self) -> None:
        with self._lock:
            self._code = None

    def current(self) -> dict | None:
        with self._lock:
            left = self._until - time.monotonic()
            if not self._code or left <= 0:
                return None
            return {"code": self._code, "expires_in": int(left)}

    def claim(self, code, device: str = "") -> bool:
        """True if `code` is the code on the PC screen right now."""
        if not isinstance(code, str):
            return False
        code = "".join(ch for ch in code if ch.isdigit())
        with self._lock:
            if not self._code or time.monotonic() > self._until:
                self._code = None
                return False
            if not hmac.compare_digest(code.encode(), self._code.encode()):
                self._wrong += 1
                if self._wrong >= MAX_WRONG:
                    self._code = None
                return False
            self._paired.append({"device": device[:80] or "a phone", "at": time.time()})
            del self._paired[:-10]
            return True

    def recent(self) -> list[dict]:
        """Phones that paired since the server started (newest last), so the PC window can say "paired"."""
        with self._lock:
            return list(self._paired)
