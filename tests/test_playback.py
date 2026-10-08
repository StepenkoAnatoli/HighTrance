# tests/test_playback.py
"""Player decode/stream/seek behaviour — no real device, no keyboard."""
import numpy as np
import pytest

from synthesis.audio_render import write_wav
from synthesis.playback import PlaybackError, Player

SR = 8000


def make_wav(tmp_path, seconds=1.0, channels=2, name="t.wav"):
    n = int(seconds * SR)
    rs = np.random.RandomState(0)
    audio = (rs.rand(n, channels).astype(np.float32) * 0.2) - 0.1
    path = write_wav(audio, tmp_path / name, SR)
    return path, audio


class FakeStream:
    def __init__(self):
        self.started = self.stopped = self.closed = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def close(self): self.closed = True


def player(tmp_path, seconds=1.0, channels=2, **kw):
    path, audio = make_wav(tmp_path, seconds, channels)
    kw.setdefault("interactive", False)
    kw.setdefault("stream_factory", FakeStream)
    return Player(path, **kw), audio


def test_decode_stereo(tmp_path):
    p, audio = player(tmp_path)
    assert p.data.dtype == np.float32 and p.data.shape == audio.shape
    assert p.samplerate == SR
    assert p.duration == pytest.approx(1.0)


def test_mono_promoted_to_stereo(tmp_path):
    p, _ = player(tmp_path, channels=1)
    assert p.data.ndim == 2 and p.data.shape[1] == 2
    assert np.allclose(p.data[:, 0], p.data[:, 1])


def test_playback_fills_frames(tmp_path):
    p, audio = player(tmp_path)
    p.play()
    out = np.zeros((256, 2), dtype=np.float32)
    p.callback(out, 256)
    # atol: the WAV round-trip quantizes to 16-bit PCM (max error 1.83e-5);
    # sample-to-sample differences are ~0.06+, so ordering/offset errors still fail.
    assert np.allclose(out, audio[:256], atol=1e-4)
    assert p.position == 256 and p.playing


def test_paused_outputs_silence(tmp_path):
    p, _ = player(tmp_path)
    p.play(); p.pause()
    out = np.ones((256, 2), dtype=np.float32)
    p.callback(out, 256)
    assert not out.any() and p.position == 0


def test_eof_stops_and_silences(tmp_path):
    p, _ = player(tmp_path, seconds=0.1)     # 800 frames
    p.play()
    out = np.zeros((1024, 2), dtype=np.float32)
    p.callback(out, 1024)
    assert not p.playing and p.position == 800
    assert not out[800:].any()


def test_play_after_eof_restarts(tmp_path):
    p, _ = player(tmp_path, seconds=0.1)
    p.play()
    p.callback(np.zeros((1024, 2), np.float32), 1024)
    assert not p.playing and p.position == 800
    p.play()
    assert p.position == 0 and p.playing


def test_seek_clamps(tmp_path):
    p, _ = player(tmp_path, seconds=1.0)
    p.seek(-50.0)
    assert p.position == 0
    p.seek(10_000.0)
    assert p.position == len(p.data)
    p.seek(-0.5)
    assert p.position == len(p.data) - int(0.5 * SR)


def test_rewind(tmp_path):
    p, _ = player(tmp_path)
    p.seek(0.4)
    p.rewind()
    assert p.position == 0


def test_toggle_and_stop(tmp_path):
    p, _ = player(tmp_path)
    p.toggle()
    assert p.playing
    p.toggle()
    assert not p.playing
    p.play(); p.stop()
    assert not p.playing and p._stream is None


def test_non_interactive_listen_returns_without_device(tmp_path):
    p, _ = player(tmp_path)
    p.listen()          # no keyboard, no device — returns immediately
    assert p._stream is None


def test_missing_file_raises(tmp_path):
    with pytest.raises(Exception):
        Player(tmp_path / "nope.wav")
