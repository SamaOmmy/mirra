"""The Samantha window on the PC (Samantha.exe).

One place for everything on the PC: first-time setup, turning Samantha on and off, connecting a phone with a code,
seeing and using the Android phone, sound, and updates. The mirroring itself runs in the background service, so it
keeps working while this window is closed.

Tk is single-threaded: anything slow (the network, PowerShell, Tailscale) runs on a worker thread and hands its
result back through `App.later()`, which the window runs on its own thread.
"""
import ctypes
import io
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from collections import deque
from pathlib import Path
from tkinter import messagebox

import qrcode
from PIL import Image, ImageTk

from . import APP_NAME, __version__, autostart, config, gestures, proc, shortcuts, tailscale, updater
from .client import Local, Offline, Refused, jpeg_frames

TITLE = "Samantha"
APK_URL = f"https://github.com/{updater.REPO}/releases/latest/download/SamanthaPhone.apk"
PROJECT_URL = f"https://github.com/{updater.REPO}"
LOCK_NAME = r"Local\SamanthaScreenMirrorWindow"
ICON = Path(__file__).resolve().parent / "app.ico"

BG, SIDE, CARD, LINE = "#101218", "#0b0d12", "#191c24", "#2a2f3b"
TEXT, MUTED, ACCENT, ACCENT_HI = "#eceef4", "#9aa1b1", "#8b6cff", "#a08aff"
OK, WARN, BAD = "#34d399", "#fbbf24", "#f87171"
FONT = "Segoe UI"


# -- small widgets ---------------------------------------------------------------------------------
class Ui:
    """Sizes in pixels at 100% Windows scaling, multiplied up on high-DPI screens."""
    scale = 1.0

    @classmethod
    def px(cls, value: float) -> int:
        return int(round(value * cls.scale))


def label(parent, text="", size=10, color=TEXT, bold=False, bg=CARD, wrap=0, **kw):
    font = (FONT + (" Semibold" if bold else ""), size)
    return tk.Label(parent, text=text, font=font, fg=color, bg=bg, justify="left", anchor="w",
                    wraplength=Ui.px(wrap) if wrap else 0, **kw)


def button(parent, text, command, kind="primary", bg=CARD):
    colors = {"primary": (ACCENT, "#ffffff", ACCENT_HI), "plain": (LINE, TEXT, "#353b49"),
              "danger": ("#3a1d22", BAD, "#4a242b")}[kind]
    b = tk.Button(parent, text=text, command=command, font=(FONT + " Semibold", 10), fg=colors[1], bg=colors[0],
                  activebackground=colors[2], activeforeground=colors[1], relief="flat", bd=0, cursor="hand2",
                  padx=Ui.px(14), pady=Ui.px(6), highlightthickness=0, disabledforeground=MUTED)
    b.bind("<Enter>", lambda e: b.config(bg=colors[2]) if str(b["state"]) != "disabled" else None)
    b.bind("<Leave>", lambda e: b.config(bg=colors[0]))
    return b


def card(parent, title=None):
    outer = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
    inner = tk.Frame(outer, bg=CARD)
    inner.pack(fill="both", expand=True, padx=Ui.px(18), pady=Ui.px(14))
    if title:
        label(inner, title, 12, bold=True).pack(anchor="w", pady=(0, Ui.px(6)))
    return outer, inner


class Toggle(tk.Canvas):
    """An on/off switch."""

    def __init__(self, parent, command, bg=CARD):
        self.w, self.h = Ui.px(42), Ui.px(24)
        super().__init__(parent, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2")
        self.on = False
        self.enabled = True
        self.command = command
        self.bind("<Button-1>", self._click)
        self._draw()

    def set(self, on: bool) -> None:
        if on != self.on:
            self.on = on
            self._draw()

    def enable(self, enabled: bool) -> None:
        self.enabled = enabled
        self._draw()

    def _click(self, _event):
        if self.enabled:
            self.set(not self.on)
            self.command(self.on)

    def _draw(self):
        self.delete("all")
        w, h, r = self.w, self.h, self.h / 2
        fill = (ACCENT if self.on else LINE) if self.enabled else "#22262f"
        self.create_oval(0, 0, h, h, fill=fill, outline=fill)
        self.create_oval(w - h, 0, w, h, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        pad = Ui.px(3)
        x = w - h + pad if self.on else pad
        self.create_oval(x, pad, x + h - 2 * pad, h - pad, fill="#ffffff" if self.enabled else MUTED, outline="")


def qr_image(text: str, size: int) -> ImageTk.PhotoImage:
    qr = qrcode.QRCode(border=2, box_size=8, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
    return ImageTk.PhotoImage(img.resize((size, size), Image.NEAREST))


def ago(timestamp: float) -> str:
    seconds = max(0, time.time() - timestamp)
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    return time.strftime("%H:%M", time.localtime(timestamp))


# -- the window ------------------------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.closing = False
        self._calls: queue.Queue = queue.Queue()
        self.wake = threading.Event()
        self.snap: dict = {}
        self._snap_lock = threading.Lock()
        self.local: Local | None = None
        self.release: updater.Release | None = None
        self.busy = ""   # what a long action is doing right now ("" when idle)

        root.title(TITLE)
        root.configure(bg=BG)
        width = min(Ui.px(1080), root.winfo_screenwidth() - Ui.px(40))
        height = min(Ui.px(720), root.winfo_screenheight() - Ui.px(90))
        root.geometry(f"{width}x{height}+{max(0, (root.winfo_screenwidth() - width) // 2)}+{Ui.px(10)}")
        root.minsize(min(width, Ui.px(820)), min(height, Ui.px(520)))
        if ICON.exists():
            try:
                root.iconbitmap(default=str(ICON))
            except tk.TclError:
                pass

        side = tk.Frame(root, bg=SIDE, width=Ui.px(200))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        label(side, "Samantha", 17, bold=True, bg=SIDE).pack(anchor="w", padx=Ui.px(20), pady=(Ui.px(22), 0))
        label(side, "Screen Mirror", 10, MUTED, bg=SIDE).pack(anchor="w", padx=Ui.px(20), pady=(0, Ui.px(22)))
        self.nav: dict[str, tk.Label] = {}
        for key, text in (("home", "Home"), ("phone", "My phone"), ("settings", "Settings")):
            item = label(side, text, 11, MUTED, bg=SIDE, cursor="hand2", padx=Ui.px(20), pady=Ui.px(9))
            item.pack(fill="x")
            item.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.nav[key] = item
        label(side, f"v{__version__}", 9, MUTED, bg=SIDE).pack(side="bottom", anchor="w", padx=Ui.px(20), pady=Ui.px(16))

        self.body = tk.Frame(root, bg=BG)
        self.body.pack(side="left", fill="both", expand=True)
        self.pages = {"setup": SetupPage(self), "home": HomePage(self), "phone": PhonePage(self),
                      "settings": SettingsPage(self)}
        self.current = None

        self._open_client()
        self.show("home" if self.ready() else "setup")
        threading.Thread(target=self._poll, name="status", daemon=True).start()
        if self.local and self.local.cfg.update_check:
            self.check_updates(quiet=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<MouseWheel>", lambda e: self.pages[self.current].wheel(e) if self.current else None)
        root.after(100, self._pump)

    # -- plumbing ----------------------------------------------------------------------------------
    def later(self, fn, *args) -> None:
        """Run fn(*args) on the window's thread."""
        self._calls.put((fn, args))

    def background(self, work, done=None) -> None:
        """Run work() on a worker thread, then done(result, error) on the window's thread."""
        def run():
            try:
                result, error = work(), None
            except Exception as exc:   # shown to the user by `done`
                result, error = None, exc
            if done:
                self.later(done, result, error)
        threading.Thread(target=run, daemon=True).start()

    def _pump(self):
        try:
            while True:
                fn, args = self._calls.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        if self.current:
            with self._snap_lock:
                snap = dict(self.snap)
            self.pages[self.current].refresh(snap)
        if not self.closing:
            self.root.after(150, self._pump)

    def _open_client(self) -> None:
        try:
            if self.local:
                self.local.reload()
            else:
                self.local = Local()
        except config.ConfigError:
            self.local = None

    def ready(self) -> bool:
        """Set up: there is a token, and the background service is installed (or already answering)."""
        if not self.local:
            return False
        with self._snap_lock:
            if "server" in self.snap:
                return True
            auto = self.snap.get("autostart")
        return (auto or autostart.status()) != "missing"

    def _poll(self):
        slow_at = 0.0
        while not self.closing:
            snap: dict = {}
            local = self.local
            if local:
                try:
                    snap["server"] = local.get("/api/state")
                    snap["phone"] = local.get("/api/phone/state")
                    snap["pair"] = local.get("/api/pair/code")
                except Offline:
                    snap["server_error"] = "offline"
                except Refused as exc:
                    snap["server_error"] = "refused" if exc.code in (401, 429) else str(exc)
            if time.monotonic() >= slow_at:
                snap["autostart"] = autostart.status()
                snap["tailscale"] = tailscale_info()
                slow_at = time.monotonic() + 10
            with self._snap_lock:
                for key in ("server", "phone", "pair", "server_error"):
                    self.snap.pop(key, None)
                self.snap.update(snap)
            self.wake.wait(1.5)
            self.wake.clear()

    def refresh_soon(self, slow: bool = False) -> None:
        if slow:
            with self._snap_lock:
                self.snap.pop("autostart", None)
        self.wake.set()

    def show(self, key: str) -> None:
        if key != "setup" and not self.ready():
            key = "setup"
        if self.current == key:
            return
        if self.current:
            self.pages[self.current].hide()
        self.current = key
        for k, item in self.nav.items():
            item.config(fg=TEXT if k == key else MUTED, bg="#191c24" if k == key else SIDE)
        self.pages[key].show()

    def close(self):
        self.closing = True
        self.pages["phone"].hide()
        self.root.destroy()

    # -- actions used by several pages ---------------------------------------------------------------
    def check_updates(self, quiet=False):
        def done(release, error):
            if error:
                if not quiet:
                    messagebox.showinfo(TITLE, f"Could not check for updates: {error}")
                return
            self.release = release
            if not quiet and not release:
                messagebox.showinfo(TITLE, f"You have the newest version (v{__version__}).")
        self.background(updater.available, done)

    def install_update(self):
        release = self.release
        if not release or self.busy:
            return
        mode = updater.install_mode()
        if mode == "other":
            webbrowser.open(release.url)
            return
        self.busy = f"Downloading version {release.version}..."

        def work():
            if mode == "exe":
                updater.update_exe(release, relaunch=Path(sys.executable))
            else:
                updater.update_git(release)
                updater.restart_service()
            return mode

        def done(result, error):
            self.busy = ""
            if error:
                messagebox.showerror(TITLE, f"The update did not work: {error}")
            elif result == "exe":
                # The new version is swapped in once this window is gone, and then it opens again by itself.
                self.close()
            else:
                messagebox.showinfo(TITLE, f"Updated to v{release.version}. Close this window and open it again.")
        self.background(work, done)

    def restart_service(self, why: str):
        self.busy = why

        def done(_result, error):
            self.busy = ""
            self._open_client()
            self.refresh_soon(slow=True)
            if error:
                messagebox.showerror(TITLE, str(error))
        self.background(lambda: updater.restart_service() or None, done)


def tailscale_info() -> dict:
    info = {"installed": bool(tailscale.find_cli()), "state": "", "ip": "", "name": ""}
    if not info["installed"]:
        return info
    try:
        st = tailscale.status()
        info["state"] = tailscale.backend_state(st)
        info["name"] = tailscale.dns_name(st).split(".")[0]
        if info["state"] == "Running":
            info["ip"] = tailscale.tailscale_ip()
    except tailscale.BindError:
        info["state"] = "Stopped"
    return info


# -- pages -----------------------------------------------------------------------------------------
class Page:
    title = ""
    scrolls = True   # the page scrolls when it is taller than the window

    def __init__(self, app: App):
        self.app = app
        self.frame = tk.Frame(app.body, bg=BG)
        self.content = self.frame
        if self.scrolls:
            self.canvas = tk.Canvas(self.frame, bg=BG, highlightthickness=0)
            self.bar = tk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
            self.content = tk.Frame(self.canvas, bg=BG)
            inside = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
            self.canvas.configure(yscrollcommand=self._scrolled)
            self.content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
            self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(inside, width=e.width))
            self.canvas.pack(side="left", fill="both", expand=True)
        if self.title:
            label(self.content, self.title, 20, bold=True, bg=BG).pack(anchor="w", padx=Ui.px(28), pady=(Ui.px(24), Ui.px(12)))
        self.build()

    def _scrolled(self, first, last):
        if float(first) <= 0 and float(last) >= 1:
            self.bar.pack_forget()
        elif not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", before=self.canvas)
        self.bar.set(first, last)

    def wheel(self, event):
        if self.scrolls and self.bar.winfo_ismapped():
            self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

    def build(self):
        pass

    def show(self):
        self.frame.pack(fill="both", expand=True)

    def hide(self):
        self.frame.pack_forget()

    def refresh(self, snap: dict):
        pass

    def section(self, title=None, **pack):
        outer, inner = card(self.content, title)
        outer.pack(fill="x", padx=Ui.px(28), pady=(0, Ui.px(14)), **pack)
        return inner


class SetupPage(Page):
    title = "Welcome to Samantha"

    def build(self):
        label(self.content, "Samantha shows this PC on your phone, and your Android phone on this PC. Everything goes "
              "straight between your own devices through Tailscale, a free private network. No cloud, no accounts "
              "with us.", 10, MUTED, bg=BG, wrap=720).pack(anchor="w", padx=Ui.px(28), pady=(0, Ui.px(16)))

        box = self.section("1.  Tailscale")
        self.ts_text = label(box, "Checking...", 10, MUTED, wrap=700)
        self.ts_text.pack(anchor="w")
        row = tk.Frame(box, bg=CARD)
        row.pack(anchor="w", pady=(Ui.px(10), 0))
        self.install_btn = button(row, "Install Tailscale", self.install_tailscale)
        self.install_btn.pack(side="left", padx=(0, Ui.px(8)))
        button(row, "Check again", lambda: self.app.refresh_soon(slow=True), "plain").pack(side="left")

        box = self.section("2.  Start Samantha")
        label(box, "Samantha runs quietly in the background and starts by itself when you sign in to Windows. "
              "You can turn it off at any time.", 10, MUTED, wrap=700).pack(anchor="w")
        self.start_btn = button(box, "Start Samantha", self.start)
        self.start_btn.pack(anchor="w", pady=(Ui.px(10), 0))
        self.start_text = label(box, "", 10, MUTED, wrap=700)
        self.start_text.pack(anchor="w", pady=(Ui.px(6), 0))

    def refresh(self, snap):
        ts = snap.get("tailscale")
        running = bool(ts and ts["state"] == "Running")
        if ts is None:
            text, color = "Checking...", MUTED
        elif not ts["installed"]:
            text, color = "Tailscale is not installed yet. Install it, open it and sign in (it is free).", WARN
        elif not running:
            text, color = ("Tailscale is installed but not signed in or switched on. Open Tailscale from the Start "
                           "menu or the tray, sign in, then click Check again."), WARN
        else:
            text, color = f"Connected as {ts['name'] or ts['ip']} ({ts['ip']}).", OK
        self.ts_text.config(text=text, fg=color)
        self.install_btn.config(state="disabled" if ts and ts["installed"] else "normal")
        self.start_btn.config(state="normal" if running and not self.app.busy else "disabled")
        if self.app.busy:
            self.start_text.config(text=self.app.busy)

    def install_tailscale(self):
        import shutil
        if not shutil.which("winget"):
            webbrowser.open(tailscale.DOWNLOAD_URL)
            return
        self.app.busy = "Installing Tailscale (Windows may ask for permission)..."

        def done(result, error):
            self.app.busy = ""
            if error or getattr(result, "returncode", 1) != 0:
                webbrowser.open(tailscale.DOWNLOAD_URL)
            self.app.refresh_soon(slow=True)
        self.app.background(lambda: proc.run(["winget", "install", "--id", "Tailscale.Tailscale", "-e",
                                              "--accept-package-agreements", "--accept-source-agreements"],
                                             capture_output=True, timeout=900), done)

    def start(self):
        self.app.busy = "Starting..."

        def work():
            config.ensure_env()
            autostart.install(start_now=True)
            shortcuts.update(create=True)

        def done(_result, error):
            self.app.busy = ""
            if error:
                self.start_text.config(text=f"Could not start it: {error}", fg=BAD)
                return
            self.app._open_client()
            self.app.refresh_soon(slow=True)
            self.app.show("home")
        self.app.background(work, done)


class HomePage(Page):
    title = "Home"

    def build(self):
        box = self.section()
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=Ui.px(14), height=Ui.px(14), bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, Ui.px(10)))
        texts = tk.Frame(row, bg=CARD)
        texts.pack(side="left", fill="x", expand=True)
        self.state_text = label(texts, "Checking...", 13, bold=True)
        self.state_text.pack(anchor="w")
        self.state_sub = label(texts, "", 10, MUTED, wrap=560)
        self.state_sub.pack(anchor="w")
        self.power = button(row, "Turn off", self.toggle_power, "plain")
        self.power.pack(side="right")

        box = self.section("Connect a phone")
        cols = tk.Frame(box, bg=CARD)
        cols.pack(fill="x")
        left = tk.Frame(cols, bg=CARD)
        left.pack(side="left", anchor="n", padx=(0, Ui.px(28)))
        self.apk_qr = qr_image(APK_URL, Ui.px(150))
        tk.Label(left, image=self.apk_qr, bg=CARD).pack(anchor="w")
        label(left, "1. Get the app", 10, bold=True).pack(anchor="w", pady=(Ui.px(8), 0))
        label(left, "Scan with your Android phone's camera,\ndownload it and open the file to install.", 9, MUTED).pack(anchor="w")
        link = label(left, "Or copy the download link", 9, ACCENT, cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda e: self.copy(APK_URL, "Download link copied."))

        right = tk.Frame(cols, bg=CARD)
        right.pack(side="left", anchor="n", fill="x", expand=True)
        label(right, "2. In the app, type", 10, bold=True).pack(anchor="w")
        label(right, "This PC", 9, MUTED).pack(anchor="w", pady=(Ui.px(8), 0))
        self.address = label(right, "-", 20, bold=True)
        self.address.pack(anchor="w")
        self.address_sub = label(right, "", 9, MUTED)
        self.address_sub.pack(anchor="w")
        label(right, "Code", 9, MUTED).pack(anchor="w", pady=(Ui.px(10), 0))
        code_row = tk.Frame(right, bg=CARD)
        code_row.pack(anchor="w", fill="x")
        self.code = label(code_row, "------", 26, bold=True)
        self.code.pack(side="left")
        self.code_btn = button(code_row, "Show a code", self.new_code)
        self.code_btn.pack(side="left", padx=Ui.px(18))
        self.code_sub = label(right, "A code works for 10 minutes. The app remembers this PC after that.", 9, MUTED)
        self.code_sub.pack(anchor="w")
        self.paired = label(right, "", 10, OK)
        self.paired.pack(anchor="w", pady=(Ui.px(8), 0))

        self.update_box = self.section("Update available")
        self.update_text = label(self.update_box, "", 10, MUTED, wrap=700)
        self.update_text.pack(anchor="w")
        row = tk.Frame(self.update_box, bg=CARD)
        row.pack(anchor="w", pady=(Ui.px(10), 0))
        self.update_btn = button(row, "Update now", self.app.install_update)
        self.update_btn.pack(side="left", padx=(0, Ui.px(8)))
        button(row, "What's new", lambda: webbrowser.open(self.app.release.url) if self.app.release else None,
               "plain").pack(side="left")
        self.update_box.master.pack_forget()

        label(self.content, "Closing this window does not stop Samantha. Use Turn off for that.", 9, MUTED,
              bg=BG).pack(anchor="w", padx=Ui.px(28))

    def copy(self, text, message):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)
        self.code_sub.config(text=message)

    def refresh(self, snap):
        app = self.app
        auto = snap.get("autostart")
        ts = snap.get("tailscale") or {}
        server = snap.get("server")
        if app.busy:
            color, title, sub = WARN, app.busy, ""
        elif auto == "disabled":
            color, title, sub = MUTED, "Samantha is off", "Your phone can't see this PC, and this PC can't see your phone."
        elif server:
            color, title = OK, "Samantha is on"
            sub = "Your phone can see this PC from anywhere through Tailscale."
            if server.get("error"):
                color, sub = WARN, f"The screen can't be captured right now: {server['error']}"
        elif ts and ts.get("state") not in (None, "", "Running"):
            color, title, sub = WARN, "Waiting for Tailscale", "Open Tailscale and sign in or switch it on."
        elif snap.get("server_error") == "refused":
            color, title, sub = BAD, "Samantha did not accept this window", "Its settings changed. Close this window and open it again."
        else:
            color, title, sub = WARN, "Starting...", "It can take a minute after Windows starts."
        self.dot.delete("all")
        self.dot.create_oval(1, 1, Ui.px(13), Ui.px(13), fill=color, outline="")
        self.state_text.config(text=title)
        self.state_sub.config(text=sub)
        self.power.config(text="Turn on" if auto == "disabled" else "Turn off",
                          state="disabled" if app.busy else "normal")

        if ts.get("ip"):
            port = app.local.cfg.port if app.local else config.DEFAULT_PORT
            self.address.config(text=ts["ip"] + ("" if port == config.DEFAULT_PORT else f":{port}"))
            self.address_sub.config(text=f"or the name: {ts['name']}" if ts.get("name") else "")
        pair = (snap.get("pair") or {})
        code = pair.get("code")
        if code:
            c = code["code"]
            self.code.config(text=f"{c[:3]} {c[3:]}", fg=TEXT)
            self.code_btn.config(text="New code")
            minutes, seconds = divmod(code["expires_in"], 60)
            self.code_sub.config(text=f"Works for {minutes}:{seconds:02d} more. The app remembers this PC after that.")
        else:
            self.code.config(text="--- ---", fg=MUTED)
            self.code_btn.config(text="Show a code")
        self.code_btn.config(state="normal" if server else "disabled")
        phone = snap.get("phone") or {}
        paired = pair.get("paired") or []
        if phone.get("connected"):
            self.paired.config(text=f"Connected: {phone.get('device') or 'your phone'}. See it under My phone.", fg=OK)
        elif paired:
            last = paired[-1]
            self.paired.config(text=f"Paired: {last['device']} ({ago(last['at'])})", fg=OK)
        else:
            self.paired.config(text="")

        release = app.release
        if release:
            self.update_text.config(text=f"Version {release.version} is ready (you have {__version__}). "
                                    "Updating takes about a minute; Samantha restarts by itself and phones reconnect.")
            self.update_btn.config(state="disabled" if app.busy else "normal")
            if not self.update_box.master.winfo_ismapped():
                self.update_box.master.pack(fill="x", padx=Ui.px(28), pady=(0, Ui.px(14)),
                                            before=self.content.winfo_children()[-1])
        elif self.update_box.master.winfo_ismapped():
            self.update_box.master.pack_forget()

    def toggle_power(self):
        app = self.app
        turning_on = app.snap.get("autostart") == "disabled"
        app.busy = "Turning on..." if turning_on else "Turning off..."

        def work():
            if turning_on:
                autostart.resume()
            elif autostart.status() == "missing":
                autostart.install(start_now=False)
                autostart.pause()
            else:
                autostart.pause()

        def done(_result, error):
            app.busy = ""
            app.refresh_soon(slow=True)
            if error:
                messagebox.showerror(TITLE, str(error))
        app.background(work, done)

    def new_code(self):
        def done(_result, error):
            if error:
                messagebox.showerror(TITLE, f"Could not make a code: {error}")
            self.app.refresh_soon()
        self.app.background(lambda: self.app.local.post("/api/pair/code"), done)


class PhonePage(Page):
    """The phone's screen, live, and the mouse and keyboard to use it."""
    scrolls = False

    def build(self):
        head = tk.Frame(self.frame, bg=BG)
        head.pack(fill="x", padx=Ui.px(28), pady=(Ui.px(24), Ui.px(12)))
        label(head, "My phone", 20, bold=True, bg=BG).pack(side="left")
        self.status = label(head, "", 10, MUTED, bg=BG)
        self.status.pack(side="left", padx=Ui.px(16), pady=(Ui.px(6), 0))

        main = tk.Frame(self.frame, bg=BG)
        main.pack(fill="both", expand=True, padx=Ui.px(28), pady=(0, Ui.px(20)))
        self.canvas = tk.Canvas(main, bg="#05060a", highlightthickness=1, highlightbackground=LINE, cursor="hand2",
                                takefocus=1)
        self.canvas.pack(side="left", fill="both", expand=True)
        side = tk.Frame(main, bg=BG, width=Ui.px(230))
        side.pack(side="left", fill="y", padx=(Ui.px(16), 0))
        side.pack_propagate(False)

        _, box = card(side)
        box.master.pack(fill="x")
        self.device = label(box, "No phone yet", 12, bold=True, wrap=190)
        self.device.pack(anchor="w")
        self.device_sub = label(box, "", 9, MUTED, wrap=190)
        self.device_sub.pack(anchor="w")

        _, keys = card(side, "Buttons")
        keys.master.pack(fill="x", pady=(Ui.px(12), 0))
        grid = tk.Frame(keys, bg=CARD)
        grid.pack(fill="x")
        for i, (text, name) in enumerate((("Back", "back"), ("Home", "home"), ("Recent apps", "recents"),
                                          ("Notifications", "notifications"), ("Quick settings", "quicksettings"),
                                          ("Wake screen", "wake"))):
            b = button(grid, text, lambda n=name: self.send({"t": "key", "k": n}), "plain")
            b.config(padx=Ui.px(6), font=(FONT, 9))
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=Ui.px(2), pady=Ui.px(2))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        row = tk.Frame(keys, bg=CARD)
        row.pack(fill="x", pady=(Ui.px(10), 0))
        self.view_only = Toggle(row, lambda on: self.canvas.config(cursor="arrow" if on else "hand2"))
        self.view_only.pack(side="left")
        label(row, "View only", 10).pack(side="left", padx=Ui.px(8))

        label(side, "Click to tap, hold for a long press, drag to swipe, use the wheel to scroll and type on "
              "your keyboard (click the phone first). Esc is Back.", 9, MUTED, bg=BG, wrap=220).pack(anchor="w", pady=Ui.px(12))

        self.stream = PhoneStream(self.app)
        self.pointer = gestures.Pointer()
        self.outbox: queue.Queue = queue.Queue()
        self.typed = ""
        self.photo = None
        self.shown_seq = -1
        self.shown_size = (0, 0)
        self.rect = (0, 0, 0, 0)
        self.send_error = ""
        threading.Thread(target=self._sender, name="phone-input", daemon=True).start()

        c = self.canvas
        c.bind("<ButtonPress-1>", self._down)
        c.bind("<B1-Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._up)
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<Key>", self._key)
        c.bind("<Configure>", lambda e: self._draw(force=True))
        self.app.root.bind("<Unmap>", lambda e: self.stream.stop() if e.widget is self.app.root else None)
        self.app.root.bind("<Map>", lambda e: self.stream.start() if e.widget is self.app.root and self.visible else None)
        self.visible = False
        self._tick()

    def show(self):
        super().show()
        self.visible = True
        self.stream.start()
        self.canvas.focus_set()

    def hide(self):
        super().hide()
        self.visible = False
        self.stream.stop()

    # -- picture -------------------------------------------------------------------------------------
    def _tick(self):
        if self.visible:
            self._draw()
        if not self.app.closing:
            self.app.root.after(40, self._tick)

    def _draw(self, force=False):
        image, seq = self.stream.latest()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if image is None or cw < 20 or ch < 20 or (seq == self.shown_seq and (cw, ch) == self.shown_size and not force):
            return
        self.shown_seq, self.shown_size = seq, (cw, ch)
        scale = min((cw - 16) / image.width, (ch - 16) / image.height)
        w, h = max(1, int(image.width * scale)), max(1, int(image.height * scale))
        x0, y0 = (cw - w) // 2, (ch - h) // 2
        self.photo = ImageTk.PhotoImage(image.resize((w, h), Image.BILINEAR))
        self.canvas.delete("picture")
        self.canvas.create_image(x0, y0, image=self.photo, anchor="nw", tags="picture")
        self.canvas.tag_raise("message")
        self.rect = (x0, y0, w, h)

    def _message(self, text: str):
        c = self.canvas
        c.delete("message")
        if not text:
            return
        cw, ch = c.winfo_width(), c.winfo_height()
        c.create_rectangle(0, ch // 2 - Ui.px(70), cw, ch // 2 + Ui.px(70), fill="#05060a", outline="", tags="message")
        c.create_text(cw // 2, ch // 2, text=text, fill=TEXT, font=(FONT, 11), width=min(cw - 40, Ui.px(460)),
                      justify="center", tags="message")

    def refresh(self, snap):
        phone = snap.get("phone") or {}
        if not snap.get("server"):
            self.device.config(text="Samantha is not running")
            self.device_sub.config(text="Turn it on under Home.")
            self._message("Samantha is not running on this PC. Turn it on under Home.")
            self.status.config(text="")
            return
        if not phone.get("connected"):
            self.device.config(text="No phone connected")
            self.device_sub.config(text="")
            self._message("No phone is connected.\n\nOn your Android phone open Samantha, pair it with this PC "
                          "(Home shows how), and switch on \"Let this PC see and use my phone\".")
            self.status.config(text="")
            return
        self.device.config(text=phone.get("device") or "Your phone")
        control = phone.get("control", True)
        self.device_sub.config(text=("You can tap, swipe and type." if control else
                                     "The phone allows viewing only (its own switch).") +
                               (f"\nApp version {phone['app_version']}" if phone.get("app_version") else ""))
        fps = self.stream.fps()
        if self.stream.latest()[0] is None:
            self._message("Waiting for the first picture from the phone...")
        else:
            self._message("")
        self.status.config(text=(f"{fps:.1f} fps" if fps else "") + (f"   {self.send_error}" if self.send_error else ""))

    # -- input --------------------------------------------------------------------------------------
    def _where(self, event) -> tuple[float, float] | None:
        x0, y0, w, h = self.rect
        if not w or not h:
            return None
        return (event.x - x0) / w, (event.y - y0) / h

    def _usable(self) -> bool:
        return not self.view_only.on and self.stream.latest()[0] is not None

    def _down(self, event):
        self.canvas.focus_set()
        pos = self._where(event)
        if pos and self._usable() and 0 <= pos[0] <= 1 and 0 <= pos[1] <= 1:
            self.pointer.down(*pos, time.monotonic() * 1000)

    def _move(self, event):
        pos = self._where(event)
        if pos and self.pointer.active:
            self.pointer.move(*pos, time.monotonic() * 1000)

    def _up(self, event):
        pos = self._where(event)
        if pos and self.pointer.active:
            action = self.pointer.up(*pos, time.monotonic() * 1000)
            if action:
                self.send(action)

    def _wheel(self, event):
        pos = self._where(event)
        if pos and self._usable() and 0 <= pos[0] <= 1 and 0 <= pos[1] <= 1:
            self.send(gestures.wheel(pos[0], pos[1], event.delta / 120))

    def _key(self, event):
        if not self._usable():
            return
        what = gestures.key(event.keysym, event.char)
        if not what:
            return
        kind, value = what
        if kind == "key":
            self._flush_text()
            self.send({"t": "key", "k": value})
            return
        if not self.typed:
            self.app.root.after(150, self._flush_text)
        self.typed += value

    def _flush_text(self):
        if self.typed:
            text, self.typed = self.typed[:500], self.typed[500:]
            self.send({"t": "text", "s": text})

    def send(self, event: dict):
        if not self.view_only.on:
            self.outbox.put(event)

    def _sender(self):
        while True:
            event = self.outbox.get()
            try:
                self.app.local.post("/api/phone/input", event)
                self.send_error = ""
            except Refused as exc:
                self.send_error = str(exc)
            except (Offline, AttributeError):
                self.send_error = "Samantha is not running."


class PhoneStream:
    """Receives the phone's pictures while the My phone page is on screen (the phone only sends them then)."""

    def __init__(self, app: App):
        self.app = app
        self._lock = threading.Lock()
        self._image = None
        self._seq = 0
        self._times: deque = deque(maxlen=30)
        self._active = False
        self._resp = None
        self._thread = None

    def start(self):
        with self._lock:
            if self._active:
                return
            self._active = True
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="phone-picture", daemon=True)
                self._thread.start()

    def stop(self):
        with self._lock:
            self._active = False
            resp, self._resp = self._resp, None
        if resp is not None:
            try:
                resp.close()   # ends the request, so the phone is told nobody is looking
            except Exception:
                pass

    def latest(self):
        with self._lock:
            return self._image, self._seq

    def fps(self) -> float:
        with self._lock:
            times = [t for t in self._times if time.monotonic() - t < 3]
        return (len(times) - 1) / (times[-1] - times[0]) if len(times) > 2 and times[-1] > times[0] else 0.0

    def _run(self):
        while self._active:
            local = self.app.local
            try:
                if local is None:
                    raise Offline("not set up")
                resp = local.stream("/api/phone/stream", timeout=20)
                with self._lock:
                    if not self._active:
                        resp.close()
                        return
                    self._resp = resp
                for jpeg in jpeg_frames(resp):
                    image = Image.open(io.BytesIO(jpeg))
                    image.load()
                    with self._lock:
                        if not self._active:
                            break
                        self._image = image
                        self._seq += 1
                        self._times.append(time.monotonic())
            except Exception:
                pass
            finally:
                with self._lock:
                    resp, self._resp = self._resp, None
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass
            if self._active:
                time.sleep(1)


class SettingsPage(Page):
    title = "Settings"

    def build(self):
        box = self.section("Sound")
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        self.sound = Toggle(row, self.set_sound)
        self.sound.pack(side="left")
        label(row, "Let my phone hear this PC's sound", 10).pack(side="left", padx=Ui.px(10))
        label(box, "Each phone also switches sound on in its own app, and the PC records nothing while no phone "
              "listens. Changing this restarts Samantha for a moment.", 9, MUTED, wrap=700).pack(anchor="w", pady=(Ui.px(6), 0))

        box = self.section("Phones")
        label(box, "Sign out every paired phone, for example after losing one. They need a new code to connect again.",
              10, MUTED, wrap=700).pack(anchor="w")
        button(box, "Sign out all phones", self.sign_out_all, "danger").pack(anchor="w", pady=(Ui.px(10), 0))

        box = self.section("iPhone or a web browser")
        label(box, "There is no iPhone app. An iPhone (or any browser in your tailnet) can still watch this PC: "
              "scan this link with its camera. The link contains your secret key, so only show it to your own devices.",
              10, MUTED, wrap=700).pack(anchor="w")
        button(box, "Show the link", self.show_browser_link, "plain").pack(anchor="w", pady=(Ui.px(10), 0))

        box = self.section("About")
        self.about = label(box, f"{APP_NAME} v{__version__}", 10)
        self.about.pack(anchor="w")
        row = tk.Frame(box, bg=CARD)
        row.pack(anchor="w", pady=(Ui.px(10), 0))
        button(row, "Check for updates", lambda: self.app.check_updates(), "plain").pack(side="left", padx=(0, Ui.px(8)))
        button(row, "Open the log folder", lambda: os.startfile(config.data_dir()), "plain").pack(side="left", padx=(0, Ui.px(8)))
        button(row, "Project page", lambda: webbrowser.open(PROJECT_URL), "plain").pack(side="left")

    def refresh(self, snap):
        server = snap.get("server") or {}
        audio = server.get("audio")
        if audio is not None and not self.app.busy:
            self.sound.set(bool(audio.get("enabled")))
        self.sound.enable(bool(server) and not self.app.busy)
        extra = f"   {self.app.busy}" if self.app.busy else ""
        self.about.config(text=f"{APP_NAME} v{__version__}{extra}")

    def set_sound(self, on: bool):
        config.set_env_value("SM_AUDIO", "1" if on else "0")
        self.app.restart_service("Restarting Samantha...")

    def sign_out_all(self):
        if not messagebox.askyesno(TITLE, "Sign out all phones? Each one needs a new code from Home to connect again."):
            return
        config.set_env_value("SM_TOKEN", config.new_token())
        self.app.restart_service("Signing out all phones...")

    def show_browser_link(self):
        local = self.app.local
        ts = self.app.snap.get("tailscale") or {}
        if not local or not ts.get("ip"):
            messagebox.showinfo(TITLE, "Samantha needs Tailscale to be on first.")
            return
        url = f"http://{ts['ip']}:{local.cfg.port}/?token={local.cfg.token}"
        win = tk.Toplevel(self.app.root, bg=CARD)
        win.title("Link for a browser")
        win.resizable(False, False)
        photo = qr_image(url, Ui.px(260))
        tk.Label(win, image=photo, bg=CARD).pack(padx=Ui.px(24), pady=(Ui.px(24), Ui.px(8)))
        win.photo = photo
        label(win, "Scan with the iPhone camera (Tailscale must be on there).\nAfter that, add it to the Home Screen "
              "from Safari's Share menu.", 9, MUTED).pack(padx=Ui.px(24))

        def copy():
            win.clipboard_clear()
            win.clipboard_append(url)
        button(win, "Copy the link", copy, "plain").pack(pady=Ui.px(16))


# -- start ----------------------------------------------------------------------------------------
def _already_open() -> bool:
    """Only one window: a second start brings the first one to the front instead."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, LOCK_NAME)
        _already_open.handle = handle
        if ctypes.get_last_error() != 183:   # ERROR_ALREADY_EXISTS
            return False
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def main() -> int:
    if sys.platform == "win32":
        if _already_open():
            return 0
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    Ui.scale = max(1.0, root.winfo_fpixels("1i") / 96)
    App(root)
    root.mainloop()
    return 0
