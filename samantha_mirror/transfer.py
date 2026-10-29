"""Files both ways between the PC and the phone.

Phone -> PC: the phone app (Android's Share > Mirra) uploads a file; it is saved in Downloads\\Mirra on the PC, under
a cleaned-up name that never replaces an existing file. Nothing received is ever opened or run.

PC -> phone: the Mirra window uploads a file the user picked; it waits here (in a private temporary folder) until the
phone, told over its usual command link, downloads it into its own Downloads folder. A waiting file is removed once
the phone has it, or after an hour.
"""
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

MAX_FILE = 1_000_000_000      # bytes in one file, either way (the web server's own request limit is 1 GB)
KEEP_FREE = 500_000_000       # never fill the PC's disk: refuse a file that would leave less than this
WAITING_FOR = 3600            # seconds a file for the phone waits before it is dropped
MAX_WAITING = 20
RECENT = 10                   # received files the Mirra window can show
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}


class TransferError(Exception):
    """Something the sender should hear about (in plain words)."""


def downloads_folder() -> Path:
    return Path.home() / "Downloads" / "Mirra"


def safe_name(name: str) -> str:
    """A plain file name from whatever the other side sent: no folders, no characters Windows forbids."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.lower() in _RESERVED or not stem:
        stem = f"file {time.strftime('%Y-%m-%d %H.%M.%S')}" if not stem else f"_{stem}"
    stem, ext = stem[:150], ext[:20]
    return f"{stem}.{ext}" if ext else stem


def _unused(folder: Path, name: str) -> Path:
    path = folder / name
    stem, suffix = path.stem, path.suffix
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}){suffix}"
        n += 1
    return path


def _copy(stream, out, limit: int) -> int:
    done = 0
    while chunk := stream.read(1 << 20):
        done += len(chunk)
        if done > limit:
            raise TransferError(f"The file is larger than {limit // 1_000_000} MB.")
        out.write(chunk)
    return done


class Inbox:
    """Files the phone sends to this PC."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder or downloads_folder()
        self._lock = threading.Lock()
        self._recent: deque = deque(maxlen=RECENT)
        self._seq = 0

    def receive(self, name: str, stream, size: int | None) -> Path:
        if size is not None and size > MAX_FILE:
            raise TransferError(f"The file is larger than {MAX_FILE // 1_000_000} MB.")
        self.folder.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.folder).free
        if free - (size or 0) < KEEP_FREE:
            raise TransferError("The PC's disk is almost full.")
        part = self.folder / f".mirra-{secrets.token_hex(6)}.part"
        try:
            with open(part, "wb") as out:
                got = _copy(stream, out, min(MAX_FILE, max(0, free - KEEP_FREE)))
            if size is not None and got != size:
                raise TransferError("The file did not arrive completely. Try again.")
            with self._lock:   # pick the name and take it in one go, so two files with one name both arrive
                path = _unused(self.folder, safe_name(name))
                part.replace(path)
                self._seq += 1
                self._recent.appendleft({"id": self._seq, "name": path.name, "size": got, "at": time.time()})
            return path
        finally:
            part.unlink(missing_ok=True)

    def recent(self) -> list:
        with self._lock:
            return list(self._recent)


class Outbox:
    """Files waiting for the phone to download them."""

    def __init__(self, folder: Path | None = None):
        self._folder = folder
        self._lock = threading.Lock()
        self._files: dict[str, dict] = {}

    def _dir(self) -> Path:
        if self._folder is None:
            self._folder = Path(tempfile.mkdtemp(prefix="mirra-to-phone-"))
        self._folder.mkdir(parents=True, exist_ok=True)
        return self._folder

    def add(self, name: str, stream, size: int | None) -> dict:
        """Keeps an uploaded file for the phone; returns what to tell the phone about it."""
        if size is not None and size > MAX_FILE:
            raise TransferError(f"The file is larger than {MAX_FILE // 1_000_000} MB.")
        self.expire()
        with self._lock:
            if len(self._files) >= MAX_WAITING:
                raise TransferError("Too many files are waiting for the phone. Try again in a minute.")
        file_id = secrets.token_urlsafe(16)
        path = self._dir() / file_id
        try:
            with open(path, "wb") as out:
                got = _copy(stream, out, MAX_FILE)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        item = {"id": file_id, "name": safe_name(name), "size": got}
        with self._lock:
            self._files[file_id] = item | {"path": path, "at": time.monotonic()}
        return item

    def get(self, file_id: str) -> dict | None:
        self.expire()
        with self._lock:
            return self._files.get(file_id)

    def done(self, file_id: str) -> None:
        with self._lock:
            item = self._files.pop(file_id, None)
        if item:
            item["path"].unlink(missing_ok=True)

    def expire(self) -> None:
        now = time.monotonic()
        with self._lock:
            old = [k for k, v in self._files.items() if now - v["at"] > WAITING_FOR]
        for file_id in old:
            self.done(file_id)
