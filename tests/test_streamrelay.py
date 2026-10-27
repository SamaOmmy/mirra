"""The live link between the phone and the Mirra window (streamrelay)."""
import json
import socket
import time

import pytest

from samantha_mirror.auth import Auth
from samantha_mirror.phonelink import PhoneHub
from samantha_mirror.streamrelay import CODEC_CONFIG, KEY_FRAME, Relay, frame, read_frame, read_line

TOKEN = "k" * 32


@pytest.fixture
def relay():
    hub = PhoneHub()
    r = Relay(Auth(TOKEN), hub, max_viewers=2)
    r.listen("127.0.0.1", 0)
    yield r, hub
    r.close()


def connect(r, role, token=TOKEN):
    s = socket.create_connection(("127.0.0.1", r.port()), timeout=5)
    s.sendall(json.dumps({"token": token, "role": role}).encode() + b"\n")
    answer = json.loads(read_line(s))
    return s, answer


def frames_until(sock, kind, limit=20):
    for _ in range(limit):
        got = read_frame(sock)
        assert got is not None
        if got[0] == kind:
            return got[1]
    raise AssertionError(f"no {kind!r} frame")


def wait(cond, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_a_wrong_token_is_refused_and_counts_towards_the_lockout(relay):
    r, _ = relay
    for _ in range(10):
        s, answer = connect(r, "viewer", token="wrong" * 8)
        assert answer["ok"] is False
        s.close()
    s, answer = connect(r, "viewer")
    assert answer["ok"] is False and "Too many" in answer["error"]   # even the right token, from this address


def test_video_flows_to_the_window_and_touches_flow_to_the_phone(relay):
    r, hub = relay
    phone, ok = connect(r, "phone")
    assert ok["ok"]
    assert json.loads(frames_until(phone, b"C")) == {"t": "viewers", "n": 0}

    viewer, ok = connect(r, "viewer")
    assert ok["ok"]
    assert wait(lambda: hub.state()["watchers"] == 1)            # the phone is told (web link) to start sharing
    assert json.loads(frames_until(phone, b"C")) == {"t": "viewers", "n": 1}
    assert json.loads(frames_until(phone, b"C")) == {"t": "keyframe"}

    phone.sendall(frame(b"H", b'{"width":1080,"height":2400}'))
    phone.sendall(frame(b"V", bytes([CODEC_CONFIG]) + b"\x00\x00\x00\x01sps"))
    phone.sendall(frame(b"V", bytes([0]) + b"skipped until a key frame"))
    phone.sendall(frame(b"V", bytes([KEY_FRAME]) + b"\x00\x00\x00\x01idr"))
    assert json.loads(frames_until(viewer, b"H"))["width"] == 1080
    assert frames_until(viewer, b"V")[1:] == b"\x00\x00\x00\x01sps"
    assert frames_until(viewer, b"V")[1:] == b"\x00\x00\x00\x01idr"

    viewer.sendall(frame(b"I", b'{"t":"touch","a":"down","x":0.5,"y":0.5}'))
    assert json.loads(frames_until(phone, b"I"))["a"] == "down"
    viewer.sendall(frame(b"X", b"not allowed from a window"))
    viewer.sendall(frame(b"C", b'{"t":"quality","fps":60}'))
    assert json.loads(frames_until(phone, b"C"))["t"] == "quality"

    viewer.close()
    assert wait(lambda: hub.state()["watchers"] == 0)
    phone.close()


def test_a_window_that_joins_late_gets_the_picture_size_and_codec_first(relay):
    r, _ = relay
    phone, _ = connect(r, "phone")
    phone.sendall(frame(b"H", b'{"width":720}'))
    phone.sendall(frame(b"V", bytes([CODEC_CONFIG]) + b"cfg"))
    time.sleep(0.2)
    viewer, _ = connect(r, "viewer")
    assert frames_until(viewer, b"H") == b'{"width":720}'
    assert frames_until(viewer, b"V") == bytes([CODEC_CONFIG]) + b"cfg"
    viewer.close()
    phone.close()


def test_too_many_windows_are_refused(relay):
    r, _ = relay
    a, _ = connect(r, "viewer")
    b, _ = connect(r, "viewer")
    c, answer = connect(r, "viewer")
    assert answer["ok"] is False
    for s in (a, b, c):
        s.close()


def test_a_newer_phone_connection_replaces_the_old_one(relay):
    r, _ = relay
    old, _ = connect(r, "phone")
    new, _ = connect(r, "phone")
    assert wait(lambda: r.state()["phone"])
    try:
        assert old.recv(1024) == b""          # the relay closed the old one
    except ConnectionResetError:
        pass
    viewer, _ = connect(r, "viewer")
    new.sendall(frame(b"J", b"\xff\xd8jpeg"))
    assert frames_until(viewer, b"J") == b"\xff\xd8jpeg"
    for s in (old, new, viewer):
        s.close()
