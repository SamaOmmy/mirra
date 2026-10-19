"""Settings loaded from the environment / .env file. Nothing secret is hardcoded.

Where files live: when run from a source checkout (pyproject.toml next to the package)
everything stays in that folder; otherwise in %APPDATA%/SamanthaScreenMirror.
Set SM_HOME to use any other folder.
"""
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MIN_TOKEN_LEN = 16


def data_dir() -> Path:
    override = os.environ.get("SM_HOME", "").strip()
    if override:
        path = Path(override)
    elif (ROOT / "pyproject.toml").exists():
        path = ROOT
    else:
        path = Path(os.environ.get("APPDATA", Path.home())) / "SamanthaScreenMirror"
    path.mkdir(parents=True, exist_ok=True)
    return path


def env_path() -> Path:
    return data_dir() / ".env"


def log_path() -> Path:
    return data_dir() / "samantha-mirror.log"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def set_env_value(key: str, value: str) -> None:
    """Set KEY=value in the .env file, keeping comments and other lines. Creates it if missing."""
    path = env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_env() -> bool:
    """Create the .env file with a fresh token if there isn't one. Returns True if created."""
    path = env_path()
    if path.exists() and re.search(r"^\s*SM_TOKEN\s*=\s*\S{%d,}" % MIN_TOKEN_LEN, path.read_text(encoding="utf-8"), re.M):
        return False
    example = ROOT / ".env.example"
    if not path.exists():
        template = example.read_text(encoding="utf-8") if example.exists() else (
            "# Samantha Screen Mirror settings. Never share or commit this file.\nSM_TOKEN=\n")
        path.write_text(template, encoding="utf-8")
    set_env_value("SM_TOKEN", new_token())
    return True


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    token: str
    port: int
    monitor: int
    fps: int
    jpeg_quality: int
    scale: float
    max_clients: int
    cursor: bool
    loopback: bool
    capture: str
    update_check: bool
    audio: bool


# Valid ranges for settings that can also be changed live from the web app.
LIMITS = {"fps": (1, 60), "quality": (10, 95), "scale": (0.1, 1.0)}


def _num(name, default, cast, lo, hi):
    raw = os.environ.get(name, "").strip()
    try:
        value = cast(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}")
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _flag(name, default):
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be 1 or 0, got {raw!r}")


def _choice(name, default, options):
    raw = os.environ.get(name, "").strip().lower() or default
    if raw not in options:
        raise ConfigError(f"{name} must be one of {', '.join(options)}, got {raw!r}")
    return raw


def load() -> Config:
    load_dotenv(env_path())
    token = os.environ.get("SM_TOKEN", "").strip()
    if len(token) < MIN_TOKEN_LEN:
        raise ConfigError(
            f"SM_TOKEN is missing or shorter than {MIN_TOKEN_LEN} characters. "
            "Run `samantha-mirror setup` to create it."
        )
    return Config(
        token=token,
        port=_num("SM_PORT", 8787, int, 1024, 65535),
        monitor=_num("SM_MONITOR", 1, int, 0, 32),
        fps=_num("SM_FPS", 30, int, *LIMITS["fps"]),
        jpeg_quality=_num("SM_JPEG_QUALITY", 70, int, *LIMITS["quality"]),
        scale=_num("SM_SCALE", 0.75, float, *LIMITS["scale"]),
        max_clients=_num("SM_MAX_CLIENTS", 3, int, 1, 16),
        cursor=_flag("SM_CURSOR", True),
        loopback=_flag("SM_LOOPBACK", False),
        capture=_choice("SM_CAPTURE", "auto", ("auto", "dxgi", "mss")),
        update_check=_flag("SM_UPDATE_CHECK", True),
        audio=_flag("SM_AUDIO", True),
    )
