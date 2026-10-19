"""PC sound: shared recording, opt-in per phone, nothing captured while nobody listens."""
import http.client
import threading
import time

import numpy as np
import pytest
from waitress import create_server

from samantha_mirror import audio
from samantha_mirror.audio import AudioError, AudioSource, to_low_data
from samantha_mirror.server import create_app
from tests.conftest import TOKEN


class FakeBackend:
    """Stands in for the Windows speakers."""

    def __init__(self, rate=48000, channels=2, fail=None):
        self.rate, self.channels, self.fail = rate, channels, fail
        self.name = "Speakers"
        self.opened = 0
        self.closed = 0
        self.push = None

    def default_name(self):
        return self.name

    def open(self, on_data):
        if self.fail:
            raise AudioError(self.fail)
        self.opened += 1
        self.push = on_data
        return self.rate, self.channels

    def close(self):
        self.closed += 1
        self.push = None

    def send(self, value=1000, frames=1024):
        self.push(np.full((frames, self.channels), value, dtype=np.int16))


def wait_for(condition, seconds=3):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def test_nothing_is_recorded_until_someone_listens():
    backend = FakeBackend()
    src = AudioSource(backend)
    assert backend.opened == 0 and src.state()["recording"] is False
    rate, channels, _ = src.add_listener()
    assert (rate, channels) == (48000, 2) and backend.opened == 1
    src.remove_listener()
    assert backend.closed == 1 and src.state() == {"enabled": True, "listeners": 0, "recording": False}


def test_listeners_share_one_recording():
    backend = FakeBackend()
    src = AudioSource(backend)
    a = src.add_listener()
    b = src.add_listener()
    assert backend.opened == 1 and src.listener_count() == 2
    backend.send(5)
    for gen in (a[2], b[2]):
        ((_, data),) = src.wait(-1, gen, timeout=0.5)
        assert np.frombuffer(data, np.int16)[0] == 5
    src.remove_listener()
    assert backend.closed == 0   # one is still listening
    src.remove_listener()
    assert backend.closed == 1


def test_a_listener_that_falls_behind_skips_ahead_instead_of_lagging():
    backend = FakeBackend()
    src = AudioSource(backend)
    _, _, gen = src.add_listener()
    for i in range(audio.KEEP_CHUNKS + 20):
        backend.send(i)
    first = src.wait(-1, gen)
    assert len(first) == audio.KEEP_CHUNKS   # first read: everything that is kept
    last = first[-1][0]
    for i in range(audio.KEEP_CHUNKS + 20):
        backend.send(i)
    skipped = src.wait(last, gen)
    assert len(skipped) == audio.CATCH_UP_TO and skipped[-1][0] == last + audio.KEEP_CHUNKS + 20


def test_silence_returns_an_empty_list_not_a_hang():
    src = AudioSource(FakeBackend())
    _, _, gen = src.add_listener()
    t0 = time.perf_counter()
    assert src.wait(-1, gen, timeout=0.1) == []
    assert time.perf_counter() - t0 < 1


def test_switched_off_on_the_pc():
    src = AudioSource(FakeBackend(), enabled=False)
    with pytest.raises(AudioError, match="SM_AUDIO"):
        src.add_listener()


def test_cannot_record_is_reported_and_not_counted_as_a_listener():
    src = AudioSource(FakeBackend(fail="no speakers"))
    with pytest.raises(AudioError, match="no speakers"):
        src.add_listener()
    assert src.listener_count() == 0


def test_following_a_speaker_change_makes_listeners_reconnect(monkeypatch):
    monkeypatch.setattr(audio, "WATCH_EVERY", 0.05)
    backend = FakeBackend()
    src = AudioSource(backend)
    _, _, gen = src.add_listener()
    backend.name = "Headphones"
    backend.rate = 44100
    assert wait_for(lambda: backend.opened == 2)
    assert src.wait(-1, gen, timeout=0.2) is None       # the old listener is told to reconnect
    rate, _, new_gen = src.add_listener()                 # the reconnect gets the new format
    assert rate == 44100 and new_gen != gen
    src.remove_listener()
    src.remove_listener()


def test_stopping_does_not_deadlock_with_a_busy_recording():
    """Windows waits for the capture callback when a stream is closed, so closing must not hold the data lock."""
    backend = FakeBackend()
    src = AudioSource(backend)
    src.add_listener()
    stop = threading.Event()

    def producer():
        while not stop.is_set():
            push = backend.push
            if push:
                push(np.zeros((64, 2), dtype=np.int16))
            time.sleep(0.001)

    t = threading.Thread(target=producer)
    t.start()
    try:
        done = threading.Thread(target=src.remove_listener)
        done.start()
        done.join(3)
        assert not done.is_alive()
    finally:
        stop.set()
        t.join()


def test_low_data_is_mono_at_half_the_rate():
    stereo = np.array([[100, 300], [100, 300], [200, 400], [200, 400]], dtype=np.int16).tobytes()
    out = np.frombuffer(to_low_data(stereo, 2), dtype=np.int16)
    assert list(out) == [200, 300]   # (100+300)/2 = 200 twice -> 200; (200+400)/2 = 300 twice -> 300


# -- over HTTP --------------------------------------------------------------------------------------
def _serve(cfg, backend):
    sound = AudioSource(backend, enabled=cfg.audio)
    server = create_server(create_app(cfg, sound), listen="127.0.0.1:0", threads=8, send_bytes=1)
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(0.2)
    return server, sound


def _open(port, path, token=TOKEN):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Authorization": f"Bearer {token}"})
    return conn, conn.getresponse()


def test_audio_needs_the_token(cfg):
    server, _ = _serve(cfg, FakeBackend())
    try:
        conn, resp = _open(server.effective_port, "/api/audio", token="wrong")
        assert resp.status == 401
        conn.close()
    finally:
        server.close()


def test_audio_streams_pcm_and_stops_recording_when_the_phone_leaves(cfg):
    backend = FakeBackend()
    server, sound = _serve(cfg, backend)
    try:
        conn, resp = _open(server.effective_port, "/api/audio")
        assert resp.status == 200
        assert resp.getheader("X-Audio-Rate") == "48000" and resp.getheader("X-Audio-Channels") == "2"
        assert wait_for(lambda: backend.push is not None)
        assert resp.read(2 * 2 * 480) == bytes(2 * 2 * 480)   # 10 ms of silence opens the stream at once
        backend.send(1234, frames=256)
        data = resp.read(256 * 4)
        assert len(data) == 256 * 4 and np.frombuffer(data, np.int16)[0] == 1234
        assert sound.state()["listeners"] == 1
        resp.close()   # (the response holds the socket open, not just the connection)
        conn.close()
        # The server notices the phone is gone at its next write; silence is written about every second.
        assert wait_for(lambda: sound.listener_count() == 0, seconds=6)
        assert backend.closed == 1
    finally:
        server.close()


def test_audio_low_data_halves_rate_and_goes_mono(cfg):
    backend = FakeBackend()
    server, _ = _serve(cfg, backend)
    try:
        conn, resp = _open(server.effective_port, "/api/audio?q=low")
        assert resp.getheader("X-Audio-Rate") == "24000" and resp.getheader("X-Audio-Channels") == "1"
        assert wait_for(lambda: backend.push is not None)
        backend.send(800, frames=512)
        assert len(resp.read(256 * 2)) == 256 * 2
        conn.close()
    finally:
        server.close()


def test_audio_refused_with_a_reason_when_it_cannot_record(cfg):
    server, _ = _serve(cfg, FakeBackend(fail="no speakers"))
    try:
        conn, resp = _open(server.effective_port, "/api/audio")
        assert resp.status == 409 and b"no speakers" in resp.read()
        conn.close()
    finally:
        server.close()


def test_state_tells_the_page_whether_sound_is_available(client):
    data = client.get("/api/state", headers={"Authorization": f"Bearer {TOKEN}"}).get_json()
    assert data["audio"] == {"enabled": True, "listeners": 0, "recording": False}


def test_a_backend_that_has_its_own_id_is_compared_by_id_not_name(monkeypatch):
    """Windows ids tell speakers apart even when two of them share a name; a rename alone changes nothing."""
    monkeypatch.setattr(audio, "WATCH_EVERY", 0.05)

    class WithId(FakeBackend):
        ident = "{0.0.0.00000000}.{aaa}"

        def default_id(self):
            return self.ident

    backend = WithId()
    src = AudioSource(backend)
    src.add_listener()
    backend.name = "Renamed speakers"
    time.sleep(0.3)
    assert backend.opened == 1                       # same id: nothing restarted
    backend.ident = "{0.0.0.00000000}.{bbb}"
    assert wait_for(lambda: backend.opened == 2)     # new id: followed
    src.remove_listener()


def test_the_real_windows_speaker_id_can_be_read():
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows only")
    try:
        ident = audio.Loopback().default_id()
    except Exception as exc:   # a CI machine without any audio device
        pytest.skip(f"no audio device: {exc}")
    assert ident == audio.Loopback().default_id() and ident
