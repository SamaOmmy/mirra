"""Start Menu and Desktop shortcuts to the Mirra window (packaged .exe only).

Older versions' shortcuts (and taskbar pins) opened the console program (before 0.5) or Samantha.exe (0.5). Those are
pointed at Mirra.exe instead, and on the Desktop and in the Start Menu renamed to "Mirra", so they keep working after
the update. Only shortcuts that point into this install folder are touched.
"""
import os
import sys
from pathlib import Path

from . import proc

NAME = "Mirra"
WINDOW_EXE = "Mirra.exe"
OLD_EXES = ("samantha-mirror.exe", "Samantha.exe")


def _q(text) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _desktop() -> Path:
    """The real Desktop folder (OneDrive often moves it away from %USERPROFILE%\\Desktop)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:   # CSIDL_DESKTOPDIRECTORY
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path.home() / "Desktop"


def _folders() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA", Path.home()))
    return [_desktop(), appdata / "Microsoft/Windows/Start Menu/Programs",
            appdata / "Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar"]


def window_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve().with_name(WINDOW_EXE)
    return exe if exe.exists() else None


def script(window: Path, folders: list[Path], create: bool) -> str:
    """PowerShell: retarget old shortcuts in `folders` to `window`, and (if `create`) add the Start Menu and
    Desktop shortcuts."""
    olds = ", ".join(_q(window.with_name(name)) for name in OLD_EXES)
    renamable = ", ".join(_q(f) for f in folders[:2])   # not taskbar pins: renaming those unpins them
    lines = [
        "$shell = New-Object -ComObject WScript.Shell",
        f"$window = {_q(window)}; $olds = @({olds}); $renamable = @({renamable})",
        f"foreach ($dir in @({', '.join(_q(f) for f in folders)})) {{",
        "  if (-not (Test-Path -LiteralPath $dir)) { continue }",
        "  foreach ($file in Get-ChildItem -LiteralPath $dir -Filter *.lnk -ErrorAction SilentlyContinue) {",
        "    $link = $shell.CreateShortcut($file.FullName)",
        "    if (($olds -contains $link.TargetPath) -and -not $link.Arguments) {",
        "      $link.TargetPath = $window; $link.WorkingDirectory = (Split-Path $window); $link.IconLocation = $window + ',0'",
        "      $link.Save()",
        f"      $named = Join-Path $dir '{NAME}.lnk'",
        "      if (($renamable -contains $dir) -and $file.Name -ne 'Mirra.lnk' -and -not (Test-Path -LiteralPath $named)) {",
        "        Rename-Item -LiteralPath $file.FullName -NewName 'Mirra.lnk' -ErrorAction SilentlyContinue",
        "      }",
        "    }",
        "  }",
        "}",
    ]
    if create:
        for folder in folders[:2]:
            path = folder / f"{NAME}.lnk"
            lines += [
                f"if ((Test-Path -LiteralPath {_q(folder)}) -and -not (Test-Path -LiteralPath {_q(path)})) {{",
                f"  $link = $shell.CreateShortcut({_q(path)})",
                "  $link.TargetPath = $window; $link.WorkingDirectory = (Split-Path $window)",
                "  $link.Description = 'See your PC on your phone and your phone on this PC'; $link.Save()",
                "}",
            ]
    return "\n".join(lines)


def update(create: bool = False) -> bool:
    """Fix old shortcuts (and create new ones if asked). False when there is no window program to point at."""
    window = window_exe()
    if window is None:
        return False
    proc.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script(window, _folders(), create)],
             capture_output=True, timeout=60)
    return True
