"""The phone on the PC: a window shaped like the phone, live and smooth, that you use with the mouse and keyboard.

The phone streams its screen as H.264 video (or JPEG screenshots when it cannot record) over the live link
(streamrelay.py). The video is decoded with OpenCV's FFmpeg (the LGPL build that ships with opencv-python): the
packets are handed to it through a socket on 127.0.0.1, which is how OpenCV reads a live stream.

Mouse: press, drag and release are a finger on the screen, live. Right click is Back, middle click is Home, the wheel
scrolls. Keyboard: typing types on the phone, Esc is Back, Ctrl+V pastes the PC's clipboard.
"""
import json
import os
import queue
import socket
import threading
import time
from collections import deque
from pathlib import Path

# Before OpenCV opens a stream: no buffering, decode as soon as a picture arrives.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                      "fflags;nobuffer|flags;low_delay|probesize;32|analyzeduration;0|max_delay;0")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from . import config, gestures  # noqa: E402
from .streamrelay import frame, read_frame, read_line  # noqa: E402

QUALITY = {   # name: (long side in pixels, 0 = the phone's own; bits per second)
    "720p": 1280, "1080p": 1920, "Full": 0,
}
BITRATES = {"Standard": 5_000_000, "High": 10_000_000, "Maximum": 20_000_000}
DEFAULTS = {"size": "1080p", "fps": 60, "bitrate": "High"}


def load_prefs() -> dict:
    try:
        data = json.loads((config.data_dir() / "phone-window.json").read_text(encoding="utf-8"))
        return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_prefs(prefs: dict) -> None:
    try:
        (config.data_dir() / "phone-window.json").write_text(json.dumps(prefs), encoding="utf-8")
    except OSError:
        pass


def quality_message(prefs: dict) -> dict:
    return {"t": "quality", "max_size": QUALITY.get(prefs["size"], 1920), "fps": int(prefs["fps"]),
            "bitrate": BITRATES.get(prefs["bitrate"], 10_000_000)}


PRIME = 60   # OpenCV's FFmpeg reads about 50 pictures before it starts: give it the first one that often


class _Decoder:
    """H.264 in, pictures out. OpenCV reads the stream from a socket on 127.0.0.1 that this feeds.

    FFmpeg only starts once it has seen some 50 pictures, which on a still phone screen takes many seconds. So the
    first key frame (a complete picture) is handed over PRIME times at once: it starts at once, showing that picture.
    """

    def __init__(self, on_picture):
        self.on_picture = on_picture
        self.packets: queue.Queue = queue.Queue(maxsize=600)
        self.alive = True
        self.config = b""        # the codec config (SPS/PPS) seen so far
        self.started = False     # a key frame has been handed over (with the priming copies)
        self.skip = PRIME        # the priming copies are not counted as pictures
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        port = self._server.getsockname()[1]
        threading.Thread(target=self._feed, name="phone-feed", daemon=True).start()
        threading.Thread(target=self._decode, args=(port,), name="phone-decode", daemon=True).start()

    def push(self, data: bytes) -> None:
        try:
            self.packets.put_nowait(data)
        except queue.Full:
            pass

    def packet(self, flags: int, data: bytes) -> None:
        """One packet from the phone: config, key frame or other picture."""
        if flags & 2:
            self.config = data
            return
        if not self.started:
            if not flags & 1 or not self.config:
                return   # nothing can be decoded before the first key frame
            self.started = True
            self.push(self.config + data * PRIME)
            return
        self.push(data)

    def _feed(self):
        try:
            self._server.settimeout(15)
            conn, _ = self._server.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            while self.alive:
                data = self.packets.get()
                if data is None:
                    break
                conn.sendall(data)
            conn.close()
        except OSError:
            pass
        finally:
            self.alive = False
            self._server.close()

    def _decode(self, port):
        cap = cv2.VideoCapture(f"tcp://127.0.0.1:{port}", cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
        try:
            while self.alive:
                ok, picture = cap.read()
                if not ok:
                    break
                if self.skip > 1:
                    self.skip -= 1
                    continue
                self.skip = 0
                self.on_picture(picture)
        finally:
            cap.release()
            self.alive = False

    def close(self):
        self.alive = False
        try:
            self.packets.put_nowait(None)
        except queue.Full:
            pass


class PhoneLink:
    """The Mirra window's side of the live link: pictures from the phone, input to it."""

    def __init__(self, host: str, port: int, token: str):
        self.host, self.port, self.token = host, port, token
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._decoder: _Decoder | None = None
        self.picture = None             # the newest picture (BGR)
        self.seq = 0
        self.info: dict = {}
        self.status = "Connecting to your phone..."
        self.times: deque = deque(maxlen=90)
        self.active = False

    def start(self):
        self.active = True
        threading.Thread(target=self._run, name="phone-link", daemon=True).start()

    def stop(self):
        self.active = False
        with self._lock:
            sock, self._sock = self._sock, None
            decoder, self._decoder = self._decoder, None
        if decoder:
            decoder.close()
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def fps(self) -> float:
        now = time.monotonic()
        recent = [t for t in self.times if now - t < 2]
        return (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 2 and recent[-1] > recent[0] else 0.0

    def _picture(self, picture):
        self.picture = picture
        self.seq += 1
        self.times.append(time.monotonic())
        self.status = ""

    def send(self, kind: bytes, message: dict) -> None:
        with self._lock:
            sock = self._sock
        if sock is None:
            return
        try:
            sock.sendall(frame(kind, json.dumps(message).encode()))
        except OSError:
            pass

    def _run(self):
        while self.active:
            try:
                sock = socket.create_connection((self.host, self.port), timeout=8)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.sendall(json.dumps({"token": self.token, "role": "viewer"}).encode() + b"\n")
                answer = json.loads(read_line(sock))
                if not answer.get("ok"):
                    self.status = answer.get("error") or "Mirra refused the connection."
                    sock.close()
                    time.sleep(3)
                    continue
                sock.settimeout(None)
                with self._lock:
                    self._sock = sock
                self.status = "Waiting for your phone..."
                self._receive(sock)
            except (OSError, ValueError) as exc:
                if self.active:
                    self.status = f"Mirra is not answering ({exc}). Trying again..."
            finally:
                with self._lock:
                    decoder, self._decoder = self._decoder, None
                    self._sock = None
                if decoder:
                    decoder.close()
            if self.active:
                time.sleep(1.5)

    def _receive(self, sock):
        while self.active:
            got = read_frame(sock)
            if got is None:
                return
            kind, payload = got
            if kind == b"H":
                info = json.loads(payload)
                with self._lock:
                    old, self._decoder = self._decoder, (_Decoder(self._picture) if info.get("codec") == "h264" else None)
                if old:
                    old.close()
                self.info = info
            elif kind == b"V" and payload:
                decoder = self._decoder
                if decoder is not None and decoder.alive:
                    decoder.packet(payload[0], payload[1:])
            elif kind == b"J":
                picture = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
                if picture is not None:
                    self._picture(picture)


# -- the window ----------------------------------------------------------------------------------------------
def open_window(app, local, device: str = "", size: tuple[int, int] = (0, 0)):
    """Opens (or brings to the front) the phone window."""
    win = getattr(app, "phone_window", None)
    if win is not None and win.winfo_exists():
        win.deiconify()
        win.lift()
        win.focus_force()
        return win
    app.phone_window = PhoneWindow(app, local, device, size)
    return app.phone_window


def _icon_font(root) -> str | None:
    from tkinter import font
    families = set(font.families(root))
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return None


class PhoneWindow:
    TOOLBAR = 56

    def __init__(self, app, local, device: str, size: tuple[int, int]):
        import tkinter as tk

        from PIL import Image, ImageTk
        self.Image, self.ImageTk = Image, ImageTk
        self.app, self.local = app, local
        self.prefs = load_prefs()
        root = app.root
        self.win = win = tk.Toplevel(root)
        win.title(f"Mirra - {device}" if device else "Mirra - your phone")
        win.configure(bg="#000000")
        icon = Path(__file__).resolve().parent / "assets" / "mirra.ico"
        if icon.exists():
            try:
                win.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.aspect = (size[0] / size[1]) if size[0] and size[1] else 9 / 19.5
        self._place_window()
        win.minsize(260, 360)

        bar = tk.Frame(win, bg="#0b0d12", width=self.TOOLBAR)
        bar.pack(side="right", fill="y")      # first, so the picture cannot take its room
        bar.pack_propagate(False)
        self.canvas = tk.Canvas(win, bg="#000000", highlightthickness=0, cursor="hand2", takefocus=1)
        self.canvas.pack(side="left", fill="both", expand=True)
        glyphs = _icon_font(root)
        buttons = [("\uE72B", "Back  (right click, Esc)", lambda: self.key("back")),
                   ("\uE80F", "Home  (middle click)", lambda: self.key("home")),
                   ("\uE7C4", "Recent apps", lambda: self.key("recents")),
                   ("\uE995", "Volume up", lambda: self.key("volup")), ("\uE993", "Volume down", lambda: self.key("voldown")),
                   ("\uE722", "Save a screenshot on this PC", self.screenshot),
                   ("\uE712", "More", self.more_menu)]
        self.tips = tk.Label(win, bg="#1c2030", fg="#f1f3f8", font=("Segoe UI", 9), padx=8, pady=3)
        for glyph, tip, action in buttons:
            b = tk.Label(bar, text=glyph if glyphs else tip[0], font=(glyphs, 15) if glyphs else ("Segoe UI", 12, "bold"),
                         fg="#c9cdd6", bg="#0b0d12", cursor="hand2", pady=10)
            b.pack(fill="x", pady=1)
            b.bind("<Button-1>", lambda e, a=action: a())
            b.bind("<Enter>", lambda e, w=b, t=tip: self._hover(w, t, True))
            b.bind("<Leave>", lambda e, w=b: self._hover(w, "", False))
        self.fps_label = tk.Label(bar, text="", fg="#8e96a8", bg="#0b0d12", font=("Segoe UI", 8))
        self.fps_label.pack(side="bottom", pady=8)

        try:   # Windows timers tick every 15 ms by default: too coarse for 60 pictures a second
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
            self._fine_timer = True
        except Exception:
            self._fine_timer = False
        self.photo = None
        self.shown = -1
        self.rect = (0, 0, 0, 0)
        self.pointer_down = False
        self.last_move = 0.0
        self.typed = ""
        self._wheel_notches = 0.0
        c = self.canvas
        c.bind("<ButtonPress-1>", self._down)
        c.bind("<B1-Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._up)
        c.bind("<Button-3>", lambda e: self.key("back"))
        c.bind("<Button-2>", lambda e: self.key("home"))
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<Configure>", lambda e: self._render(force=True))
        win.bind("<Key>", self._key)
        win.bind("<Control-v>", self._paste)
        win.protocol("WM_DELETE_WINDOW", self.close)

        host = "127.0.0.1" if local.cfg.loopback else local.base().split("//", 1)[1].rsplit(":", 1)[0]
        self.link = PhoneLink(host, local.cfg.port + 1, local.cfg.token)
        self.link.start()
        self._sent_quality = False
        self.canvas.focus_set()
        self._tick()

    # -- placement --------------------------------------------------------------------------------
    def _place_window(self):
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        h = int(sh * 0.85)
        w = int(h * self.aspect) + self.TOOLBAR
        if w > sw * 0.9:   # sideways phone
            w = int(sw * 0.75)
            h = int((w - self.TOOLBAR) / self.aspect)
        self.win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")

    def _fit_to(self, aspect: float):
        """The phone turned (or its picture changed shape): reshape the window, keeping its height."""
        if abs(aspect - self.aspect) < 0.01:
            return
        self.aspect = aspect
        h = self.canvas.winfo_height()
        sw = self.win.winfo_screenwidth()
        w = int(h * aspect) + self.TOOLBAR
        if w > sw * 0.95:
            w = int(sw * 0.8)
            h = int((w - self.TOOLBAR) / aspect)
        self.win.geometry(f"{w}x{h}")

    def _hover(self, widget, tip, on):
        widget.config(fg="#ffffff" if on else "#c9cdd6", bg="#1c2030" if on else "#0b0d12")
        if on:
            self.tips.config(text=tip)
            self.tips.place(relx=1.0, x=-self.TOOLBAR - 6, y=widget.winfo_y() + 8, anchor="ne")
        else:
            self.tips.place_forget()

    # -- drawing ----------------------------------------------------------------------------------
    def _tick(self):
        if not self.win.winfo_exists():
            return
        link = self.link
        if not self._sent_quality and link._sock is not None:
            link.send(b"C", quality_message(self.prefs))
            self._sent_quality = True
        if link.info.get("width") and link.info.get("height"):
            self._fit_to(link.info["width"] / link.info["height"])
        self._render()
        fps = link.fps()
        mode = "video" if link.info.get("codec") == "h264" else ("photos" if link.info else "")
        self.fps_label.config(text=f"{fps:.0f} fps\n{mode}" if fps else mode)
        self.win.after(4, self._tick)

    def _render(self, force=False):
        link = self.link
        picture = link.picture
        c = self.canvas
        cw, ch = c.winfo_width(), c.winfo_height()
        if picture is None:
            c.delete("all")
            c.create_text(cw // 2, ch // 2, text=link.status or "Waiting for your phone...", fill="#c9cdd6",
                          width=max(120, cw - 40), justify="center", font=("Segoe UI", 11))
            self.photo = None
            return
        if link.seq == self.shown and not force:
            return
        self.shown = link.seq
        ph, pw = picture.shape[:2]
        scale = min(cw / pw, ch / ph)
        w, h = max(1, int(pw * scale)), max(1, int(ph * scale))
        small = cv2.resize(picture, (w, h), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        image = self.Image.frombuffer("RGB", (w, h), rgb.tobytes(), "raw", "RGB", 0, 1)
        x0, y0 = (cw - w) // 2, (ch - h) // 2
        if self.photo is not None and (self.photo.width(), self.photo.height()) == (w, h):
            self.photo.paste(image)
        else:
            self.photo = self.ImageTk.PhotoImage(image)
            c.delete("all")
            c.create_image(x0, y0, image=self.photo, anchor="nw", tags="picture")
        if self.rect[:2] != (x0, y0):
            c.coords("picture", x0, y0)
        c.tag_raise("finger")
        self.rect = (x0, y0, w, h)

    # -- input -----------------------------------------------------------------------------------
    def _where(self, event):
        x0, y0, w, h = self.rect
        if not w or not h:
            return None
        return min(1.0, max(0.0, (event.x - x0) / w)), min(1.0, max(0.0, (event.y - y0) / h))

    def _touch(self, action, pos, event=None):
        self.link.send(b"I", {"t": "touch", "a": action, "x": round(pos[0], 4), "y": round(pos[1], 4)})
        c = self.canvas
        if action == "up" or event is None:
            c.after(120, lambda: c.delete("finger"))
            return
        r = 13   # shows the touch at once, before the phone's picture catches up
        if c.find_withtag("finger"):
            c.coords("finger", event.x - r, event.y - r, event.x + r, event.y + r)
        else:
            c.create_oval(event.x - r, event.y - r, event.x + r, event.y + r, outline="#ffffff", width=2,
                          fill="#7c5cff", stipple="gray50", tags="finger")

    def _down(self, event):
        self.canvas.focus_set()
        pos = self._where(event)
        if pos:
            self.pointer_down = True
            self._touch("down", pos, event)

    def _move(self, event):
        now = time.monotonic()
        if not self.pointer_down or now - self.last_move < 0.004:
            return
        pos = self._where(event)
        if pos:
            self.last_move = now
            self._touch("move", pos, event)

    def _up(self, event):
        pos = self._where(event)
        if pos and self.pointer_down:
            self._touch("up", pos)
        self.pointer_down = False

    def _wheel(self, event):
        pos = self._where(event)
        if not pos:
            return
        if event.state & 0x4:   # Ctrl + wheel: pinch to zoom
            self.link.send(b"I", gestures.pinch(pos[0], pos[1], event.delta > 0))
            return
        # notches that arrive together become one smooth drag
        if not self._wheel_notches:
            self.win.after(30, lambda p=pos: self._wheel_flush(p))
        self._wheel_notches += event.delta / 120

    def _wheel_flush(self, pos):
        notches, self._wheel_notches = self._wheel_notches, 0.0
        if notches:
            self.link.send(b"I", gestures.scroll(pos[0], pos[1], notches))

    def key(self, name: str):
        self.link.send(b"I", {"t": "key", "k": name})

    def _key(self, event):
        if event.state & 0x4 and event.keysym.lower() == "v":
            return   # Ctrl+V: handled by _paste
        what = gestures.key(event.keysym, event.char)
        if not what:
            return
        kind, value = what
        if kind == "key":
            self._flush_text()
            self.key(value)
            return
        if not self.typed:
            self.win.after(25, self._flush_text)
        self.typed += value

    def _flush_text(self):
        if self.typed:
            text, self.typed = self.typed[:500], self.typed[500:]
            self.link.send(b"I", {"t": "text", "s": text})

    def _paste(self, _event=None):
        try:
            text = self.win.clipboard_get()
        except Exception:
            return "break"
        if text:
            self.link.send(b"I", {"t": "text", "s": text[:500]})
        return "break"

    # -- tools -----------------------------------------------------------------------------------
    def screenshot(self):
        picture = self.link.picture
        if picture is None:
            return
        folder = Path.home() / "Pictures" / "Mirra"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / time.strftime("Phone %Y-%m-%d %H.%M.%S.png")
        cv2.imwrite(str(path), picture)
        self.tips.config(text="Saved in Pictures\\Mirra")
        self.tips.place(relx=0.5, rely=0.96, anchor="s")
        self.win.after(2500, self.tips.place_forget)

    def more_menu(self):
        import tkinter as tk
        menu = tk.Menu(self.win, tearoff=0, bg="#141721", fg="#f1f3f8", activebackground="#7c5cff",
                       activeforeground="#ffffff", bd=0)
        for text, name in (("Notifications", "notifications"), ("Quick settings", "quicksettings"),
                           ("Lock the phone", "lock"), ("Power menu", "power"), ("Wake the screen", "wake")):
            menu.add_command(label=text, command=lambda n=name: self.key(n))
        menu.add_separator()
        menu.add_command(label="Paste this PC's clipboard  (Ctrl+V)", command=self._paste)
        menu.add_command(label="Picture quality...", command=self.quality_menu)
        x, y = self.win.winfo_pointerxy()
        menu.tk_popup(x, y)

    def quality_menu(self):
        import tkinter as tk
        menu = tk.Menu(self.win, tearoff=0, bg="#141721", fg="#f1f3f8", activebackground="#7c5cff",
                       activeforeground="#ffffff", bd=0)
        size, fps, rate = tk.StringVar(value=self.prefs["size"]), tk.IntVar(value=self.prefs["fps"]), tk.StringVar(value=self.prefs["bitrate"])

        def apply():
            self.prefs.update(size=size.get(), fps=fps.get(), bitrate=rate.get())
            save_prefs(self.prefs)
            self.link.send(b"C", quality_message(self.prefs))
        menu.add_command(label="Sharpness", state="disabled")
        for name in QUALITY:
            menu.add_radiobutton(label=f"   {name}", variable=size, value=name, command=apply)
        menu.add_separator()
        menu.add_command(label="Smoothness", state="disabled")
        for n in (30, 60):
            menu.add_radiobutton(label=f"   {n} frames a second", variable=fps, value=n, command=apply)
        menu.add_separator()
        menu.add_command(label="Picture quality", state="disabled")
        for name in BITRATES:
            menu.add_radiobutton(label=f"   {name}", variable=rate, value=name, command=apply)
        x, y = self.win.winfo_pointerxy()
        menu.tk_popup(x, y)

    def close(self):
        self.link.stop()
        if self._fine_timer:
            try:
                import ctypes
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
        self.win.destroy()

    def winfo_exists(self):
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    def deiconify(self):
        self.win.deiconify()

    def lift(self):
        self.win.lift()

    def focus_force(self):
        self.win.focus_force()
