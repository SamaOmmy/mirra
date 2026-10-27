"""Find and install new releases: `samantha-mirror update`.

Releases come from the project's GitHub Releases page. Two kinds of install are supported:
  - a git checkout (what install.ps1 makes): fast-forward to the release tag, reinstall dependencies;
  - the downloadable Windows .exe folder: download the zip, verify its SHA-256, swap the folder.
Updating is always started from the PC. The phone can see that an update exists but cannot start one.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__, autostart, config, proc

REPO = "SamaOmmy/samantha-screen-mirror"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ZIP_NAME = "SamanthaScreenMirror-windows.zip"
SUM_NAME = ZIP_NAME + ".sha256"
CHECK_EVERY = 12 * 3600   # seconds between background checks
FIRST_CHECK_DELAY = 60    # seconds after start, so startup stays quick


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    url: str
    notes: str
    zip_url: str | None
    sha_url: str | None


# -- versions --------------------------------------------------------------------------------
def parse_version(text: str) -> tuple[int, ...]:
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)\s*$", text or "")
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


# -- GitHub ----------------------------------------------------------------------------------
def _get(url: str, timeout: int = 10, limit: int = 2_000_000) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": f"samantha-screen-mirror/{__version__}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = resp.read(limit + 1)
    except OSError as exc:
        raise UpdateError(f"Could not reach GitHub ({exc}).") from exc
    if len(data) > limit:
        raise UpdateError("Unexpectedly large response from GitHub.")
    return data


def latest_release() -> Release:
    try:
        data = json.loads(_get(API_LATEST))
        tag = data["tag_name"]
        version = ".".join(str(n) for n in parse_version(tag))
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateError("GitHub sent something unexpected.") from exc
    # Only ever download from this project's own release page.
    zip_url, sha_url = assets.get(ZIP_NAME), assets.get(SUM_NAME)
    for url in (zip_url, sha_url):
        if url and not url.startswith(DOWNLOAD_PREFIX):
            raise UpdateError("Release asset is not hosted on the project's release page; refusing.")
    return Release(tag, version, data.get("html_url", f"https://github.com/{REPO}/releases"),
                   (data.get("body") or "").strip(), zip_url, sha_url)


def available() -> Release | None:
    """The newest release if it is newer than this install, else None."""
    release = latest_release()
    return release if is_newer(release.version, __version__) else None


# -- background check, shown in the app -------------------------------------------------------
_latest: Release | None = None
_lock = threading.Lock()


def cached_info() -> dict | None:
    """What the app shows: {"latest": "0.3.1", "url": ...} when an update is waiting."""
    with _lock:
        if _latest and is_newer(_latest.version, __version__):
            return {"latest": _latest.version, "url": _latest.url}
    return None


def _background(stop: threading.Event) -> None:
    global _latest
    if stop.wait(FIRST_CHECK_DELAY):
        return
    while True:
        try:
            release = latest_release()
            with _lock:
                _latest = release
        except UpdateError:
            pass  # offline or rate-limited: try again next time
        if stop.wait(CHECK_EVERY):
            return


def start_background_check() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_background, args=(stop,), name="update-check", daemon=True).start()
    return stop


# -- installing ------------------------------------------------------------------------------
def install_mode() -> str:
    if getattr(sys, "frozen", False):
        return "exe"
    if (config.ROOT / ".git").exists():
        return "git"
    return "other"


def _git(root: Path, *args: str) -> str:
    out = proc.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed: {(out.stderr or out.stdout).strip()}")
    return out.stdout


def update_git(release: Release, root: Path | None = None, reinstall: bool = True) -> None:
    root = root or config.ROOT
    if _git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise UpdateError("You have local changes in this folder, so it can't be updated automatically. "
                          "Commit or discard them first.")
    _git(root, "fetch", "--tags", "--quiet", "origin")
    _git(root, "merge", "--ff-only", release.tag)
    if reinstall:  # dependencies may have changed
        out = proc.run([sys.executable, "-m", "pip", "install", "--quiet", "-e", str(root)],
                             capture_output=True, text=True, timeout=900)
        if out.returncode != 0:
            raise UpdateError(f"Installing dependencies failed: {(out.stderr or out.stdout).strip()[-400:]}")


def verify_sha256(path: Path, expected_line: str) -> None:
    expected = expected_line.strip().split()[0].lower() if expected_line.strip() else ""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest.hexdigest() != expected:
        raise UpdateError("The downloaded file does not match its checksum; not installing it.")


DOWNLOAD_TRIES = 12   # a stalled or dropped download is picked up again where it stopped, this many times
RETRY_WAIT = 3        # seconds, doubling, at most 30


def _download(url: str, dest: Path) -> None:
    """Download `url` to `dest`. A connection that stalls or drops is resumed (or restarted if the server can't
    resume), so a slow or flaky line still gets there."""
    done, total, last_error = 0, 0, None
    dest.write_bytes(b"")
    for attempt in range(DOWNLOAD_TRIES):
        headers = {"User-Agent": f"samantha-screen-mirror/{__version__}"}
        if done:
            headers["Range"] = f"bytes={done}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                if done and resp.status != 206:   # the server sent the whole file again: start over
                    done = 0
                    dest.write_bytes(b"")
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit():
                    total = int(content_range.rsplit("/", 1)[1])
                elif not done:
                    total = int(resp.headers.get("Content-Length") or 0)
                with open(dest, "ab") as out:
                    while block := resp.read(1 << 20):
                        out.write(block)
                        done += len(block)
                        if total and sys.stdout is not None:
                            print(f"\r  downloading... {done * 100 // total}%", end="", flush=True)
            if not total or done >= total:
                if sys.stdout is not None:
                    print()
                return
            last_error = "the connection ended early"
        except OSError as exc:
            last_error = exc
        if sys.stdout is not None:
            print(f"\n  the download stalled ({last_error}); continuing...")
        time.sleep(min(30, RETRY_WAIT * 2 ** attempt))
    raise UpdateError(f"Download failed ({last_error}). Check the internet connection and try again.")


def swap_script(install: Path, new: Path, task: str, caller_pid: int, log: Path, relaunch: str = "") -> str:
    """PowerShell that replaces the install folder once this program has exited.

    `relaunch`: the name of a program in the folder to open again afterwards (the Samantha window that started it).
    """
    def q(p) -> str:
        return "'" + str(p).replace("'", "''") + "'"
    return f"""
$ErrorActionPreference = 'Stop'
$install = {q(install)}; $new = {q(new)}; $old = $install + '.old'; $task = {q(task)}; $log = {q(log)}
$relaunch = {q(relaunch)}
function Log($m) {{ Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }}
try {{
  Get-Process -Id {caller_pid} -ErrorAction SilentlyContinue | Wait-Process -Timeout 60 -ErrorAction SilentlyContinue
  # Disable the task while swapping: its 5-minute trigger would otherwise relaunch the server in the middle.
  $wasDisabled = (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue).State -eq 'Disabled'
  Disable-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue | Out-Null
  Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
  Get-Process samantha-mirror-service, samantha-mirror, Samantha -ErrorAction SilentlyContinue |
    Where-Object {{ $_.Path -and $_.Path.StartsWith($install, [StringComparison]::OrdinalIgnoreCase) }} |
    Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  if (-not (Test-Path -LiteralPath $new)) {{ throw 'the downloaded update is missing' }}
  # Move the folder's CONTENTS, never the folder itself: Windows will not rename a folder that any program has
  # open as its current directory (for example a PowerShell window the user ran `update` from).
  function Move-All($from, $to) {{
    foreach ($item in Get-ChildItem -LiteralPath $from -Force) {{
      for ($i = 0; ; $i++) {{
        try {{ Move-Item -LiteralPath $item.FullName -Destination $to -ErrorAction Stop; break }}
        catch {{ if ($i -ge 14) {{ throw }}; Start-Sleep -Seconds 2 }}   # a virus scanner may hold a file briefly
      }}
    }}
  }}
  if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Recurse -Force }}
  New-Item -ItemType Directory -Path $old | Out-Null
  try {{
    Move-All $install $old
    Move-All $new $install
  }} catch {{
    $why = $_
    foreach ($item in Get-ChildItem -LiteralPath $install -Force) {{ Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction SilentlyContinue }}
    Move-All $old $install   # put the old version back
    throw $why
  }}
  Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $new -Recurse -Force -ErrorAction SilentlyContinue
  Log 'updated'
}} catch {{ Log ('FAILED: ' + $_) }}
if (-not $wasDisabled) {{
  Enable-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue | Out-Null
  Start-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
}}
if ($relaunch) {{
  $program = Join-Path $install $relaunch
  if (Test-Path -LiteralPath $program) {{ Start-Process -FilePath $program -WorkingDirectory $install }}
}}
"""


def update_exe(release: Release, relaunch: Path | None = None) -> None:
    if not (release.zip_url and release.sha_url):
        raise UpdateError("This release has no verified Windows download yet; try again later.")
    install = Path(sys.executable).resolve().parent
    staging = install.parent / (install.name + ".update")
    work = Path(tempfile.mkdtemp(prefix="samantha-update-"))
    try:
        zip_path = work / ZIP_NAME
        print(f"  Downloading v{release.version} ({release.zip_url.rsplit('/', 1)[-1]})")
        _download(release.zip_url, zip_path)
        verify_sha256(zip_path, _get(release.sha_url).decode("utf-8", "replace"))
        print("  Checksum OK. Unpacking...")
        if staging.exists():
            proc.run(["powershell", "-NoProfile", "-Command", f"Remove-Item -LiteralPath '{staging}' -Recurse -Force"],
                           check=False, capture_output=True)
        try:
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(work / "x")
        except (zipfile.BadZipFile, OSError) as exc:
            raise UpdateError(f"The download is not a valid zip ({exc}).") from exc
        unpacked = work / "x" / "SamanthaScreenMirror"
        if not (unpacked / "samantha-mirror.exe").exists():
            raise UpdateError("The download does not look like Samantha Screen Mirror.")
        try:
            proc.run(["powershell", "-NoProfile", "-Command",
                            f"Move-Item -LiteralPath '{unpacked}' -Destination '{staging}'"],
                           check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise UpdateError(f"Could not write next to the current install ({staging}): "
                              f"{exc.stderr.decode(errors='replace').strip()}") from exc
    finally:
        proc.run(["powershell", "-NoProfile", "-Command", f"Remove-Item -LiteralPath '{work}' -Recurse -Force"],
                       check=False, capture_output=True)

    script = Path(tempfile.gettempdir()) / "samantha-update-swap.ps1"
    script.write_text(swap_script(install, staging, autostart.TASK, os.getpid(), install.parent / "update.log",
                                  relaunch.name if relaunch else ""), encoding="utf-8")
    # Detached: it waits for this program to exit, swaps the folders, then restarts the server.
    proc.start_detached(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                         "-File", str(script)])


def restart_service() -> bool:
    """Restart the start-at-logon task so a source/pip update takes effect. False if there is none."""
    if autostart.status() == "missing":
        return False
    autostart._ps(f"Stop-ScheduledTask -TaskName '{autostart.TASK}' -ErrorAction SilentlyContinue; "
                  f"Start-Sleep -Seconds 2; Start-ScheduledTask -TaskName '{autostart.TASK}'")
    return True


def run_update(check_only: bool = False, yes: bool = False) -> int:
    """The `samantha-mirror update` command."""
    try:
        release = latest_release()
    except UpdateError as exc:
        print(f"Could not check for updates: {exc}")
        return 1
    if not is_newer(release.version, __version__):
        print(f"You're up to date (v{__version__}).")
        return 0
    print(f"Update available: v{__version__} -> v{release.version}\n  {release.url}")
    if release.notes:
        print("\n  " + "\n  ".join(release.notes.splitlines()[:8]) + "\n")
    if check_only:
        return 0
    if not yes:
        from .wizard import ask
        if not ask("Install it now?", True):
            return 0

    mode = install_mode()
    try:
        if mode == "git":
            update_git(release)
            restarted = restart_service()
            print(f"Updated to v{release.version}." + (" The server was restarted." if restarted
                                                        else " Restart it with `samantha-mirror run`."))
        elif mode == "exe":
            update_exe(release)
            print("Update downloaded and verified. It finishes in a few seconds after this window closes,\n"
                  "then the server restarts by itself. (Progress is logged in update.log next to the folder.)")
        else:
            print("This copy was not installed with git or the .exe download, so it can't update itself.\n"
                  f"Get the latest from https://github.com/{REPO}/releases")
            return 1
    except UpdateError as exc:
        print(f"Update failed: {exc}")
        return 1
    return 0

