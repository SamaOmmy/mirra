"""The Samantha window talking to the server on this same PC, through the same API the phone app uses."""
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from . import config, tailscale


class Offline(Exception):
    """Nothing answers: the server is stopped, starting, or Tailscale is off."""


class Refused(Exception):
    """The server answered with an error."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class Local:
    def __init__(self):
        self.cfg = config.load()
        self._base: str | None = None

    def reload(self) -> None:
        """Read the settings again (after the token or the port changed)."""
        self.cfg = config.load()
        self._base = None

    def base(self) -> str:
        if self._base is None:
            host = "127.0.0.1" if self.cfg.loopback else tailscale.tailscale_ip()
            self._base = f"http://{host}:{self.cfg.port}"
        return self._base

    def _open(self, method: str, path: str, data=None, timeout: float = 5):
        try:
            base = self.base()
        except tailscale.BindError as exc:
            raise Offline(str(exc))
        body = None if data is None else json.dumps(data).encode()
        request = urllib.request.Request(base + path, data=body, method=method, headers={
            "Authorization": f"Bearer {self.cfg.token}", "Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read() or b"{}").get("error", "")
            except ValueError:
                message = ""
            raise Refused(exc.code, message or f"The server answered {exc.code}.")
        except OSError as exc:
            self._base = None   # the address may have changed
            raise Offline(str(exc))

    def call(self, method: str, path: str, data=None, timeout: float = 5) -> dict:
        with self._open(method, path, data, timeout) as resp:
            return json.loads(resp.read() or b"{}")

    def get(self, path: str) -> dict:
        return self.call("GET", path)

    def post(self, path: str, data=None) -> dict:
        return self.call("POST", path, data if data is not None else {})

    def stream(self, path: str, timeout: float = 10):
        return self._open("GET", path, timeout=timeout)

    def send_file(self, file: Path) -> dict:
        """Sends a file to the phone (server.py: /api/phone/send), streamed, not read into memory."""
        try:
            base = self.base()
        except tailscale.BindError as exc:
            raise Offline(str(exc))
        with open(file, "rb") as body:
            request = urllib.request.Request(base + "/api/phone/send", data=body, method="POST", headers={
                "Authorization": f"Bearer {self.cfg.token}", "Content-Type": "application/octet-stream",
                "Content-Length": str(file.stat().st_size), "X-File-Name": quote(file.name)})
            try:
                with urllib.request.urlopen(request, timeout=120) as resp:
                    return json.loads(resp.read() or b"{}")
            except urllib.error.HTTPError as exc:
                try:
                    message = json.loads(exc.read() or b"{}").get("error", "")
                except ValueError:
                    message = ""
                raise Refused(exc.code, message or f"The server answered {exc.code}.")
            except OSError as exc:
                raise Offline(str(exc))


def jpeg_frames(resp):
    """The pictures in a multipart (MJPEG) response, one bytes object each."""
    while True:
        length = None
        while True:
            line = resp.readline(200)
            if not line:
                return
            line = line.strip()
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
            elif not line and length is not None:
                break
        data = resp.read(length)
        if len(data) < length:
            return
        yield data
