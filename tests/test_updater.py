import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from samantha_mirror import __version__, updater

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


@pytest.mark.parametrize("latest,current,newer", [
    ("0.3.1", "0.3.0", True), ("v0.4.0", "0.3.9", True), ("1.0", "0.9.9", True),
    ("0.3.0", "0.3.0", False), ("0.2.9", "0.3.0", False), ("v0.10.0", "0.9.0", True),
])
def test_version_comparison(latest, current, newer):
    assert updater.is_newer(latest, current) is newer


def test_garbage_version_is_rejected():
    with pytest.raises(ValueError):
        updater.parse_version("latest")


def api_json(tag="v9.9.9", zip_url=None, sha_url=None):
    prefix = updater.DOWNLOAD_PREFIX + tag + "/"
    return json.dumps({
        "tag_name": tag, "html_url": "https://github.com/x/y/releases/tag/" + tag, "body": "notes",
        "assets": [
            {"name": updater.ZIP_NAME, "browser_download_url": zip_url or prefix + updater.ZIP_NAME},
            {"name": updater.SUM_NAME, "browser_download_url": sha_url or prefix + updater.SUM_NAME},
        ]}).encode()


def test_latest_release_is_parsed(monkeypatch):
    monkeypatch.setattr(updater, "_get", lambda url, **kw: api_json())
    rel = updater.latest_release()
    assert (rel.tag, rel.version) == ("v9.9.9", "9.9.9")
    assert rel.zip_url.endswith(updater.ZIP_NAME) and rel.sha_url.endswith(updater.SUM_NAME)
    assert updater.available() == rel


def test_up_to_date_means_no_update(monkeypatch):
    monkeypatch.setattr(updater, "_get", lambda url, **kw: api_json(tag="v" + __version__))
    assert updater.available() is None


def test_downloads_must_come_from_the_projects_release_page(monkeypatch):
    evil = "https://evil.example.com/Mirra-for-Windows.zip"
    monkeypatch.setattr(updater, "_get", lambda url, **kw: api_json(zip_url=evil))
    with pytest.raises(updater.UpdateError, match="refusing"):
        updater.latest_release()


def test_nonsense_from_github_is_an_update_error(monkeypatch):
    monkeypatch.setattr(updater, "_get", lambda url, **kw: b"<html>rate limited</html>")
    with pytest.raises(updater.UpdateError):
        updater.latest_release()


def test_app_only_shows_an_update_when_one_is_newer(monkeypatch):
    rel = updater.Release("v9.9.9", "9.9.9", "https://example.com", "", None, None)
    monkeypatch.setattr(updater, "_latest", rel)
    assert updater.cached_info() == {"latest": "9.9.9", "url": "https://example.com"}
    monkeypatch.setattr(updater, "_latest", updater.Release("v0.0.1", "0.0.1", "u", "", None, None))
    assert updater.cached_info() is None
    monkeypatch.setattr(updater, "_latest", None)
    assert updater.cached_info() is None


def test_state_endpoint_carries_the_update_notice(client, monkeypatch):
    from tests.conftest import TOKEN
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/state", headers=headers).get_json()["update"] is None
    monkeypatch.setattr(updater, "_latest", updater.Release("v9.9.9", "9.9.9", "u", "", None, None))
    assert client.get("/api/state", headers=headers).get_json()["update"]["latest"] == "9.9.9"


def test_checksum_is_enforced(tmp_path):
    f = tmp_path / "x.zip"
    f.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    updater.verify_sha256(f, f"{good}  x.zip\n")  # no exception
    for bad in (hashlib.sha256(b"other").hexdigest() + "  x.zip", "", "not-a-hash  x.zip"):
        with pytest.raises(updater.UpdateError, match="checksum"):
            updater.verify_sha256(f, bad)


# -- real git updates on temporary repositories ----------------------------------------------
def git(cwd, *args):
    import os
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


@pytest.fixture
def repos(tmp_path):
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    (origin / "app.txt").write_text("v1")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "one")
    git(origin, "tag", "v0.3.0")
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    (origin / "app.txt").write_text("v2")
    git(origin, "commit", "-q", "-am", "two")
    git(origin, "tag", "v0.3.1")
    return origin, clone


def release(tag):
    return updater.Release(tag, tag.lstrip("v"), "u", "", None, None)


def test_git_update_fast_forwards_to_the_release_tag(repos):
    _, clone = repos
    assert (clone / "app.txt").read_text() == "v1"
    updater.update_git(release("v0.3.1"), root=clone, reinstall=False)
    assert (clone / "app.txt").read_text() == "v2"


def test_git_update_refuses_to_touch_local_changes(repos):
    _, clone = repos
    (clone / "app.txt").write_text("my edit")
    with pytest.raises(updater.UpdateError, match="local changes"):
        updater.update_git(release("v0.3.1"), root=clone, reinstall=False)
    assert (clone / "app.txt").read_text() == "my edit"


# -- swapping the .exe folder ----------------------------------------------------------------
pytestmark_ps = pytest.mark.skipif(shutil.which("powershell") is None, reason="needs Windows PowerShell")


def run_swap(tmp_path: Path, new_exists: bool):
    install = tmp_path / "SamanthaScreenMirror"
    new = tmp_path / "SamanthaScreenMirror.update"
    install.mkdir()
    (install / "old.txt").write_text("old")
    if new_exists:
        new.mkdir()
        (new / "new.txt").write_text("new")
    log = tmp_path / "update.log"
    script = tmp_path / "swap.ps1"
    # A task name that does not exist and a process id that has already exited: both are harmless no-ops.
    script.write_text(updater.swap_script(install, new, "NoSuchTask-SamanthaTest", 999999, log), encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                   check=True, capture_output=True, timeout=120)
    return install, log


@pytestmark_ps
def test_swap_replaces_the_folder(tmp_path):
    install, log = run_swap(tmp_path, new_exists=True)
    assert (install / "new.txt").exists() and not (install / "old.txt").exists()
    assert not (tmp_path / "SamanthaScreenMirror.old").exists()
    assert "updated" in log.read_text()


@pytestmark_ps
def test_a_failed_swap_puts_the_old_version_back(tmp_path):
    install, log = run_swap(tmp_path, new_exists=False)  # the staged folder is missing: the swap must fail
    assert (install / "old.txt").exists()
    assert "FAILED" in log.read_text()


def _task_state(name: str) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-ScheduledTask -TaskName '{name}').State"],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


@pytestmark_ps
@pytest.mark.parametrize("disabled", [True, False])
def test_swap_leaves_the_task_as_it_found_it(tmp_path, disabled):
    """A server stopped on purpose must stay stopped; a running one must come back (and not be relaunched mid-swap)."""
    name = f"SamanthaSwapTest{'Off' if disabled else 'On'}"
    ps = (f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c exit'; "
          f"$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddDays(30); "
          f"Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $t -Force | Out-Null; "
          + (f"Disable-ScheduledTask -TaskName '{name}' | Out-Null" if disabled else ""))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, timeout=60)
    try:
        install = tmp_path / "SamanthaScreenMirror"
        new = tmp_path / "SamanthaScreenMirror.update"
        install.mkdir()
        new.mkdir()
        script = tmp_path / "swap.ps1"
        script.write_text(updater.swap_script(install, new, name, 999999, tmp_path / "update.log"), encoding="utf-8")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       check=True, capture_output=True, timeout=120)
        assert (_task_state(name) == "Disabled") is disabled
    finally:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false -ErrorAction SilentlyContinue"],
                       capture_output=True, timeout=60)


@pytestmark_ps
def test_swap_works_while_a_program_sits_inside_the_install_folder(tmp_path):
    """The README tells people to run `update` from the program's folder, and Windows will not rename a folder
    that a program (their PowerShell window) has as its current directory. The swap must not need to."""
    install = tmp_path / "SamanthaScreenMirror"
    new = tmp_path / "SamanthaScreenMirror.update"
    install.mkdir()
    (install / "old.txt").write_text("old")
    new.mkdir()
    (new / "new.txt").write_text("new")
    (new / "_internal").mkdir()
    (new / "_internal" / "lib.txt").write_text("lib")
    holder = subprocess.Popen(["powershell", "-NoProfile", "-Command", "Start-Sleep 120"], cwd=install)
    try:
        time.sleep(2)  # let it start, so the folder really is in use
        script = tmp_path / "swap.ps1"
        script.write_text(updater.swap_script(install, new, "NoSuchTask-SamanthaTest", 999999, tmp_path / "update.log"),
                          encoding="utf-8")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       check=True, capture_output=True, timeout=120)
    finally:
        holder.kill()
    assert (install / "new.txt").exists() and (install / "_internal" / "lib.txt").exists()
    assert not (install / "old.txt").exists() and not new.exists() and not (tmp_path / "SamanthaScreenMirror.old").exists()
    assert "updated" in (tmp_path / "update.log").read_text()


class _FlakyServer:
    """Serves `data`; the first `drops` responses send only part of it and then cut the connection.
    `ranges=False` ignores Range requests (sends the whole file again), like some download servers."""

    def __init__(self, data: bytes, drops: int, ranges: bool = True):
        import http.server
        import threading

        outer = self
        self.requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                rng = self.headers.get("Range")
                outer.requests.append(rng)
                start = int(rng[6:-1]) if rng and ranges else 0
                body = data[start:]
                self.send_response(206 if start else 200)
                if start:
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if len(outer.requests) <= drops:
                    self.wfile.write(body[: len(body) // 3])
                    self.wfile.flush()
                    self.connection.shutdown(2)   # drop the line mid-download
                    return
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/file.zip"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.mark.parametrize("ranges", [True, False])
def test_a_dropped_download_is_picked_up_again(tmp_path, monkeypatch, ranges):
    monkeypatch.setattr(updater, "RETRY_WAIT", 0)
    data = bytes(range(256)) * 4000
    server = _FlakyServer(data, drops=2, ranges=ranges)
    try:
        updater._download(server.url, tmp_path / "f.zip")
    finally:
        server.close()
    assert (tmp_path / "f.zip").read_bytes() == data
    assert len(server.requests) == 3
    if ranges:
        assert server.requests[0] is None and server.requests[1].startswith("bytes=")   # resumed, not restarted


def test_a_download_that_never_finishes_gives_up_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "RETRY_WAIT", 0)
    monkeypatch.setattr(updater, "DOWNLOAD_TRIES", 3)
    server = _FlakyServer(b"x" * 300_000, drops=99)
    try:
        with pytest.raises(updater.UpdateError, match="Download failed"):
            updater._download(server.url, tmp_path / "f.zip")
    finally:
        server.close()
