"""Mirra on the PC (Mirra.exe): the window.

One place for everything on the PC: first-time setup, turning Mirra on and off, connecting a phone (one QR code),
the phone window, sound, and updates (a pop-up when a new version is out). Mirra itself runs in the background
service, so it keeps working while this window is closed.

Tk is single-threaded: anything slow (the network, PowerShell, Tailscale) runs on a worker thread and hands its
result back through `App.later()`, which the window runs on its own thread.
"""
import ctypes
import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import font as tkfont

import customtkinter as ctk
import qrcode
from PIL import Image

from . import __version__, autostart, config, proc, shortcuts, tailscale, transfer, updater
from .client import Local, Offline, Refused

APP = "Mirra"
TITLE = "Mirra"
SETUP_URL = f"https://github.com/{updater.REPO}/releases/latest/download/Mirra-for-Android-Setup.apk"
TAILSCALE_ANDROID = tailscale.PLAY_STORE_URL
PROJECT_URL = f"https://github.com/{updater.REPO}"
LOCK_NAME = r"Local\MirraWindow"
ASSETS = Path(__file__).resolve().parent / "assets"

BG, SIDE, CARD, CARD2, LINE = "#0b0d12", "#0e1118", "#141721", "#1c2030", "#262b3a"
TEXT, MUTED, ACCENT, ACCENT_HI, CYAN = "#f1f3f8", "#8e96a8", "#7c5cff", "#8f74ff", "#22d3ee"
OK, WARN, BAD = "#34d399", "#fbbf24", "#f87171"
FONT = "Segoe UI"
# Windows' own icon font (Windows 11, else Windows 10)
ICONS = {"home": "", "phone": "", "settings": "", "check": "", "sound": "",
         "update": "", "lock": "", "web": "", "info": "", "power": ""}


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def icon_font(root) -> str | None:
    families = set(tkfont.families(root))
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return None


def label(parent, text="", size=13, color=TEXT, weight="normal", wrap=0, **kw):
    return ctk.CTkLabel(parent, text=text, font=font(size, weight), text_color=color, justify="left", anchor="w",
                        wraplength=wrap, **kw)


def button(parent, text, command, kind="primary", width=0, height=40):
    styles = {"primary": (ACCENT, ACCENT_HI, "#ffffff", 0), "plain": (CARD2, "#262b3e", TEXT, 1),
              "danger": ("#3a1d22", "#4a242b", BAD, 0), "ghost": ("transparent", CARD2, TEXT, 0)}
    fg, hover, color, border = styles[kind]
    return ctk.CTkButton(parent, text=text, command=command, fg_color=fg, hover_color=hover, text_color=color,
                         border_width=border, border_color=LINE, corner_radius=12, height=height,
                         width=width or 120, font=font(13, "bold"))


def card(parent, title=None, subtitle=None):
    frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=18, border_width=1, border_color=LINE)
    inner = ctk.CTkFrame(frame, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=22, pady=18)
    if title:
        label(inner, title, 17, weight="bold").pack(anchor="w")
    if subtitle:
        label(inner, subtitle, 13, MUTED, wrap=640).pack(anchor="w", pady=(2, 0))
    return frame, inner


def switch(parent, command, text=""):
    return ctk.CTkSwitch(parent, text=text, command=command, progress_color=ACCENT, button_color="#ffffff",
                         button_hover_color="#e8e8f0", fg_color="#3a3f4b", font=font(13), text_color=TEXT)


def qr_image(text: str, size: int) -> ctk.CTkImage:
    qr = qrcode.QRCode(border=2, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0b0d12", back_color="white").get_image().convert("RGB")
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def put(widget, **options) -> None:
    """widget.configure(**options), but only when they differ from last time: every configure redraws."""
    last = getattr(widget, "_mirra_last", None)
    if last == options:
        return
    widget._mirra_last = dict(options)
    widget.configure(**options)


def ago(timestamp: float) -> str:
    seconds = max(0, time.time() - timestamp)
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    return time.strftime("%H:%M", time.localtime(timestamp))


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


HELP = [
    ("The phone says \"Can't reach your PC\"",
     "Switch Tailscale on in the phone. Keep this PC on and awake (Windows Settings > System > Power: never sleep "
     "while plugged in), and Mirra on (Home)."),
    ("The QR code's link does not open on the phone", "Tailscale must be on in the phone: the page comes from this PC."),
    ("\"Restricted setting\" when switching Mirra on in the phone",
     "Mirra was installed straight from the downloaded file. In Mirra on the phone, tap Get Mirra Setup, open it and "
     "tap Install Mirra again."),
    ("The phone window stays black or says \"Waiting for your phone\"",
     "In Mirra on the phone, \"This phone on your PC\" must be on and not paused. Banking apps and password screens "
     "always show black (Android hides them)."),
    ("It is not smooth", "Under My phone, choose 720p and 30 fps. On Wi-Fi at home it can go higher."),
    ("Where do sent files go?",
     "From the phone (Share > Mirra): Downloads\\Mirra on this PC. To the phone (drop files on the phone window): "
     "Downloads on the phone. Sending to the phone needs \"This phone on your PC\" on in the phone app."),
    ("A phone was lost", "Settings > Phones > Sign out all phones. Every phone then needs to scan the code again."),
]


# -- the window ------------------------------------------------------------------------------------
class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.closing = False
        self._calls: queue.Queue = queue.Queue()
        self.wake = threading.Event()
        self.snap: dict = {}
        self._snap_lock = threading.Lock()
        self.local: Local | None = None
        self.release: updater.Release | None = None
        self.offered = ""          # the version already offered in a pop-up
        self.busy = ""             # what a long action is doing right now ("" when idle)
        self.phone_window = None
        self.icons = icon_font(root)
        self.received_seen: int | None = None   # the newest file from the phone already announced

        root.title(TITLE)
        root.configure(fg_color=BG)
        # screen size in CustomTkinter's units (Tk reports real pixels once the process is DPI aware)
        scale = ctk.ScalingTracker.get_window_scaling(root) if root.winfo_fpixels("1i") > 100 else 1.0
        sw, sh = root.winfo_screenwidth() / scale, root.winfo_screenheight() / scale
        width, height = int(min(1140, sw - 40)), int(min(780, sh - 90))
        root.geometry(f"{width}x{height}+{int(max(0, (sw - width) / 2))}+10")
        root.minsize(min(width, 900), min(height, 560))
        if (ASSETS / "mirra.ico").exists():
            try:
                root.iconbitmap(default=str(ASSETS / "mirra.ico"))
            except tk.TclError:
                pass

        side = ctk.CTkFrame(root, fg_color=SIDE, corner_radius=0, width=236)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(anchor="w", padx=22, pady=(26, 30))
        logo = Image.open(ASSETS / "mirra-256.png")
        ctk.CTkLabel(brand, text="", image=ctk.CTkImage(logo, logo, size=(42, 42))).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=12)
        label(names, "Mirra", 22, weight="bold").pack(anchor="w")
        label(names, "PC and phone, as one", 11, MUTED).pack(anchor="w")
        self.nav: dict[str, ctk.CTkFrame] = {}
        for key, text in (("home", "Home"), ("phone", "My phone"), ("settings", "Settings")):
            self.nav[key] = self._nav_item(side, key, text)
        self.version_label = label(side, f"Version {__version__}", 11, MUTED)
        self.version_label.pack(side="bottom", anchor="w", padx=24, pady=18)

        self.body = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
        self.body.pack(side="left", fill="both", expand=True)
        self.pages = {"setup": SetupPage(self), "home": HomePage(self), "phone": PhonePage(self),
                      "settings": SettingsPage(self)}
        self.current = None

        self._open_client()
        self.show("home" if self.ready() else "setup")
        threading.Thread(target=self._poll, name="status", daemon=True).start()
        if self.local and self.local.cfg.update_check:
            self.check_updates(quiet=True)
            root.after(6 * 3600 * 1000, self._recheck)
        if getattr(sys, "frozen", False):
            self.background(shortcuts.update)   # older versions' shortcuts open this window
            self.background(autostart.adopt, lambda moved, _e: moved and self.refresh_soon(slow=True))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._pump)

    def _nav_item(self, side, key, text):
        item = ctk.CTkFrame(side, fg_color="transparent", corner_radius=12, height=46, cursor="hand2")
        item.pack(fill="x", padx=12, pady=2)
        item.pack_propagate(False)
        glyph = ctk.CTkLabel(item, text=ICONS[key] if self.icons else "", width=28,
                             font=ctk.CTkFont(family=self.icons or FONT, size=16), text_color=MUTED)
        glyph.pack(side="left", padx=(14, 6))
        name = label(item, text, 14, MUTED, weight="bold")
        name.pack(side="left")
        for w in (item, glyph, name):
            w.bind("<Button-1>", lambda e, k=key: self.show(k))
            w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
            w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))
        item.parts = (glyph, name)
        return item

    def _nav_hover(self, key, on):
        if key != self.current:
            self.nav[key].configure(fg_color=CARD if on else "transparent")

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
        with self._snap_lock:
            snap = dict(self.snap)
        self._announce_files(snap)
        if self.current:
            self.pages[self.current].refresh(snap)
        if not self.closing:
            self.root.after(200, self._pump)

    def _announce_files(self, snap: dict) -> None:
        """A small notice when the phone has sent files (not for the ones that came before the window opened)."""
        received = (snap.get("phone") or {}).get("received")
        if received is None:
            return
        newest = received[0]["id"] if received else 0
        if self.received_seen is None or newest < self.received_seen:   # first look, or the service restarted
            self.received_seen = newest
            return
        new = [f for f in received if f["id"] > self.received_seen]
        self.received_seen = newest
        if new:
            FileNotice(self, new)

    def send_files(self, paths) -> None:
        """Sends files to the phone (they land in its Downloads folder), saying how it went in a pop-up if it fails."""
        files = [Path(p) for p in paths if Path(p).is_file()]
        if not files or not self.local:
            return
        self.busy = f"Sending {files[0].name}..." if len(files) == 1 else f"Sending {len(files)} files..."

        def work():
            for file in files:
                self.local.send_file(file)

        def done(_result, error):
            self.busy = ""
            if error is not None:
                UpdateDialog.message(self, "Not sent", f"The phone did not get the file: {error}")
            else:
                self.sent_note = ("Sent. It is in Downloads on the phone." if len(files) == 1 else
                                  f"Sent {len(files)} files. They are in Downloads on the phone.", time.monotonic())
        self.background(work, done)

    def open_received(self) -> None:
        folder = transfer.downloads_folder()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

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
            selected = k == key
            item.configure(fg_color=CARD2 if selected else "transparent")
            for part in item.parts:
                part.configure(text_color=TEXT if selected else MUTED)
            if selected and self.icons:
                item.parts[0].configure(text_color=CYAN)
        self.pages[key].show()

    def close(self):
        self.closing = True
        if self.phone_window is not None and self.phone_window.winfo_exists():
            self.phone_window.close()
        self.root.destroy()

    def open_phone(self):
        from .phonewindow import open_window
        if not self.local:
            return
        phone = self.snap.get("phone") or {}
        open_window(self, self.local, phone.get("device", ""), (phone.get("width", 0), phone.get("height", 0)))

    # -- updates -----------------------------------------------------------------------------------
    def _recheck(self):
        if not self.closing:
            self.check_updates(quiet=True)
            self.root.after(6 * 3600 * 1000, self._recheck)

    def check_updates(self, quiet=False):
        def done(release, error):
            if error:
                if not quiet:
                    UpdateDialog.message(self, "Could not check for updates", str(error))
                return
            self.release = release
            if release and release.version != self.offered:
                self.offered = release.version
                UpdateDialog(self, release)
            elif not quiet and not release:
                UpdateDialog.message(self, "You're up to date", f"Mirra {__version__} is the newest version.")
        self.background(updater.available, done)

    def install_update(self):
        release = self.release
        if not release or self.busy:
            return
        mode = updater.install_mode()
        if mode == "other":
            webbrowser.open(release.url)
            return
        self.busy = f"Downloading Mirra {release.version}..."

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
                UpdateDialog.message(self, "The update did not work", str(error))
            elif result == "exe":
                self.close()   # the new version is swapped in once this window is gone, then it opens again
            else:
                UpdateDialog.message(self, "Updated", f"Mirra {release.version} is installed. Close this window and open it again.")
        self.background(work, done)

    def restart_service(self, why: str):
        self.busy = why

        def done(_result, error):
            self.busy = ""
            self._open_client()
            self.refresh_soon(slow=True)
            if error:
                UpdateDialog.message(self, "Something went wrong", str(error))
        self.background(lambda: updater.restart_service() or None, done)


class UpdateDialog:
    """The pop-up: a new version is out. Also used for short messages."""

    def __init__(self, app: App, release):
        self.app = app
        win = self.win = self._window(app, "Update available")
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=24)
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")
        logo = Image.open(ASSETS / "mirra-256.png")
        ctk.CTkLabel(top, text="", image=ctk.CTkImage(logo, logo, size=(54, 54))).pack(side="left")
        titles = ctk.CTkFrame(top, fg_color="transparent")
        titles.pack(side="left", padx=14)
        label(titles, f"Mirra {release.version} is here", 19, weight="bold").pack(anchor="w")
        label(titles, f"You have {__version__}. Updating takes about a minute.", 13, MUTED).pack(anchor="w")
        notes = [ln.strip("-* ").strip() for ln in release.notes.splitlines() if ln.strip().startswith(("-", "*"))][:4]
        if notes:
            box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=14)
            box.pack(fill="x", pady=(18, 0))
            for n in notes:
                label(box, "•  " + n.replace("**", "")[:140], 12, TEXT, wrap=430).pack(anchor="w", padx=16, pady=3)
        label(body, "Mirra restarts by itself and your phone reconnects. Phones get their matching update next.",
              12, MUTED, wrap=460).pack(anchor="w", pady=(14, 0))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(18, 0))
        button(row, "Update now", self._update, width=150).pack(side="right")
        button(row, "Later", win.destroy, "ghost", width=100).pack(side="right", padx=8)
        button(row, "What's new", lambda: webbrowser.open(release.url), "ghost", width=110).pack(side="left")

    @staticmethod
    def _window(app, title):
        win = ctk.CTkToplevel(app.root)
        win.title(title)
        win.configure(fg_color=BG)
        win.resizable(False, False)
        win.transient(app.root)
        win.after(200, lambda: (win.lift(), win.focus_force()))
        if (ASSETS / "mirra.ico").exists():
            win.after(250, lambda: win.iconbitmap(str(ASSETS / "mirra.ico")))
        app.root.update_idletasks()
        x = app.root.winfo_rootx() + app.root.winfo_width() // 2 - 260
        y = app.root.winfo_rooty() + 120
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        return win

    def _update(self):
        self.win.destroy()
        self.app.install_update()

    @staticmethod
    def message(app, title, text):
        win = UpdateDialog._window(app, title)
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=24)
        label(body, title, 18, weight="bold").pack(anchor="w")
        label(body, text, 13, MUTED, wrap=420).pack(anchor="w", pady=(6, 0))
        button(body, "OK", win.destroy, width=100).pack(anchor="e", pady=(18, 0))


# -- pages -----------------------------------------------------------------------------------------
class FileNotice:
    """Bottom right, for a few seconds: "Your phone sent photo.jpg", with a button to open the folder."""

    def __init__(self, app: App, files: list):
        win = self.win = ctk.CTkToplevel(app.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(fg_color=CARD)
        body = ctk.CTkFrame(win, fg_color=CARD, corner_radius=0, border_width=1, border_color=LINE)
        body.pack(fill="both", expand=True)
        inner = ctk.CTkFrame(body, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        names = files[0]["name"] if len(files) == 1 else f"{len(files)} files"
        label(inner, "Your phone sent " + names, 14, weight="bold", wrap=300).pack(anchor="w")
        label(inner, "Saved in Downloads\\Mirra", 12, MUTED).pack(anchor="w", pady=(2, 10))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(anchor="w")
        button(row, "Open folder", lambda: (app.open_received(), self.close()), width=120, height=34).pack(side="left")
        button(row, "OK", self.close, "ghost", width=60, height=34).pack(side="left", padx=6)
        win.update_idletasks()
        w, h = max(340, win.winfo_reqwidth()), win.winfo_reqheight()
        x, y = win.winfo_screenwidth() - w - 24, win.winfo_screenheight() - h - 72
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.after(9000, self.close)

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class Page:
    title = ""
    scrolls = True

    def __init__(self, app: App):
        self.app = app
        if self.scrolls:
            self.frame = ctk.CTkScrollableFrame(app.body, fg_color=BG, corner_radius=0,
                                                scrollbar_button_color=CARD2, scrollbar_button_hover_color=LINE)
        else:
            self.frame = ctk.CTkFrame(app.body, fg_color=BG, corner_radius=0)
        self.content = self.frame
        if self.title:
            label(self.content, self.title, 28, weight="bold").pack(anchor="w", padx=32, pady=(28, 16))
        self.build()

    def build(self):
        pass

    def show(self):
        self.frame.pack(fill="both", expand=True)

    def hide(self):
        self.frame.pack_forget()

    def refresh(self, snap: dict):
        pass

    def section(self, title=None, subtitle=None):
        outer, inner = card(self.content, title, subtitle)
        outer.pack(fill="x", padx=32, pady=(0, 16))
        return inner


class SetupPage(Page):
    title = "Welcome to Mirra"

    def build(self):
        label(self.content, "Mirra shows this PC on your phone, and your Android phone on this PC. Everything goes "
              "straight between your own devices through Tailscale, a free private network. No cloud, no accounts "
              "with us.", 14, MUTED, wrap=720).pack(anchor="w", padx=32, pady=(0, 18))
        box = self.section("1   Tailscale", "The private network between your PC and your phone.")
        self.ts_text = label(box, "Checking...", 13, MUTED, wrap=680)
        self.ts_text.pack(anchor="w", pady=(10, 0))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(anchor="w", pady=(12, 0))
        self.install_btn = button(row, "Install Tailscale", self.install_tailscale, width=160)
        self.install_btn.pack(side="left", padx=(0, 8))
        button(row, "Check again", lambda: self.app.refresh_soon(slow=True), "plain", width=120).pack(side="left")

        box = self.section("2   Start Mirra", "Mirra runs quietly in the background and starts with Windows. "
                           "You can turn it off at any time.")
        self.start_btn = button(box, "Start Mirra", self.start, width=160)
        self.start_btn.pack(anchor="w", pady=(12, 0))
        self.start_text = label(box, "", 13, MUTED, wrap=680)
        self.start_text.pack(anchor="w", pady=(6, 0))

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
        put(self.ts_text, text=text, text_color=color)
        put(self.install_btn, state="disabled" if ts and ts["installed"] else "normal")
        put(self.start_btn, state="normal" if running and not self.app.busy else "disabled")
        if self.app.busy:
            put(self.start_text, text=self.app.busy)

    def install_tailscale(self):
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
                self.start_text.configure(text=f"Could not start it: {error}", text_color=BAD)
                return
            self.app._open_client()
            self.app.refresh_soon(slow=True)
            self.app.show("home")
        self.app.background(work, done)


class HomePage(Page):
    title = "Home"

    # The guide on this page: what to do, one step at a time, each ticked off when Mirra sees it done.
    STEPS = [
        ("Put Tailscale on your phone", "The free private network between your phone and this PC."),
        ("Scan the code with your phone", "It installs Mirra and connects it to this PC."),
        ("Let this PC see your phone", "One switch in the Mirra app on the phone."),
        ("Open your phone on this PC", "Use it with your mouse and keyboard."),
    ]

    def build(self):
        # status
        box = self.section()
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x")
        self.dot = label(row, "●", 22, MUTED)
        self.dot.pack(side="left", padx=(0, 12))
        texts = ctk.CTkFrame(row, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True)
        self.state_text = label(texts, "Checking...", 19, weight="bold")
        self.state_text.pack(anchor="w")
        self.state_sub = label(texts, "", 13, MUTED, wrap=560)
        self.state_sub.pack(anchor="w")
        self.power = switch(row, self.toggle_power)
        self.power.pack(side="right")
        self.power_busy = False

        # the guide
        box = self.section("Connect your phone", "Follow the steps. Each one ticks itself off when it is done.")
        cols = ctk.CTkFrame(box, fg_color="transparent")
        cols.pack(fill="x", pady=(16, 0))
        steps = ctk.CTkFrame(cols, fg_color="transparent", width=330)
        steps.pack(side="left", anchor="n", fill="y")
        self.rows = [self._step_row(steps, i, t, s) for i, (t, s) in enumerate(self.STEPS)]
        self.panel = ctk.CTkFrame(cols, fg_color=CARD2, corner_radius=16)
        self.panel.pack(side="left", fill="both", expand=True, padx=(22, 0))
        self.panels = [self._panel_tailscale(), self._panel_scan(), self._panel_allow(), self._panel_open()]
        self.done = [False] * 4
        self.selected = None      # a step the user clicked; None = follow the first one not done
        self.shown = None
        self.asked_code = 0.0
        self.qr_for = None

        self.update_box = self.section()
        row = ctk.CTkFrame(self.update_box, fg_color="transparent")
        row.pack(fill="x")
        self.update_text = label(row, "", 14, TEXT, weight="bold")
        self.update_text.pack(side="left")
        button(row, "Update now", self.app.install_update, width=130).pack(side="right")
        self.update_box.master.pack_forget()

        label(self.content, "Closing this window does not stop Mirra; it keeps running in the background.", 12,
              MUTED).pack(anchor="w", padx=34, pady=(0, 20))

    # -- the step list ------------------------------------------------------------------------------
    def _step_row(self, parent, i, title, sub):
        row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=14, cursor="hand2")
        row.pack(fill="x", pady=3)
        badge = ctk.CTkLabel(row, text=str(i + 1), width=34, height=34, corner_radius=17, fg_color=CARD2,
                             text_color=MUTED, font=font(14, "bold"))
        badge.pack(side="left", padx=(10, 12), pady=10)
        texts = ctk.CTkFrame(row, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True, pady=8)
        t = label(texts, title, 14, MUTED, weight="bold")
        t.pack(anchor="w")
        s = label(texts, sub, 12, MUTED, wrap=250)
        s.pack(anchor="w")
        for w in (row, badge, texts, t, s):
            w.bind("<Button-1>", lambda e, n=i: self._select(n))
        return row, badge, t

    def _select(self, n):
        self.selected = n
        self._show_panel(n)

    def _current(self) -> int:
        if self.selected is not None:
            return self.selected
        return next((i for i, d in enumerate(self.done) if not d), 3)

    def _show_panel(self, n):
        for i, (row, badge, title) in enumerate(self.rows):
            done, current = self.done[i], i == n
            put(row, fg_color=CARD2 if current else "transparent")
            put(badge, text="✓" if done else str(i + 1),
                            fg_color=OK if done else (ACCENT if current else CARD2),
                            text_color="#0b0d12" if done else ("#ffffff" if current else MUTED))
            put(title, text_color=TEXT if (current or done) else MUTED)
        if self.shown != n:
            for p in self.panels:
                p.pack_forget()
            self.panels[n].pack(fill="both", expand=True, padx=22, pady=18)
            self.shown = n

    # -- what to do for each step ---------------------------------------------------------------------
    def _panel(self):
        return ctk.CTkFrame(self.panel, fg_color="transparent")

    def _panel_tailscale(self):
        p = self._panel()
        label(p, "Step 1: Tailscale on your phone", 16, weight="bold").pack(anchor="w")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))
        qr_box = ctk.CTkFrame(row, fg_color="#ffffff", corner_radius=14)
        qr_box.pack(side="left", anchor="n")
        ctk.CTkLabel(qr_box, text="", image=qr_image(TAILSCALE_ANDROID, 150)).pack(padx=8, pady=8)
        texts = ctk.CTkFrame(row, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True, padx=(18, 0))
        for line in ("1.  Scan this code with your phone's camera: it opens Tailscale in the Play Store.",
                     "2.  Install it and open it.",
                     "3.  Sign in with the same account as on this PC.",
                     "4.  Switch it on (it asks to add a VPN: tap OK)."):
            label(texts, line, 13, TEXT, wrap=230).pack(anchor="w", pady=2)
        button(p, "Done, next step", lambda: self._select(1), width=160).pack(anchor="e", pady=(14, 0))
        return p

    def _panel_scan(self):
        p = self._panel()
        label(p, "Step 2: scan this code with your phone", 16, weight="bold").pack(anchor="w")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))
        qr_box = ctk.CTkFrame(row, fg_color="#ffffff", corner_radius=14)
        qr_box.pack(side="left", anchor="n")
        self.qr = ctk.CTkLabel(qr_box, text="Waiting for Mirra...", text_color="#1d1650", width=190, height=190)
        self.qr.pack(padx=8, pady=8)
        texts = ctk.CTkFrame(row, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True, padx=(18, 0))
        for line in ("1.  Open the phone's camera and point it at the code. Tap the link that appears.",
                     "2.  Tap \"Open Mirra and connect\".",
                     "3.  The first time it downloads Mirra Setup: open it, install it, tap \"Install Mirra\", "
                     "then tap \"Open Mirra and connect\" again."):
            label(texts, line, 13, TEXT, wrap=230).pack(anchor="w", pady=2)
        label(texts, "No camera? In the Mirra app type:", 12, MUTED).pack(anchor="w", pady=(10, 2))
        pills = ctk.CTkFrame(texts, fg_color="transparent")
        pills.pack(anchor="w")
        self.name_pill = self._pill(pills, "PC", "-")
        self.code_pill = self._pill(pills, "Code", "--- ---")
        return p

    def _panel_allow(self):
        p = self._panel()
        label(p, "Step 3: let this PC see your phone", 16, weight="bold").pack(anchor="w")
        label(p, "On the phone, in the Mirra app:", 13, MUTED).pack(anchor="w", pady=(10, 4))
        for line in ("1.  Under \"This phone on your PC\", tap Turn it on.",
                     "2.  In the list, tap Mirra.",
                     "3.  Switch on \"Use Mirra\".",
                     "4.  Android asks \"Allow Mirra to have full control?\": tap Allow."):
            label(p, line, 13, TEXT, wrap=400).pack(anchor="w", pady=2)
        label(p, "You do this once. While this PC looks at the phone, the phone shows a notification.", 12, MUTED,
              wrap=400).pack(anchor="w", pady=(10, 0))
        self.allow_status = label(p, "", 13, WARN, wrap=400)
        self.allow_status.pack(anchor="w", pady=(10, 0))
        return p

    def _panel_open(self):
        p = self._panel()
        self.ready_title = label(p, "Step 4: your phone, on this PC", 16, weight="bold")
        self.ready_title.pack(anchor="w")
        self.ready_sub = label(p, "", 13, MUTED, wrap=400)
        self.ready_sub.pack(anchor="w", pady=(6, 0))
        self.open_btn = button(p, "Open phone window", self.app.open_phone, width=200, height=44)
        self.open_btn.pack(anchor="w", pady=(14, 0))
        label(p, "Click to tap, drag to swipe, right click is Back. More under My phone.", 12, MUTED,
              wrap=480).pack(anchor="w", pady=(12, 0))
        a = label(p, "Connect another phone", 13, CYAN, cursor="hand2")
        a.pack(anchor="w", pady=(10, 0))
        a.bind("<Button-1>", lambda e: self._select(1))
        return p

    def _pill(self, parent, name, value):
        pill = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=LINE)
        pill.pack(side="left", padx=(0, 10))
        label(pill, name, 11, MUTED).pack(anchor="w", padx=14, pady=(8, 0))
        v = label(pill, value, 20, weight="bold")
        v.pack(anchor="w", padx=14, pady=(0, 8))
        return v

    # -- keeping it up to date ----------------------------------------------------------------------------
    def refresh(self, snap):
        app = self.app
        auto = snap.get("autostart")
        ts = snap.get("tailscale") or {}
        server = snap.get("server")
        if app.busy:
            color, title, sub = WARN, app.busy, ""
        elif auto == "disabled":
            color, title, sub = MUTED, "Mirra is off", "Your phone can't see this PC, and this PC can't see your phone."
        elif server:
            color, title, sub = OK, "Mirra is on", "Your phone can reach this PC from anywhere through Tailscale."
            if server.get("error"):
                color, sub = WARN, f"The screen can't be captured right now: {server['error']}"
        elif ts and ts.get("state") not in (None, "", "Running"):
            color, title, sub = WARN, "Waiting for Tailscale on this PC", "Open Tailscale (in the taskbar corner) and sign in or switch it on."
        elif snap.get("server_error") == "refused":
            color, title, sub = BAD, "Mirra did not accept this window", "Its settings changed. Close this window and open it again."
        else:
            color, title, sub = WARN, "Starting...", "It can take a minute after Windows starts."
        put(self.dot, text_color=color)
        put(self.state_text, text=title)
        put(self.state_sub, text=sub)
        if not self.power_busy and bool(self.power.get()) != (auto != "disabled"):
            (self.power.deselect if auto == "disabled" else self.power.select)()
        put(self.power, state="disabled" if app.busy else "normal")

        # pairing: keep a fresh code (and its QR code) while this page is open
        port = app.local.cfg.port if app.local else config.DEFAULT_PORT
        name = ts.get("name") or ts.get("ip") or "-"
        put(self.name_pill, text=name if port == config.DEFAULT_PORT else f"{name}:{port}")
        pair = snap.get("pair") or {}
        code = pair.get("code")
        if server and (not code or code["expires_in"] < 90) and time.monotonic() - self.asked_code > 8:
            self.asked_code = time.monotonic()
            app.background(lambda: app.local.post("/api/pair/code"), lambda *_: app.refresh_soon())
        if code and ts.get("ip"):
            c = code["code"]
            put(self.code_pill, text=f"{c[:3]} {c[3:]}")
            url = f"http://{ts['ip']}:{port}/join?c={c}"
            if url != self.qr_for:
                self.qr_for = url
                put(self.qr, image=qr_image(url, 190), text="")
        else:
            put(self.code_pill, text="--- ---")
            if not server:
                put(self.qr, image=None, text="Mirra is not\nrunning yet")
                self.qr_for = None

        # the steps that are done: the phone app talked to this PC (paired); the phone shares (switch on)
        phone = snap.get("phone") or {}
        seen = phone.get("app_seen")
        paired = bool(pair.get("paired")) or (seen is not None and seen < 600) or phone.get("connected")
        sharing = bool(phone.get("connected"))
        self.done = [paired or sharing, paired or sharing, sharing, False]
        if sharing:
            device = phone.get("device") or "Your phone"
            put(self.ready_title, text=f"{device} is ready")
            put(self.ready_sub, text="Open its window to see it and use it with your mouse and keyboard."
                                     + ("" if phone.get("control", True) else
                                        " (The phone allows viewing only: its own switch.)"))
            put(self.open_btn, state="normal")
        else:
            put(self.ready_title, text="Step 4: your phone, on this PC")
            put(self.ready_sub, text="Waiting for your phone. Do steps 1 to 3 first.")
            put(self.open_btn, state="disabled")
        if paired and not sharing:
            put(self.allow_status, text="Waiting for the switch on the phone..." if seen is not None and seen < 60
                                        else "Open the Mirra app on your phone.")
        else:
            put(self.allow_status, text="")
        self._show_panel(self._current())

        release = app.release
        if release:
            put(self.update_text, text=f"Mirra {release.version} is available  (you have {__version__})")
            if not self.update_box.master.winfo_ismapped():
                self.update_box.master.pack(fill="x", padx=32, pady=(0, 16), before=self.content.winfo_children()[-1])
        elif self.update_box.master.winfo_ismapped():
            self.update_box.master.pack_forget()

    def toggle_power(self):
        app = self.app
        turning_on = bool(self.power.get())
        app.busy = "Turning on..." if turning_on else "Turning off..."
        self.power_busy = True

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
            self.power_busy = False
            app.refresh_soon(slow=True)
            if error:
                UpdateDialog.message(app, "Could not do that", str(error))
        app.background(work, done)


class PhonePage(Page):
    title = "My phone"

    def build(self):
        from .phonewindow import BITRATES, QUALITY, load_prefs
        self.prefs = load_prefs()
        hero = ctk.CTkFrame(self.content, fg_color="#241a66", corner_radius=20)
        hero.pack(fill="x", padx=32, pady=(0, 16))
        inner = ctk.CTkFrame(hero, fg_color="transparent")
        inner.pack(fill="x", padx=26, pady=24)
        self.device = label(inner, "No phone connected", 22, "#ffffff", weight="bold")
        self.device.pack(anchor="w")
        self.device_sub = label(inner, "", 13, "#d6d9f5", wrap=620)
        self.device_sub.pack(anchor="w", pady=(2, 14))
        self.open_btn = ctk.CTkButton(inner, text="Open phone window", command=self.app.open_phone, fg_color="#ffffff",
                                      hover_color="#e9e6ff", text_color="#241a66", corner_radius=14, height=48,
                                      width=220, font=font(15, "bold"))
        self.open_btn.pack(anchor="w")

        box = self.section("Files", "Send photos, documents, anything, between this PC and your phone.")
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(anchor="w", pady=(12, 0))
        self.send_btn = button(row, "Send files to the phone", self.pick_files, width=200)
        self.send_btn.pack(side="left", padx=(0, 8))
        button(row, "Open files from the phone", self.app.open_received, "plain", width=210).pack(side="left")
        self.files_note = label(box, "", 13, MUTED, wrap=640)
        self.files_note.pack(anchor="w", pady=(10, 0))
        label(box, "On the phone: in any app tap Share, then Mirra. Files arrive in Downloads\\Mirra on this PC. "
              "Files you send land in Downloads on the phone. You can also drop files on the phone window.",
              12, MUTED, wrap=640).pack(anchor="w", pady=(6, 0))

        box = self.section("Picture", "Sharper and smoother needs a faster connection. On mobile data choose 720p.")
        self._choice(box, "Sharpness", list(QUALITY), self.prefs["size"], "size")
        self._choice(box, "Smoothness", ["30 fps", "60 fps"], f"{self.prefs['fps']} fps", "fps")
        self._choice(box, "Quality", list(BITRATES), self.prefs["bitrate"], "bitrate")

        box = self.section("Using the phone from this PC")
        for keys, what in (("Click", "Tap"), ("Hold and drag", "Swipe, scroll, draw: your mouse is a finger"),
                           ("Mouse wheel", "Scroll"), ("Right click  or  Esc", "Back"), ("Middle click", "Home"),
                           ("Type", "Types on the phone (click a text field on the phone first)"),
                           ("Ctrl + V", "Pastes this PC's clipboard on the phone")):
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", pady=3)
            label(row, keys, 13, CYAN, weight="bold", width=180).pack(side="left")
            label(row, what, 13, TEXT).pack(side="left")
        label(box, "The phone shares its screen only while the phone window is open, and shows a notification then.",
              12, MUTED, wrap=640).pack(anchor="w", pady=(10, 0))

    def pick_files(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(parent=self.app.root, title="Send to the phone")
        if paths:
            self.app.send_files(list(paths))

    def _choice(self, parent, name, values, current, key):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))
        label(row, name, 13, MUTED, weight="bold", width=120).pack(side="left")
        seg = ctk.CTkSegmentedButton(row, values=values, command=lambda v, k=key: self._set(k, v),
                                     selected_color=ACCENT, selected_hover_color=ACCENT_HI, unselected_color=CARD2,
                                     unselected_hover_color=LINE, fg_color=CARD2, text_color=TEXT, font=font(13, "bold"),
                                     corner_radius=10, height=36)
        seg.set(current)
        seg.pack(side="left")

    def _set(self, key, value):
        from .phonewindow import quality_message, save_prefs
        self.prefs[key] = int(value.split()[0]) if key == "fps" else value
        save_prefs(self.prefs)
        win = self.app.phone_window
        if win is not None and win.winfo_exists():
            win.prefs = dict(self.prefs)
            win.link.send(b"C", quality_message(self.prefs))

    def refresh(self, snap):
        phone = snap.get("phone") or {}
        server = snap.get("server")
        put(self.send_btn, state="normal" if phone.get("connected") and not self.app.busy else "disabled")
        note, at = getattr(self.app, "sent_note", ("", 0))
        received = phone.get("received") or []
        if self.app.busy.startswith("Sending"):
            note = self.app.busy
        elif not note or time.monotonic() - at > 20:
            note = ("Last from the phone: " + ", ".join(f["name"] for f in received[:3])) if received else ""
        put(self.files_note, text=note)
        if not server:
            put(self.device, text="Mirra is not running")
            put(self.device_sub, text="Turn it on under Home.")
            put(self.open_btn, state="disabled")
        elif phone.get("connected"):
            put(self.device, text=phone.get("device") or "Your phone")
            put(self.device_sub, text="Connected. The window opens at the phone's own shape; you can resize it."
                                      if phone.get("control", True) else
                                      "Connected, view only: the phone does not allow tapping (its own switch).")
            put(self.open_btn, state="normal")
        else:
            put(self.device, text="No phone connected")
            put(self.device_sub, text="Open Mirra on your phone. Under \"This phone on your PC\", switch it on. "
                                      "Not paired yet? Scan the code on Home.")
            put(self.open_btn, state="normal")


class SettingsPage(Page):
    title = "Settings"

    def build(self):
        box = self.section("Sound", "Each phone switches sound on in its own app; the PC records nothing while no "
                           "phone listens.")
        self.sound = switch(box, self.set_sound, "Let phones hear this PC's sound")
        self.sound.pack(anchor="w", pady=(12, 0))

        box = self.section("Updates", "Mirra checks for a new version every few hours and shows a pop-up when one is out.")
        self.auto_update = switch(box, self.set_auto_update, "Check for updates automatically")
        self.auto_update.pack(anchor="w", pady=(12, 0))
        if not self.app.local or self.app.local.cfg.update_check:
            self.auto_update.select()
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(anchor="w", pady=(12, 0))
        button(row, "Check now", lambda: self.app.check_updates(), "plain", width=130).pack(side="left")
        self.version = label(row, f"   You have Mirra {__version__}", 13, MUTED)
        self.version.pack(side="left")

        box = self.section("Phones", "Sign out every paired phone, for example after losing one. They need to scan the "
                           "code again to connect.")
        button(box, "Sign out all phones", self.sign_out_all, "danger", width=180).pack(anchor="w", pady=(12, 0))

        box = self.section("iPhone or a web browser", "There is no iPhone app, but an iPhone (or any browser in your "
                           "tailnet) can still watch this PC. The link contains your secret key: only show it to your "
                           "own devices.")
        button(box, "Show the link", self.show_browser_link, "plain", width=150).pack(anchor="w", pady=(12, 0))

        box = self.section("Help", "The usual problems, and what fixes them.")
        for question, answer in HELP:
            label(box, question, 14, TEXT, weight="bold", wrap=680).pack(anchor="w", pady=(12, 0))
            label(box, answer, 13, MUTED, wrap=680).pack(anchor="w")

        box = self.section("About")
        label(box, f"Mirra {__version__}. Free and open source (MIT).", 13, MUTED).pack(anchor="w", pady=(4, 0))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(anchor="w", pady=(12, 0))
        button(row, "Open the log folder", lambda: os.startfile(config.data_dir()), "plain", width=170).pack(side="left", padx=(0, 8))
        button(row, "Project page", lambda: webbrowser.open(PROJECT_URL), "plain", width=140).pack(side="left")

    def refresh(self, snap):
        server = snap.get("server") or {}
        audio = server.get("audio")
        if audio is not None and not self.app.busy and bool(self.sound.get()) != bool(audio.get("enabled")):
            (self.sound.select if audio.get("enabled") else self.sound.deselect)()
        put(self.sound, state="normal" if server and not self.app.busy else "disabled")
        put(self.version, text=f"   You have Mirra {__version__}" + (f"   {self.app.busy}" if self.app.busy else ""))

    def set_sound(self):
        config.set_env_value("SM_AUDIO", "1" if self.sound.get() else "0")
        self.app.restart_service("Restarting Mirra...")

    def set_auto_update(self):
        config.set_env_value("SM_UPDATE_CHECK", "1" if self.auto_update.get() else "0")

    def sign_out_all(self):
        win = UpdateDialog._window(self.app, "Sign out all phones?")
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=24)
        label(body, "Sign out all phones?", 18, weight="bold").pack(anchor="w")
        label(body, "Every phone needs to scan the code on Home again to connect.", 13, MUTED, wrap=380).pack(anchor="w", pady=(6, 0))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(18, 0))

        def go():
            win.destroy()
            config.set_env_value("SM_TOKEN", config.new_token())
            self.app.restart_service("Signing out all phones...")
        button(row, "Sign out all", go, "danger", width=140).pack(side="right")
        button(row, "Cancel", win.destroy, "ghost", width=100).pack(side="right", padx=8)

    def show_browser_link(self):
        local = self.app.local
        ts = self.app.snap.get("tailscale") or {}
        if not local or not ts.get("ip"):
            UpdateDialog.message(self.app, "Tailscale is off", "Mirra needs Tailscale to be on first.")
            return
        url = f"http://{ts['ip']}:{local.cfg.port}/?token={local.cfg.token}"
        win = UpdateDialog._window(self.app, "Link for a browser")
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=24)
        qr_box = ctk.CTkFrame(body, fg_color="#ffffff", corner_radius=16)
        qr_box.pack()
        ctk.CTkLabel(qr_box, text="", image=qr_image(url, 240)).pack(padx=10, pady=10)
        label(body, "Scan with the iPhone camera (Tailscale must be on there). Then, in Safari, Share > Add to "
              "Home Screen.", 12, MUTED, wrap=300).pack(pady=(12, 0))

        def copy():
            win.clipboard_clear()
            win.clipboard_append(url)
        button(body, "Copy the link", copy, "plain", width=150).pack(pady=(12, 0))


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
        try:   # sharp text on scaled screens; CustomTkinter then scales the layout itself
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    App(root)
    root.mainloop()
    return 0
