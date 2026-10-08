"""Tests for the post-render mastering stage (synthesis/audio_processor.py)."""

import numpy as np
import pytest
from scipy import signal

from core.generator import TranceGenerator
from synthesis import dsp
from synthesis.audio_processor import AudioProcessor, process_audio, read_wav
from synthesis.audio_render import write_wav


def _tone(freq: float, amp: float, seconds: float, sr: int) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _band_energy(sig: np.ndarray, lo: float, hi: float, sr: int) -> float:
    band = dsp.bandpass(sig, lo, hi, sr)
    return float(np.sum(band[2000:-2000] ** 2))          # skip filter transients


# --------------------------------------------------------------------------- dsp.peaking

def test_peaking_filter_boosts_target_band():
    sr = 16000
    x = _tone(1000, 0.4, 1.0, sr) + _tone(4000, 0.4, 1.0, sr)
    y = dsp.peaking(x, 1000, 6.0, sr, q=1.0)
    before = _band_energy(x, 700, 1400, sr) / _band_energy(x, 3400, 4600, sr)
    after = _band_energy(y, 700, 1400, sr) / _band_energy(y, 3400, 4600, sr)
    assert after > before * 1.5


def test_peaking_cut_reduces_target_band():
    sr = 16000
    x = _tone(300, 0.5, 1.0, sr) + _tone(4000, 0.5, 1.0, sr)
    y = dsp.peaking(x, 300, -6.0, sr, q=1.0)
    assert _band_energy(y, 200, 420, sr) < _band_energy(x, 200, 420, sr)


# --------------------------------------------------------------------------- processor

def test_compressor_reduces_dynamic_range():
    sr = 8000
    loud, quiet = _tone(150, 0.9, 1.0, sr), _tone(150, 0.05, 1.0, sr)
    x = np.stack([np.concatenate([loud, quiet])] * 2, axis=1)

    # level-matched check of the compressor stage itself: the loud part must be
    # turned down and the quiet part (below threshold) must pass unchanged
    y = AudioProcessor()._compress(x.copy(), sr)
    cut = float(np.abs(y[2000:len(loud) - 2000]).max()) / float(np.abs(x[2000:len(loud) - 2000]).max())
    untouched = float(np.abs(y[len(loud) + 2000:]).max()) / float(np.abs(x[len(loud) + 2000:]).max())
    assert cut < 0.8
    assert untouched == pytest.approx(1.0, abs=0.05)

    # and the full chain reduces the loud/quiet ratio
    z = AudioProcessor().process(x, sr)

    def seg_peak(arr, start, end):
        return float(np.abs(arr[start:end]).max())

    before = seg_peak(x, 0, len(loud)) / seg_peak(x, len(loud), len(x))
    after = seg_peak(z, 0, len(loud)) / seg_peak(z, len(loud), len(z))
    assert after < before * 0.9


def test_widen_preserves_distinct_channels():
    sr = 8000
    x = np.stack([_tone(100, 0.8, 0.5, sr), _tone(300, 0.4, 0.5, sr)], axis=1)
    y = AudioProcessor().process(x, sr)
    assert y.shape == x.shape and np.isfinite(y).all()
    assert not np.allclose(y[:, 0], y[:, 1], atol=1e-3)   # not collapsed to mono


def test_processor_rejects_bad_input():
    with pytest.raises(ValueError):
        AudioProcessor().process(np.array([np.nan]), 8000)
    with pytest.raises(ValueError):
        AudioProcessor().process(np.zeros((10, 5)), 8000)
    with pytest.raises(ValueError):
        AudioProcessor(ratio=0.5)
    with pytest.raises(ValueError):
        AudioProcessor(knee_threshold=0.8, knee_ceiling=0.6)


def test_mastering_preserves_loudness():
    """Guards against the classic mastering regressions: the mastered track must
    not come out quieter (RMS) or peakier (crest) than the raw render."""
    sr = 16000
    t = np.arange(sr * 2) / sr
    tone = (0.30 * np.sin(2 * np.pi * 60 * t) + 0.20 * np.sin(2 * np.pi * 200 * t)
            + 0.12 * np.sin(2 * np.pi * 800 * t) + 0.08 * np.sin(2 * np.pi * 3000 * t)
            + 0.05 * np.sin(2 * np.pi * 6000 * t))
    env = np.where(t < 1.0, 1.0, 0.35)                       # loud intro, quiet half
    left = (tone * env).astype(np.float32)
    x = np.stack([left, np.roll(left, 23)], axis=1)

    y = AudioProcessor().process(x, sr)
    rms_in = float(np.sqrt((x ** 2).mean()))
    rms_out = float(np.sqrt((y ** 2).mean()))
    crest_in = 20 * np.log10(np.abs(x).max() / rms_in)
    crest_out = 20 * np.log10(np.abs(y).max() / rms_out)

    assert rms_out >= rms_in * 0.85
    assert crest_out <= crest_in + 1.5
    assert float(np.abs(y).max()) == pytest.approx(10 ** (-1.0 / 20), abs=0.005)


def test_highpass_removes_rumble_but_keeps_bass():
    sr = 8000
    t = np.arange(sr * 2) / sr
    x = np.stack([(0.4 * np.sin(2 * np.pi * 12 * t)
                   + 0.4 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)] * 2, axis=1)
    y = AudioProcessor().process(x, sr)

    def band_rms(a, lo, hi):
        sos = signal.butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
        b = signal.sosfilt(sos, a, axis=0)
        return float(np.sqrt((b ** 2).mean()))

    assert band_rms(y, 1, 18) < band_rms(x, 1, 18) * 0.5     # 12 Hz rumble gone
    assert band_rms(y, 55, 65) > band_rms(x, 55, 65) * 0.7   # kick fundamental kept


# --------------------------------------------------------------------------- file level

def test_process_audio_writes_mastered_copy(tmp_path):
    sr = 8000
    x = np.stack([_tone(100, 0.9, 2.0, sr), _tone(300, 0.3, 2.0, sr)], axis=1)
    src = write_wav(x, tmp_path / "raw.wav", sr, 16)

    out = process_audio(src)
    assert out != src and (tmp_path / "raw_mastered.wav").exists()

    mastered, out_sr, bits = read_wav(out)
    assert out_sr == sr and bits == 16
    assert mastered.shape == x.shape
    assert np.isfinite(mastered).all()
    assert float(np.abs(mastered).max()) == pytest.approx(10 ** (-1.0 / 20), abs=0.005)
    assert not np.allclose(mastered[:, 0], mastered[:, 1], atol=1e-3)


def test_process_audio_respects_output_file(tmp_path):
    sr = 8000
    src = write_wav(np.zeros((sr, 2), dtype=np.float32), tmp_path / "silence.wav", sr, 16)
    out = process_audio(src, str(tmp_path / "custom.wav"))
    assert out == str(tmp_path / "custom.wav")
    audio, _, _ = read_wav(out)
    assert audio.shape == (sr, 2)


def test_process_audio_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_audio(str(tmp_path / "nope.wav"))


# --------------------------------------------------------------------------- generator flag

def test_generate_master_flag(monkeypatch, tmp_path):
    fake = str(tmp_path / "fake.wav")

    def render(self, midi_path=None, output_format="wav", output_path=None, song=None, progress=None):
        return fake

    monkeypatch.setattr("synthesis.audio_render.AudioGenerator.render", render)
    gen = TranceGenerator(style="goa", seed=8, length_minutes=1, output_dir=tmp_path, verbose=False)

    skipped = gen.generate(render_audio=True, master=False)
    assert skipped["audio_path"] == fake and skipped["errors"] == []

    attempted = gen.generate(render_audio=True, master=True)
    assert attempted["audio_path"] == fake                # raw render kept on failure
    assert any(e.startswith("Mastering failed") for e in attempted["errors"])
