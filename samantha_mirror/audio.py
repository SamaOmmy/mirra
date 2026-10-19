"""Optional PC sound for the phone.

Windows can hand us a copy of whatever it is playing (WASAPI "loopback" of the default
speakers). One capture is shared by every listener and only runs while someone listens, so
with sound off nothing is captured. Nobody hears anything unless a phone asks for it in its
settings: this module just makes the sound available.

The stream is raw 16-bit PCM. It is sent as it is captured (no codec): about 1.5 Mbit/s for
stereo, or a quarter of that in "low data" mode (mono, half the sample rate).
"""
import logging
import threading
from collections import deque

import numpy as np

log = logging.getLogger("screen-mirror")

FRAMES = 1024           # samples per channel per capture callback (~21 ms at 48 kHz)
KEEP_CHUNKS = 48        # about a second of sound is kept for listeners that fall behind
CATCH_UP_TO = 4         # a listener that fell further behind than KEEP_CHUNKS resumes this close to live
WATCH_EVERY = 2.0       # seconds between checks for a changed default speaker (headphones plugged in)
SILENCE_WAIT = 0.5      # a listener wakes this often even when the PC is silent (to notice it disconnected)


class AudioError(Exception):
    """Sound can't be captured; the message says why and is shown to the user."""


def _default_speaker_id() -> str:
    """Windows' id of the default speakers, asked directly: PortAudio keeps the list of devices from when it started,
    so it would not notice headphones being plugged in."""
    import ctypes
    from ctypes import HRESULT, POINTER, c_int, c_void_p

    import comtypes
    from comtypes import COMMETHOD, GUID, IUnknown

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = (
            COMMETHOD([], HRESULT, "Activate"),
            COMMETHOD([], HRESULT, "OpenPropertyStore"),
            COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_void_p), "ppstrId")),
            COMMETHOD([], HRESULT, "GetState"),
        )

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = (
            COMMETHOD([], HRESULT, "EnumAudioEndpoints"),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_int, "dataFlow"), (["in"], c_int, "role"),
                      (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
        )

    comtypes.CoInitialize()   # this runs on a background thread
    try:
        enumerator = comtypes.CoCreateInstance(GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), IMMDeviceEnumerator,
                                               comtypes.CLSCTX_INPROC_SERVER)
        raw = enumerator.GetDefaultAudioEndpoint(0, 0).GetId()   # eRender, eConsole
        try:
            return ctypes.wstring_at(raw)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(c_void_p(raw))
    finally:
        comtypes.CoUninitialize()


class Loopback:
    """Windows: records what the default speakers play."""

    def __init__(self):
        self._pa = None
        self._stream = None
        self._channels = 2

    @staticmethod
    def _import():
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            raise AudioError("PC sound needs Windows (and the pyaudiowpatch package).")
        return pyaudio

    def default_name(self) -> str:
        """Name of the speakers Windows is using right now. A fresh PortAudio each time, since it caches devices."""
        pyaudio = self._import()
        pa = pyaudio.PyAudio()
        try:
            return pa.get_default_wasapi_loopback()["name"]
        except Exception as exc:
            raise AudioError(f"No speakers to record from ({exc}).")
        finally:
            pa.terminate()

    def default_id(self) -> str:
        """Changes when Windows switches to other speakers (headphones, a Bluetooth headset...)."""
        try:
            return _default_speaker_id()
        except Exception:
            return self.default_name()

    def open(self, on_data) -> tuple[int, int]:
        """Start recording; on_data(int16 array shaped (frames, channels)) gets each piece. Returns (rate, channels)."""
        pyaudio = self._import()
        pa = pyaudio.PyAudio()
        try:
            dev = pa.get_default_wasapi_loopback()
            rate, channels = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])

            def callback(data, frame_count, time_info, status):
                pcm = np.frombuffer(data, dtype=np.int16).reshape(-1, channels)
                on_data(pcm[:, :2] if channels > 2 else pcm)  # surround: keep front left/right
                return None, pyaudio.paContinue

            stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=rate, frames_per_buffer=FRAMES,
                             input=True, input_device_index=dev["index"], stream_callback=callback)
        except AudioError:
            pa.terminate()
            raise
        except Exception as exc:
            pa.terminate()
            raise AudioError(f"Could not record the PC's sound ({exc}).")
        self._pa, self._stream, self._channels = pa, stream, min(channels, 2)
        return rate, self._channels

    def close(self):
        stream, pa, self._stream, self._pa = self._stream, self._pa, None, None
        try:
            if stream:
                stream.stop_stream()
                stream.close()
        finally:
            if pa:
                pa.terminate()


class AudioSource:
    """Shared recording with any number of listeners. Safe to call from several threads.

    Two locks: `_ctl` serialises starting/stopping the recording (slow Windows calls), `_cond` guards the
    audio data and is also taken by the capture callback. The slow calls never run under `_cond`: stopping
    a Windows audio stream waits for its callback, which would deadlock.
    """

    def __init__(self, backend=None, enabled=True):
        self.enabled = enabled
        self._backend = backend or Loopback()
        self._ctl = threading.Lock()
        self._cond = threading.Condition()
        self._chunks: deque = deque(maxlen=KEEP_CHUNKS)   # (seq, bytes)
        self._seq = 0
        self._listeners = 0
        self._format = None        # (rate, channels) while recording
        self._generation = 0       # changes when the recording is restarted (new speakers)
        self._name = ""            # for the log
        self._ident = ""           # compared to notice a speaker change
        self._stopping = threading.Event()

    def _identity(self) -> str:
        return (getattr(self._backend, "default_id", None) or self._backend.default_name)()

    # -- state ---------------------------------------------------------------------------
    def state(self) -> dict:
        with self._cond:
            return {"enabled": self.enabled, "listeners": self._listeners, "recording": self._format is not None}

    def listener_count(self) -> int:
        with self._cond:
            return self._listeners

    # -- listeners -----------------------------------------------------------------------
    def add_listener(self) -> tuple[int, int, int]:
        """Join. Starts recording if this is the first listener. Returns (rate, channels, generation)."""
        if not self.enabled:
            raise AudioError("PC sound is switched off on the PC (SM_AUDIO=0).")
        with self._ctl:
            if self._format is None:  # first listener, or the recording could not follow a speaker change
                self._start()
            with self._cond:
                self._listeners += 1
                return (*self._format, self._generation)

    def remove_listener(self):
        with self._ctl:
            with self._cond:
                self._listeners = max(0, self._listeners - 1)
                last = self._listeners == 0
            if last:
                self._stop()

    def wait(self, last_seq: int, generation: int, timeout: float = SILENCE_WAIT):
        """Chunks newer than last_seq as [(seq, bytes), ...] (empty when the PC is silent).
        Returns None when the recording was restarted: the listener should reconnect."""
        with self._cond:
            if self._generation != generation or self._format is None:
                return None
            if not self._chunks or self._chunks[-1][0] <= last_seq:
                self._cond.wait(timeout)
                if self._generation != generation or self._format is None:
                    return None
            fresh = [c for c in self._chunks if c[0] > last_seq]
            if fresh and last_seq >= 0 and fresh[0][0] > last_seq + 1:
                fresh = fresh[-CATCH_UP_TO:]  # we were too slow and chunks were dropped: skip ahead
            return fresh

    # -- recording -----------------------------------------------------------------------
    def _on_data(self, pcm):
        data = np.ascontiguousarray(pcm).tobytes()
        with self._cond:
            self._seq += 1
            self._chunks.append((self._seq, data))
            self._cond.notify_all()

    def _start(self):  # called with _ctl held
        name = self._backend.default_name()
        ident = self._identity()
        fmt = self._backend.open(self._on_data)
        with self._cond:
            self._name, self._ident, self._format = name, ident, fmt
            self._generation += 1
            self._chunks.clear()
        self._stopping = threading.Event()
        threading.Thread(target=self._watch, args=(self._stopping,), name="audio-watch", daemon=True).start()
        log.info("PC sound: recording %s (%d Hz, %d channels)", name or "speakers", *fmt)

    def _stop(self):  # called with _ctl held
        self._stopping.set()
        with self._cond:
            self._format = None
            self._cond.notify_all()
        try:
            self._backend.close()
        except Exception:
            log.exception("PC sound: closing the recording failed")
        log.info("PC sound: stopped (no listeners)")

    def _watch(self, stopping):
        """Follow the default speakers: when they change, restart the recording on the new ones."""
        while not stopping.wait(WATCH_EVERY):
            try:
                ident = self._identity()
            except Exception:
                continue
            if ident == self._ident:
                continue
            with self._ctl:
                if stopping.is_set():
                    return
                fmt, name = None, ""
                try:
                    self._backend.close()
                    name = self._backend.default_name()
                    log.info("PC sound: speakers changed to %s", name)
                    fmt = self._backend.open(self._on_data)
                except Exception as exc:
                    log.warning("PC sound: could not follow the new speakers: %s", exc)
                with self._cond:
                    self._name, self._ident, self._format = name, ident, fmt
                    self._generation += 1   # listeners reconnect and pick up the new format (or the error)
                    self._cond.notify_all()


def to_low_data(pcm: bytes, channels: int) -> bytes:
    """Mono at half the sample rate: a quarter of the data (the caller halves the rate it announces)."""
    samples = np.frombuffer(pcm, dtype=np.int16).reshape(-1, channels).astype(np.int32)
    mono = samples.mean(axis=1)
    mono = mono[: len(mono) // 2 * 2].reshape(-1, 2).mean(axis=1)
    return mono.astype(np.int16).tobytes()
