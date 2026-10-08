"""
Post-render mastering: EQ, light stereo widening, bus compression, soft-knee
peak control and peak normalisation of a rendered WAV file.

Pure NumPy/SciPy (built on :mod:`synthesis.dsp`), so it adds no dependencies
and works for both the built-in synthesizer output and FluidSynth renders.

Chain: zero-phase high-pass / EQ -> mid-side width -> bus compressor ->
soft-knee limiter -> peak normalise.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from scipy import signal

from config.settings import MASTERING
from synthesis import dsp
from synthesis.audio_render import write_wav


def read_wav(path) -> Tuple[np.ndarray, int, int]:
    """Read a PCM WAV file.

    Returns ``(audio, sample_rate, bit_depth)`` where ``audio`` is a float32
    array of shape ``(n, channels)`` in [-1, 1].
    """
    with wave.open(str(Path(path)), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if sample_width == 1:                       # 8-bit WAV is unsigned
        data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
        bit_depth = 8
    elif sample_width == 2:
        data = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
        bit_depth = 16
    elif sample_width == 3:
        bytes_ = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        values = bytes_[:, 0] | (bytes_[:, 1] << 8) | (bytes_[:, 2] << 16)
        values = np.where(values & 0x800000, values - 0x1000000, values)   # sign extend
        data = values.astype(np.float32) / 8388608.0
        bit_depth = 24
    elif sample_width == 4:                     # 32-bit PCM (the wave module rejects float WAVs)
        data = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
        bit_depth = 32
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes")

    return data.reshape(-1, n_channels), sample_rate, bit_depth


class AudioProcessor:
    """Mastering chain for a rendered track.

    * EQ: zero-phase high-pass (no phase smear on the kick), a small low-mid
      cut, presence and air boosts.
    * Mid/side stereo widening (skipped for mono).
    * Gentle bus compression with fast attack / slow release ballistics.
    * Soft-knee peak control, so EQ-boosted transients don't force the final
      normalisation to turn the whole track down.
    * Peak normalisation to ``target_peak_db``.
    """

    def __init__(self, highpass_hz: float = MASTERING["highpass_hz"],
                 lowmid_hz: float = MASTERING["lowmid_hz"], lowmid_db: float = MASTERING["lowmid_db"],
                 presence_hz: float = MASTERING["presence_hz"], presence_db: float = MASTERING["presence_db"],
                 air_hz: float = MASTERING["air_hz"], air_db: float = MASTERING["air_db"],
                 width: float = MASTERING["width"], threshold_db: float = MASTERING["threshold_db"],
                 ratio: float = MASTERING["ratio"], attack_ms: float = MASTERING["attack_ms"],
                 release_ms: float = MASTERING["release_ms"],
                 knee_threshold: float = MASTERING["knee_threshold"],
                 knee_ceiling: float = MASTERING["knee_ceiling"],
                 target_peak_db: float = MASTERING["target_peak_db"]):
        if ratio < 1.0:
            raise ValueError("ratio must be >= 1.0")
        if width < 0.0:
            raise ValueError("width must be >= 0.0")
        if attack_ms <= 0 or release_ms <= 0:
            raise ValueError("attack_ms and release_ms must be positive")
        if not 0.0 < knee_threshold < knee_ceiling:
            raise ValueError("knee_threshold must be positive and below knee_ceiling")
        self.highpass_hz = highpass_hz
        self.lowmid_hz, self.lowmid_db = lowmid_hz, lowmid_db
        self.presence_hz, self.presence_db = presence_hz, presence_db
        self.air_hz, self.air_db = air_hz, air_db
        self.width = width
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.knee_threshold = knee_threshold
        self.knee_ceiling = knee_ceiling
        self.target_peak_db = target_peak_db

    # ------------------------------------------------------------------ stages
    def _eq(self, x: np.ndarray, sr: int) -> np.ndarray:
        x = dsp.highpass(x, self.highpass_hz, sr, order=2, zero_phase=True)
        x = dsp.peaking(x, self.lowmid_hz, self.lowmid_db, sr, q=1.0)
        x = dsp.peaking(x, self.presence_hz, self.presence_db, sr, q=0.8)
        return dsp.peaking(x, self.air_hz, self.air_db, sr, q=0.7)

    def _widen(self, x: np.ndarray) -> np.ndarray:
        """Mid/side width: boosts the side signal, keeps the mid untouched."""
        if x.shape[1] < 2 or abs(self.width - 1.0) < 1e-3:
            return x
        mid = (x[:, 0] + x[:, 1]) * np.float32(0.5)
        side = (x[:, 0] - x[:, 1]) * np.float32(0.5 * self.width)
        out = np.empty_like(x)
        out[:, 0] = mid + side
        out[:, 1] = mid - side
        return out

    def _compress(self, x: np.ndarray, sr: int) -> np.ndarray:
        """Feed-forward bus compressor (in place on ``x``).

        The envelope follower is the maximum of a fast (attack) and a slow
        (release) one-pole smoothing of the peak detector, which approximates
        asymmetric ballistics while staying fully vectorised.
        """
        det = np.maximum(np.abs(x[:, 0]), np.abs(x[:, 1]))
        att = np.float32(np.exp(-1.0 / (self.attack_ms * 0.001 * sr)))
        rel = np.float32(np.exp(-1.0 / (self.release_ms * 0.001 * sr)))
        fast = signal.lfilter(np.asarray([1.0 - att], dtype=np.float32),
                              np.asarray([1.0, -att], dtype=np.float32), det)
        slow = signal.lfilter(np.asarray([1.0 - rel], dtype=np.float32),
                              np.asarray([1.0, -rel], dtype=np.float32), det)
        env = np.maximum(fast, slow)
        del fast, slow, det

        # gain computer + in-place chain to keep memory down on long tracks:
        # env -> env (dBFS) -> excess over threshold -> gain reduction (dB) -> linear gain
        np.maximum(env, np.float32(1e-6), out=env)
        np.log10(env, out=env)
        env *= np.float32(20.0)
        env -= np.float32(self.threshold_db)                      # excess above threshold
        env *= np.float32(-(1.0 - 1.0 / self.ratio))              # negative = gain reduction
        np.minimum(env, np.float32(0.0), out=env)                 # below threshold: no change
        env *= np.float32(1.0 / 20.0)
        np.power(np.float32(10.0), env, out=env)
        x *= env[:, None]
        return x

    def _soft_limit(self, x: np.ndarray) -> np.ndarray:
        """Soft-knee limiter: linear below ``knee_threshold``, tanh-shaped up to
        ``knee_ceiling``. Absorbs transient overshoots (EQ-boosted kicks,
        crashes) so the final normalisation doesn't scale the whole mix down."""
        ax = np.abs(x)
        over = ax > self.knee_threshold
        if not over.any():
            return x
        span = self.knee_ceiling - self.knee_threshold
        shaped = self.knee_threshold + span * np.tanh((ax[over] - self.knee_threshold) / span)
        out = x.copy()
        out[over] = np.sign(x[over]) * shaped
        return out

    def _normalize(self, x: np.ndarray) -> np.ndarray:
        peak = float(np.abs(x).max()) if x.size else 0.0
        if peak > 0.0:
            target = float(10.0 ** (self.target_peak_db / 20.0))
            x *= np.float32(target / peak)
        return x

    # ------------------------------------------------------------------ chain
    def process(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """Return a mastered copy of ``audio`` – a float array shaped (n, 1) or (n, 2)."""
        x = np.array(audio, dtype=np.float32, copy=True)
        if x.ndim == 1:
            x = x[:, None]
        if x.ndim != 2 or x.shape[1] not in (1, 2):
            raise ValueError(f"Expected a mono or stereo array, got shape {x.shape}")
        if not np.isfinite(x).all():
            raise ValueError("Audio contains non-finite samples")
        if x.shape[0] == 0:
            return x
        x = self._eq(x, sample_rate)
        x = self._widen(x)
        x = self._compress(x, sample_rate)
        x = self._soft_limit(x)
        return self._normalize(x)


def process_audio(input_file, output_file: Optional[str] = None,
                  processor: Optional[AudioProcessor] = None) -> str:
    """Read a WAV file, master it and write the result.

    The default output is ``<input>_mastered.wav`` next to the input, so the
    raw render is kept. Returns the path of the written file.
    """
    audio, sample_rate, bit_depth = read_wav(input_file)
    mastered = (processor or AudioProcessor()).process(audio, sample_rate)
    if output_file is None:
        input_path = Path(input_file)
        output_file = input_path.with_name(input_path.stem + "_mastered.wav")
    # write_wav only supports 16/24-bit – keep the source depth when possible
    out_bits = bit_depth if bit_depth in (16, 24) else (16 if bit_depth < 16 else 24)
    return write_wav(mastered, output_file, sample_rate, out_bits)
