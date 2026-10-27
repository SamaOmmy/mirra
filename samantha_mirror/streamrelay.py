"""The live link between the phone and the Mirra window: the phone's screen as video, and touches going back.

A plain TCP port next to the web port (SM_PORT + 1), on the same addresses (the Tailscale address, and 127.0.0.1 if
enabled). Each side connects and sends one JSON line, {"token": ..., "role": "phone" | "viewer"}, and gets
{"ok": true} back (or an error, and the connection closes). After that both sides send frames:

    1 byte type, 4 bytes big-endian length, payload

    phone -> viewers   'H'  JSON: the picture size, codec and so on (sent first, and again when it changes)
                       'V'  video: 1 byte flags (1 = key frame, 2 = codec config), then H.264 (Annex B)
                       'J'  one JPEG picture (when the phone cannot record its screen, it sends screenshots)
    viewers -> phone   'I'  JSON input event (touch, key, text)
                       'C'  JSON control ({"t": "keyframe"}, {"t": "quality", ...})
    relay -> phone     'C'  {"t": "viewers", "n": ...}

The relay only forwards bytes; it never decodes anything. Opening a viewer also tells the phone, over its usual web
link, to start sharing (PhoneHub watchers), so the phone records nothing while nobody looks.
"""
import json
import logging
import queue
import socket
import struct
import threading

from .auth import Auth
from .phonelink import PhoneHub

log = logging.getLogger("samantha-mirror")

MAX_FRAME = 8_000_000
HEADER = struct.Struct(">cI")
HANDSHAKE_LIMIT = 4096
FROM_PHONE = {b"H", b"V", b"J"}
FROM_VIEWER = {b"I", b"C"}
VIEWER_QUEUE = 240        # frames waiting for a slow viewer before it starts over from the next key frame
KEY_FRAME, CODEC_CONFIG = 1, 2


def frame(kind: bytes, payload: bytes) -> bytes:
    return HEADER.pack(kind, len(payload)) + payload


def read_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def read_frame(sock: socket.socket):
    """(type, payload), or None when the other side has gone."""
    head = read_exact(sock, HEADER.size)
    if head is None:
        return None
    kind, size = HEADER.unpack(head)
    if size > MAX_FRAME:
        raise ValueError("frame too large")
    payload = read_exact(sock, size)
    return None if payload is None else (kind, payload)


def read_line(sock: socket.socket) -> bytes:
    buf = bytearray()
    while not buf.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("closed during handshake")
        buf += chunk
        if len(buf) > HANDSHAKE_LIMIT:
            raise ValueError("handshake too long")
    return bytes(buf)


class _Viewer:
    """A Mirra window. Frames go out through a queue so one slow window cannot hold up the phone."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.out: queue.Queue = queue.Queue(maxsize=VIEWER_QUEUE)
        self.need_key = False
        self.alive = True
        threading.Thread(target=self._send, name="relay-viewer-out", daemon=True).start()

    def push(self, kind: bytes, payload: bytes, flags: int = 0) -> bool:
        """False when this viewer fell behind and needs a key frame to catch up."""
        if not self.alive:
            return True
        if self.need_key and kind == b"V" and not flags & (KEY_FRAME | CODEC_CONFIG):
            return True   # skipping until the next key frame
        try:
            self.out.put_nowait(frame(kind, payload))
            if flags & KEY_FRAME:
                self.need_key = False
            return True
        except queue.Full:
            while not self.out.empty():
                try:
                    self.out.get_nowait()
                except queue.Empty:
                    break
            self.need_key = True
            return False

    def _send(self):
        try:
            while self.alive:
                data = self.out.get()
                if data is None:
                    return
                self.sock.sendall(data)
        except OSError:
            pass
        finally:
            self.alive = False

    def close(self):
        self.alive = False
        try:
            self.out.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Relay:
    def __init__(self, auth: Auth, hub: PhoneHub, max_viewers: int = 3):
        self.auth = auth
        self.hub = hub
        self.max_viewers = max_viewers
        self._lock = threading.Lock()
        self._phone: socket.socket | None = None
        self._phone_send = threading.Lock()
        self._viewers: list[_Viewer] = []
        self._info: bytes | None = None       # the phone's last 'H'
        self._config: bytes | None = None     # the last codec config (SPS/PPS) 'V' payload
        self._listeners: list[socket.socket] = []
        self._closed = False

    # -- listening ------------------------------------------------------------------------------
    def listen(self, host: str, port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE if hasattr(socket, "SO_EXCLUSIVEADDRUSE")
                        else socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(8)
        self._listeners.append(sock)
        threading.Thread(target=self._accept, args=(sock,), name=f"relay-{host}", daemon=True).start()

    def port(self) -> int:
        return self._listeners[0].getsockname()[1]

    def close(self) -> None:
        self._closed = True
        for s in self._listeners:
            try:
                s.close()
            except OSError:
                pass
        with self._lock:
            phone, viewers = self._phone, list(self._viewers)
            self._phone, self._viewers = None, []
        for v in viewers:
            v.close()
        if phone:
            phone.close()

    def _accept(self, listener: socket.socket) -> None:
        while not self._closed:
            try:
                conn, addr = listener.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn, addr[0]), name="relay-conn", daemon=True).start()

    def state(self) -> dict:
        with self._lock:
            return {"phone": self._phone is not None, "viewers": len(self._viewers)}

    # -- one connection ---------------------------------------------------------------------------
    def _handle(self, conn: socket.socket, ip: str) -> None:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            conn.settimeout(10)
            try:
                hello = json.loads(read_line(conn))
            except (ValueError, ConnectionError, OSError):
                return self._refuse(conn, "Bad handshake.")
            if self.auth.locked_out(ip):
                return self._refuse(conn, "Too many wrong attempts. Try again in a few minutes.")
            token = hello.get("token") if isinstance(hello, dict) else None
            if not isinstance(token, str) or not self.auth.valid(token):
                self.auth.record_failure(ip)
                return self._refuse(conn, "Wrong token.")
            role = hello.get("role")
            conn.settimeout(None)
            if role == "phone":
                self._serve_phone(conn)
            elif role == "viewer":
                self._serve_viewer(conn)
            else:
                self._refuse(conn, "Unknown role.")
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _refuse(conn: socket.socket, why: str) -> None:
        try:
            conn.sendall(json.dumps({"ok": False, "error": why}).encode() + b"\n")
            conn.shutdown(socket.SHUT_WR)   # a gentle close, so the answer is not lost to a reset
            conn.settimeout(2)
            while conn.recv(4096):
                pass
        except OSError:
            pass

    def _to_phone(self, kind: bytes, payload: bytes) -> None:
        with self._lock:
            phone = self._phone
        if phone is None:
            return
        with self._phone_send:
            try:
                phone.sendall(frame(kind, payload))
            except OSError:
                pass

    def _viewer_count_to_phone(self) -> None:
        with self._lock:
            n = len(self._viewers)
        self._to_phone(b"C", json.dumps({"t": "viewers", "n": n}).encode())

    def _serve_phone(self, conn: socket.socket) -> None:
        with self._lock:
            old, self._phone = self._phone, conn
            self._info = self._config = None
        if old is not None:
            try:
                old.close()   # a newer connection from the phone replaces an older one
            except OSError:
                pass
        conn.sendall(json.dumps({"ok": True}).encode() + b"\n")
        log.info("phone video link connected")
        self._viewer_count_to_phone()
        try:
            while True:
                try:
                    got = read_frame(conn)
                except (ValueError, OSError):
                    return
                if got is None:
                    return
                kind, payload = got
                if kind not in FROM_PHONE:
                    continue
                flags = payload[0] if kind == b"V" and payload else 0
                with self._lock:
                    if kind == b"H":
                        self._info = payload
                    elif kind == b"V" and flags & CODEC_CONFIG:
                        self._config = payload
                    viewers = list(self._viewers)
                behind = False
                for v in viewers:
                    if not v.push(kind, payload, flags):
                        behind = True
                if behind:
                    self._to_phone(b"C", b'{"t":"keyframe"}')
        finally:
            with self._lock:
                if self._phone is conn:
                    self._phone = None
            log.info("phone video link closed")

    def _serve_viewer(self, conn: socket.socket) -> None:
        with self._lock:
            if len(self._viewers) >= self.max_viewers:
                full = True
            else:
                full = False
                viewer = _Viewer(conn)
                self._viewers.append(viewer)
                info, config = self._info, self._config
        if full:
            return self._refuse(conn, "Too many windows are showing the phone.")
        conn.sendall(json.dumps({"ok": True}).encode() + b"\n")
        self.hub.add_watcher()          # the phone starts sharing (over its web link) if it was idle
        if info:
            viewer.push(b"H", info)
        if config:
            viewer.push(b"V", config, CODEC_CONFIG)
        viewer.need_key = True
        self._viewer_count_to_phone()
        self._to_phone(b"C", b'{"t":"keyframe"}')
        try:
            while viewer.alive:
                try:
                    got = read_frame(conn)
                except (ValueError, OSError):
                    return
                if got is None:
                    return
                kind, payload = got
                if kind in FROM_VIEWER:
                    self._to_phone(kind, payload)
        finally:
            viewer.close()
            with self._lock:
                if viewer in self._viewers:
                    self._viewers.remove(viewer)
            self.hub.remove_watcher()
            self._viewer_count_to_phone()
