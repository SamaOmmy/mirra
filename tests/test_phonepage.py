"""`samantha-mirror phone` opens the page, and the Android app builds."""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from samantha_mirror import phonepage, tailscale

ROOT = Path(__file__).resolve().parent.parent


def test_the_address_uses_loopback_when_the_server_listens_there(cfg, monkeypatch):
    monkeypatch.setattr(tailscale, "tailscale_ip", lambda: "100.64.0.9")
    assert phonepage.page_address(cfg).startswith("http://100.64.0.9:8787/phone")   # loopback is off by default
    looped = type(cfg)(**{**cfg.__dict__, "loopback": True})
    assert phonepage.page_address(looped) == "http://127.0.0.1:8787/phone"
    assert phonepage.page_address(looped, with_token=True).endswith("/phone?token=" + cfg.token)


def test_only_print_does_not_open_a_browser(cfg, monkeypatch, capsys):
    monkeypatch.setattr(tailscale, "tailscale_ip", lambda: "100.64.0.9")
    opened = []
    monkeypatch.setattr(phonepage.webbrowser, "open", opened.append)
    assert phonepage.open_phone_page(only_print=True) == 0
    printed = capsys.readouterr().out
    assert opened == [] and "100.64.0.9:8787/phone" in printed
    assert cfg.token not in printed


def test_a_stopped_server_is_explained_instead_of_opening_an_error_page(cfg, monkeypatch, capsys):
    monkeypatch.setattr(tailscale, "tailscale_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(phonepage.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    opened = []
    monkeypatch.setattr(phonepage.webbrowser, "open", opened.append)
    assert phonepage.open_phone_page() == 1
    assert opened == [] and "samantha-mirror start" in capsys.readouterr().out


def test_the_token_is_only_in_the_opened_address_not_in_what_is_printed(cfg, monkeypatch, capsys):
    monkeypatch.setattr(tailscale, "tailscale_ip", lambda: "100.64.0.9")

    class Fine:
        def close(self):
            pass

    monkeypatch.setattr(phonepage.urllib.request, "urlopen", lambda *a, **k: Fine())
    opened = []
    monkeypatch.setattr(phonepage.webbrowser, "open", opened.append)
    assert phonepage.open_phone_page() == 0
    assert opened == [f"http://100.64.0.9:8787/phone?token={cfg.token}"]
    assert cfg.token not in capsys.readouterr().out


# -- the Android app ----------------------------------------------------------------------------
def _android_tools_present() -> bool:
    sys.path.insert(0, str(ROOT / "android"))
    try:
        import build
        build.find_sdk()
        build.find_jdk_tool("javac")
        return True
    except SystemExit:
        return False
    finally:
        sys.path.pop(0)


@pytest.mark.skipif(not _android_tools_present(), reason="needs the Android SDK and a JDK")
def test_the_android_app_builds_and_is_a_valid_signed_apk(tmp_path):
    out = tmp_path / "SamanthaPhone.apk"
    env = {**os.environ, "SM_APK_OUT": str(out)}
    env.pop("SM_KEYSTORE", None)
    # keep the throwaway signing key out of the repository folder
    keystore = ROOT / "android" / "dev.keystore"
    existed = keystore.exists()
    try:
        result = subprocess.run([sys.executable, str(ROOT / "android" / "build.py")], env=env, capture_output=True, text=True)
    finally:
        if not existed and keystore.exists():
            keystore.unlink()
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(out) as apk:
        names = apk.namelist()
    assert "classes.dex" in names and "AndroidManifest.xml" in names
    assert any(n.startswith("META-INF/") for n in names)   # signed


def test_the_apk_is_not_committed_but_its_folder_ships(monkeypatch):
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "phone_app/*.apk" in ignored and "*.keystore" in ignored
    if shutil.which("git"):
        tracked = subprocess.run(["git", "ls-files", "--", "*.apk", "*.keystore"], cwd=ROOT, capture_output=True, text=True).stdout
        assert tracked.strip() == ""
