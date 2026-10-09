"""Tests for the real audio-level sidechain (spec 2026-10-09-sidechain-pedalboard-design.md, D1)."""

from types import SimpleNamespace

import numpy as np
import pytest

from config.settings import SIDECHAIN, get_preset
from core.models import Note, Song, Track
from synthesis.audio_render import render_song_audio
from synthesis.instruments import kick as kick_voice
from synthesis.mixer import Mixer

SR = 44100


def _kick_sequence(style="goa", bpm=142, beats=8, sr=SR):
    """A buffer of one kick per beat plus the beat length, for duck-shape checks."""
    preset = get_preset(style)
    spb = 60.0 / bpm
    n = int(beats * spb * sr) + sr
    one = kick_voice(Note(pitch=36, start=0.0, duration=0.2, velocity=120), 0.2, sr, preset).astype(np.float64)
    buf = np.zeros(n)
    for b in range(beats):
        s = int(round(b * spb * sr))
        buf[s:s + len(one)] += one[: n - s]
    return buf, spb, sr


def _mini_song(beats=8, bpm=142):
    """A tiny two-track song (kick + bass) so render tests stay fast."""
    def track(name, instrument, channel, dur):
        return Track(name=name, instrument=instrument, channel=channel, program=0,
                     notes=[Note(start=float(b), duration=dur, pitch=36, velocity=120) for b in range(beats)],
                     controls=[])

    return Song(style="goa", bpm=bpm, key="Am", scale="minor", seed=7, intensity=0.7,
                length_minutes=0.1, arrangement=SimpleNamespace(total_beats=float(beats)),
                harmony=None, tracks=[track("kick", "kick", 9, 0.2), track("bass", "bass", 0, 0.5)],
                module_seeds={})


# --------------------------------------------------------------------------- audio_sidechain units

def test_audio_sidechain_peaks_at_onset_and_recovers():
    buf, spb, sr = _kick_sequence()
    d = Mixer(sample_rate=sr).audio_sidechain(buf, len(buf))
    assert d.dtype == np.float32 and d.shape == (len(buf),)
    assert 0.0 <= d.min() and d.max() <= 1.0
    per = int(round(spb * sr))
    for b in range(1, 8):
        seg = d[b * per:(b + 1) * per]
        assert np.argmax(seg) <= int(0.010 * sr)      # duck reaches full depth at the onset
        assert seg.max() > 0.9
        assert seg.min() < 0.02                        # fully recovers between kicks


@pytest.mark.parametrize("style", ["goa"])
def test_audio_sidechain_recovers_for_every_style(style):
    buf, spb, sr = _kick_sequence(style=style, bpm=143)
    d = Mixer(sample_rate=sr).audio_sidechain(buf, len(buf))
    per = int(round(spb * sr))
    assert min(d[b * per:(b + 1) * per].min() for b in range(1, 8)) < 0.02
    assert d.max() > 0.9


def test_audio_sidechain_silence_is_zero():
    m = Mixer()
    assert np.all(m.audio_sidechain(np.zeros(4410), 4410) == 0.0)
    assert np.all(m.audio_sidechain(np.zeros((4410, 2)), 4410) == 0.0)


def test_audio_sidechain_accepts_mono_and_stereo():
    buf, _, sr = _kick_sequence()
    m = Mixer(sample_rate=sr)
    mono = m.audio_sidechain(buf, len(buf))
    stereo = m.audio_sidechain(np.stack([buf, buf], axis=1), len(buf))
    assert mono.shape == stereo.shape == (len(buf),)
    assert np.allclose(mono, stereo, atol=1e-6)


def test_audio_sidechain_pads_short_input():
    d = Mixer(sample_rate=8000).audio_sidechain(np.ones(100, dtype=np.float32), 500)
    assert d.shape == (500,)


def test_mixer_sidechain_mode_is_resolved():
    assert Mixer().sidechain_mode == SIDECHAIN["mode"]
    assert Mixer(sidechain_mode="note").sidechain_mode == "note"


# --------------------------------------------------------------------------- render integration

def test_render_audio_mode_does_not_call_note_curve(monkeypatch):
    song = _mini_song()
    assert any(t.instrument == "kick" and t.notes for t in song.tracks)   # non-vacuous

    def _boom(*args, **kwargs):
        raise AssertionError("sidechain_curve must not be called in audio mode")

    monkeypatch.setattr(Mixer, "sidechain_curve", _boom)
    audio = render_song_audio(song, 8000)
    assert np.isfinite(audio).all()


def test_render_note_mode_uses_note_curve(monkeypatch):
    song = _mini_song()
    monkeypatch.setitem(SIDECHAIN, "mode", "note")
    calls = {"n": 0}
    real = Mixer.sidechain_curve

    def _spy(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Mixer, "sidechain_curve", _spy)
    audio = render_song_audio(song, 8000)
    assert calls["n"] == 1
    assert np.isfinite(audio).all()


def test_render_same_seed_is_deterministic():
    first = render_song_audio(_mini_song(), 8000)
    second = render_song_audio(_mini_song(), 8000)
    assert np.array_equal(first, second)
