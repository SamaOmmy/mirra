"""The Android app: it builds into a signed APK, and its networking code works against a real server.

The networking classes (Net, Mjpeg) are plain Java, so they run here on an ordinary JVM. Skipped without a JDK
and the Android SDK.
"""
import io
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from waitress import create_server

from samantha_mirror import capture
from samantha_mirror.pairing import Pairing
from samantha_mirror.server import create_app
from tests.conftest import TOKEN
from tests.test_capture_pacing import FakeGrabber

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"


def _tools():
    sys.path.insert(0, str(ANDROID))
    try:
        import build
        sdk = build.find_sdk()
        platforms = sorted(p for p in (sdk / "platforms").iterdir() if (p / "android.jar").exists())
        return build.find_jdk_tool("javac"), build.find_jdk_tool("java"), platforms[-1] / "android.jar"
    except (SystemExit, IndexError, OSError):
        return None
    finally:
        sys.path.pop(0)


TOOLS = _tools()
needs_tools = pytest.mark.skipif(TOOLS is None, reason="needs a JDK and the Android SDK")


@needs_tools
def test_the_android_app_builds_and_is_a_valid_signed_apk(tmp_path):
    out = tmp_path / "SamanthaPhone.apk"
    env = {**os.environ, "SM_APK_OUT": str(out)}
    env.pop("SM_KEYSTORE", None)
    keystore = ANDROID / "dev.keystore"
    existed = keystore.exists()
    try:
        result = subprocess.run([sys.executable, str(ANDROID / "build.py")], env=env, capture_output=True, text=True)
    finally:
        if not existed and keystore.exists():
            keystore.unlink()   # keep a throwaway signing key out of the repository folder
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(out) as apk:
        names = apk.namelist()
    assert "classes.dex" in names and "AndroidManifest.xml" in names
    assert any(n.startswith("META-INF/") for n in names)   # signed
    # Samantha Setup carries this very app and installs it (so Android 13+ does not restrict it)
    with zipfile.ZipFile(out.with_name("SamanthaSetup.apk")) as setup:
        assert setup.read("assets/Samantha.apk") == out.read_bytes()
        assert any(n.startswith("META-INF/") for n in setup.namelist())


@needs_tools
def test_the_apps_networking_code_works_against_a_real_server(cfg, tmp_path, monkeypatch):
    javac, java, android_jar = TOOLS
    src = ANDROID / "src" / "app" / "samantha" / "phone"
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-encoding", "UTF-8", "-cp", str(android_jar), "-d", str(classes),
                               str(src / "Net.java"), str(src / "Mjpeg.java"), str(ANDROID / "test" / "NetCheck.java")],
                              capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr

    # Stand-ins for the screen capture: a small real JPEG, a new one every frame.
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (40, 80, 160)).save(buf, "JPEG")
    monkeypatch.setattr(capture.FrameSource, "_open_grabber", lambda self, monitor: FakeGrabber())
    monkeypatch.setattr(capture.FrameSource, "_encode", staticmethod(lambda *a: (buf.getvalue(), (64, 36))))

    pairing = Pairing()
    code = pairing.new_code()["code"]
    app = create_app(cfg, pairing=pairing)
    server = create_server(app, listen="127.0.0.1:0", threads=6, send_bytes=1)
    port = server.effective_port
    threading.Thread(target=server.run, daemon=True).start()
    try:
        run = subprocess.run([java, "-cp", str(classes), "app.samantha.phone.NetCheck", f"127.0.0.1:{port}", TOKEN, code],
                             capture_output=True, text=True, timeout=90)
    finally:
        server.close()
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all good" in run.stdout


def test_the_apk_is_not_committed_but_its_folder_ships():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "phone_app/*.apk" in ignored and "*.keystore" in ignored
    if shutil.which("git"):
        tracked = subprocess.run(["git", "ls-files", "--", "*.apk", "*.keystore"], cwd=ROOT, capture_output=True, text=True).stdout
        assert tracked.strip() == ""
