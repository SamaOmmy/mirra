"""The relay between the Android app and the PC page: validation, flow of commands and pictures, access control."""
import http.client
import json
import threading
import time

import pytest
from waitress import create_server

from samantha_mirror import phonelink, server
from samantha_mirror.phonelink import BadInput, PhoneHub, parse_input
from samantha_mirror.server import create_app
from tests.conftest import TOKEN

BEARER = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


# -- input validation ---------------------------------------------------------------------------
def test_good_events_are_accepted_and_cleaned():
    assert parse_input({"t": "tap", "x": 0.5, "y": 1, "junk": 1}) == {"t": "tap", "x": 0.5, "y": 1.0}
    assert parse_input({"t": "long", "x": 0, "y": 0})["t"] == "long"
    assert parse_input({"t": "key", "k": "home"}) == {"t": "key", "k": "home"}
    assert parse_input({"t": "text", "s": "hello"}) == {"t": "text", "s": "hello"}
    swipe = parse_input({"t": "gesture", "pts": [[0.5, 0.8], [0.5, 0.2]], "ms": 250})
    assert swipe == {"t": "gesture", "pts": [[0.5, 0.8], [0.5, 0.2]], "ms": 250}


@pytest.mark.parametrize("bad", [
    None, [], "tap", {}, {"t": "reboot"},
    {"t": "tap", "x": 2, "y": 0}, {"t": "tap", "x": -0.1, "y": 0}, {"t": "tap", "x": "0.5", "y": 0},
    {"t": "tap", "x": True, "y": 0}, {"t": "tap", "x": float("nan"), "y": 0}, {"t": "tap", "y": 0},
    {"t": "key", "k": "poweroff"}, {"t": "key"},
    {"t": "text", "s": ""}, {"t": "text", "s": "x" * 501}, {"t": "text", "s": 5},
    {"t": "gesture", "pts": [[0, 0]], "ms": 100}, {"t": "gesture", "pts": [[0, 0]] * 201, "ms": 100},
    {"t": "gesture", "pts": [[0, 0], [1]], "ms": 100}, {"t": "gesture", "pts": [[0, 0], [1, 9]], "ms": 100},
    {"t": "gesture", "pts": [[0, 0], [1, 1]], "ms": 0}, {"t": "gesture", "pts": [[0, 0], [1, 1]], "ms": 10**6},
    {"t": "gesture", "pts": "ab", "ms": 100},
])
def test_bad_events_are_refused(bad):
    with pytest.raises(BadInput):
        parse_input(bad)


# -- the hub -------------------------------------------------------------------------------------
def test_nothing_is_connected_at_first():
    hub = PhoneHub()
    state = hub.state()
    assert state["connected"] is False and state["seq"] == 0
    assert hub.send_input({"t": "tap", "x": 0, "y": 0}) is False
    assert hub.wait_frame(-1, timeout=0) is None


def test_hello_tells_the_phone_whether_anyone_is_watching():
    hub = PhoneHub()
    hub.hello({"device": "Pixel", "version": "1", "control": True})
    assert hub.next_commands(0) == [{"t": "watch", "on": False}]
    hub.add_watcher()
    assert hub.next_commands(0) == [{"t": "watch", "on": True}]
    hub.hello({"device": "Pixel"})   # a restarted app asks again
    assert hub.next_commands(0) == [{"t": "watch", "on": True}]


def test_watch_commands_follow_the_first_and_last_watcher():
    hub = PhoneHub()
    hub.hello({"device": "p"})
    hub.next_commands(0)
    hub.add_watcher()
    hub.add_watcher()
    hub.remove_watcher()
    assert hub.next_commands(0) == [{"t": "watch", "on": True}]   # only the first one told the phone
    hub.remove_watcher()
    assert hub.next_commands(0) == [{"t": "watch", "on": False}]
    hub.remove_watcher()   # never goes negative
    assert hub.state()["watchers"] == 0


def test_input_reaches_a_waiting_phone_at_once():
    hub = PhoneHub()
    hub.hello({"device": "p"})
    hub.next_commands(0)
    got = []
    t = threading.Thread(target=lambda: got.append(hub.next_commands(5)))
    t.start()
    time.sleep(0.2)
    t0 = time.perf_counter()
    assert hub.send_input({"t": "key", "k": "back"})
    t.join(2)
    assert got == [[{"t": "key", "k": "back"}]] and time.perf_counter() - t0 < 0.5


def test_a_phone_that_forbids_control_gets_no_input():
    hub = PhoneHub()
    hub.hello({"device": "p", "control": False})
    assert hub.state()["control"] is False
    assert hub.send_input({"t": "key", "k": "back"}) is False


def test_a_silent_phone_counts_as_gone(monkeypatch):
    hub = PhoneHub()
    hub.hello({"device": "p"})
    assert hub.state()["connected"]
    monkeypatch.setattr(phonelink, "GONE_AFTER", -1)
    assert hub.state()["connected"] is False
    assert hub.send_input({"t": "key", "k": "back"}) is False


def test_a_newer_request_from_the_phone_ends_the_older_one():
    hub = PhoneHub()
    hub.hello({"device": "p"})
    hub.next_commands(0)
    old = []
    t = threading.Thread(target=lambda: old.append(hub.next_commands(10)))
    t.start()
    time.sleep(0.2)
    t0 = time.perf_counter()
    new = []
    t2 = threading.Thread(target=lambda: new.append(hub.next_commands(10)))
    t2.start()
    t.join(2)
    assert old == [[]] and time.perf_counter() - t0 < 1   # released at once, not after 10 s
    hub.send_input({"t": "key", "k": "home"})
    t2.join(2)
    assert new == [[{"t": "key", "k": "home"}]]


def test_pictures_flow_to_the_page():
    hub = PhoneHub()
    hub.push_frame(JPEG, 720, 1600)
    seq, frame = hub.wait_frame(-1, timeout=0)
    assert frame == JPEG and hub.state()["width"] == 720 and hub.state()["height"] == 1600
    assert hub.wait_frame(seq, timeout=0.05) is None     # nothing newer
    hub.push_frame(JPEG + b"2", 720, 1600)
    assert hub.wait_frame(seq, timeout=0)[0] == seq + 1


# -- over HTTP -----------------------------------------------------------------------------------
def _serve(cfg, hub):
    srv = create_server(create_app(cfg, phone=hub), listen="127.0.0.1:0", threads=8, send_bytes=1)
    threading.Thread(target=srv.run, daemon=True).start()
    time.sleep(0.2)
    return srv


def _call(port, method, path, body=None, headers=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    data = raw if raw is not None else (json.dumps(body) if body is not None else None)
    hdr = {"Content-Type": "application/json", **(headers or {})}
    conn.request(method, path, body=data, headers=hdr)
    resp = conn.getresponse()
    out = resp.read()
    conn.close()
    return resp.status, out


def test_every_phone_endpoint_needs_the_token(cfg):
    srv = _serve(cfg, PhoneHub())
    port = srv.effective_port
    try:
        for method, path in [("GET", "/api/phone/state"), ("GET", "/api/phone/pair"), ("GET", "/api/phone/app.apk"),
                             ("POST", "/api/phone/hello"), ("GET", "/api/phone/commands"), ("POST", "/api/phone/frame"),
                             ("GET", "/api/phone/stream"), ("POST", "/api/phone/input")]:
            assert _call(port, method, path, {} if method == "POST" else None)[0] == 401, path
    finally:
        srv.close()


def test_the_phone_page_itself_is_public_like_the_rest_of_the_app(cfg):
    srv = _serve(cfg, PhoneHub())
    try:
        assert _call(srv.effective_port, "GET", "/phone")[0] in (200, 500)   # 500 only if the web app is not built
    finally:
        srv.close()


def test_a_whole_session_over_http(cfg):
    hub = PhoneHub()
    srv = _serve(cfg, hub)
    port = srv.effective_port
    try:
        status, body = _call(port, "POST", "/api/phone/hello", {"device": "Pixel 8", "version": "0.5.0", "control": True,
                                                                "width": 1080, "height": 2400}, BEARER)
        assert status == 200 and json.loads(body)["poll"] == phonelink.POLL_SECONDS
        assert json.loads(_call(port, "GET", "/api/phone/commands", headers=BEARER)[1]) == [{"t": "watch", "on": False}]

        state = json.loads(_call(port, "GET", "/api/phone/state", headers=BEARER)[1])
        assert state["connected"] and state["device"] == "Pixel 8" and state["control"] is True

        status, body = _call(port, "POST", "/api/phone/input", {"t": "tap", "x": 0.25, "y": 0.75}, BEARER)
        assert status == 200
        assert json.loads(_call(port, "GET", "/api/phone/commands", headers=BEARER)[1]) == [{"t": "tap", "x": 0.25, "y": 0.75}]

        assert _call(port, "POST", "/api/phone/input", {"t": "tap", "x": 9, "y": 0}, BEARER)[0] == 400
        assert _call(port, "POST", "/api/phone/frame", raw=b"not a jpeg", headers={**BEARER, "Content-Type": "image/jpeg"})[0] == 400
        assert _call(port, "POST", "/api/phone/frame", raw=JPEG,
                     headers={**BEARER, "Content-Type": "image/jpeg", "X-Width": "720", "X-Height": "1600"})[0] == 200
        assert hub.state()["seq"] == 1 and hub.state()["width"] == 720
    finally:
        srv.close()


def test_a_page_that_watches_gets_the_picture_and_the_phone_is_told(cfg):
    hub = PhoneHub()
    hub.hello({"device": "p"})
    hub.next_commands(0)
    hub.push_frame(JPEG, 720, 1600)
    srv = _serve(cfg, hub)
    port = srv.effective_port
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
        conn.request("GET", "/api/phone/stream", headers=BEARER)
        resp = conn.getresponse()
        assert resp.status == 200 and "multipart/x-mixed-replace" in resp.getheader("Content-Type")
        chunk = resp.read(120)
        assert b"image/jpeg" in chunk and b"\xff\xd8" in chunk
        assert hub.state()["watchers"] == 1
        assert hub.next_commands(0) == [{"t": "watch", "on": True}]
        resp.close()
        conn.close()
    finally:
        srv.close()


def test_input_without_a_phone_is_refused_clearly(cfg):
    srv = _serve(cfg, PhoneHub())
    try:
        status, body = _call(srv.effective_port, "POST", "/api/phone/input", {"t": "key", "k": "back"}, BEARER)
        assert status == 409 and b"not connected" in body
    finally:
        srv.close()


def test_pairing_hands_the_token_only_to_someone_who_has_it(cfg):
    srv = _serve(cfg, PhoneHub())
    try:
        assert json.loads(_call(srv.effective_port, "GET", "/api/phone/pair", headers=BEARER)[1]) == {"token": TOKEN}
    finally:
        srv.close()


def test_the_app_download_says_so_when_it_is_missing(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "PHONE_APP", tmp_path / "nope.apk")
    srv = _serve(cfg, PhoneHub())
    try:
        status, body = _call(srv.effective_port, "GET", "/api/phone/app.apk", headers=BEARER)
        assert status == 404 and b"does not include" in body
    finally:
        srv.close()


def test_the_app_is_downloaded_as_an_apk(cfg, monkeypatch, tmp_path):
    apk = tmp_path / "SamanthaPhone.apk"
    apk.write_bytes(b"PK\x03\x04apk")
    monkeypatch.setattr(server, "PHONE_APP", apk)
    srv = _serve(cfg, PhoneHub())
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.effective_port, timeout=8)
        conn.request("GET", "/api/phone/app.apk", headers=BEARER)
        resp = conn.getresponse()
        assert resp.status == 200 and resp.getheader("Content-Type") == "application/vnd.android.package-archive"
        assert resp.read() == b"PK\x03\x04apk"
        conn.close()
    finally:
        srv.close()
