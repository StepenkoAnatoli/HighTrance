"""
Mixer
Basic volume, panning, kick-triggered sidechain, simple EQ, bus compression,
tempo-synced ping-pong delay, reverb and a master glue compressor / limiter.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

import numpy as np
from scipy import ndimage, signal

from config.settings import DEFAULTS, SIDECHAIN, MixSettings, get_mix
from synthesis import dsp


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


class Mixer:
    def __init__(self, intensity: float = DEFAULTS["intensity"], sample_rate: int = DEFAULTS["sample_rate"],
                 bpm: float = DEFAULTS["bpm"], reverb_size: float = 2.6, delay_feedback: float = 0.45,
                 overrides: Optional[Dict[str, MixSettings]] = None,
                 sidechain_mode: Optional[str] = None):
        self.intensity = intensity
        self.sr = sample_rate
        self.bpm = bpm
        self.reverb_size = reverb_size
        self.delay_feedback = delay_feedback
        self.overrides = overrides or {}
        # Resolve at construction time (not as a default arg) so config/tests can override it.
        self.sidechain_mode = sidechain_mode or SIDECHAIN["mode"]

    def settings(self, track_name: str) -> MixSettings:
        return self.overrides.get(track_name) or get_mix(track_name)

    # ------------------------------------------------------------------ building blocks
    def sidechain_curve(self, kick_times: Iterable[float], n: int, release: float = 0.11) -> np.ndarray:
        """0..1 ducking curve: 1 right at every kick, decaying with ``release`` seconds."""
        curve = np.zeros(n, dtype=np.float32)
        seg_len = int(release * 5 * self.sr)
        t = dsp.time_axis(seg_len, self.sr)
        shape = np.where(t < 0.004, 1.0, np.exp(-(t - 0.004) / release)).astype(np.float32)
        for kt in kick_times:
            s = int(round(kt * self.sr))
            if s >= n or s < 0:
                continue
            e = min(n, s + seg_len)
            np.maximum(curve[s:e], shape[: e - s], out=curve[s:e])
        return curve

    def audio_sidechain(self, kick: np.ndarray, n: int, *, gate: float = SIDECHAIN["gate"],
                        hold_ms: float = SIDECHAIN["hold_ms"]) -> np.ndarray:
        """0..1 ducking curve from the **rendered kick audio** (real, audio-level sidechain).

        ``kick`` is the kick track's buffer, either ``(n,)`` or ``(n, channels)``
        (a 2-D input is mono-ised). The rectified kick is peak-held over a short
        window (the centered filter also gives ~``hold_ms/2`` of lookahead, so the
        duck reaches full depth on the onset) and normalised to its own peak; the
        gate then maps the envelope onto ``[0, 1]``, so the duck recovers fully in
        the gaps between kicks and follows each kick's actual level. Silence
        yields an all-zero curve (no ducking).
        """
        x = np.abs(np.asarray(kick, dtype=np.float64))
        if x.ndim == 2:
            x = x.mean(axis=1)
        if x.size < n:
            x = np.pad(x, (0, n - x.size))
        else:
            x = x[:n]
        size = max(3, int(hold_ms * 0.001 * self.sr))
        env = ndimage.maximum_filter1d(x, size=size, mode="nearest")
        peak = float(env.max()) if env.size else 0.0
        if peak <= 0.0:
            return np.zeros(n, dtype=np.float32)
        env /= peak
        return np.clip((env - gate) / (1.0 - gate), 0.0, 1.0).astype(np.float32)

    def eq(self, x: np.ndarray, highpass: float = 0.0, lowpass: float = 0.0) -> np.ndarray:
        if highpass > 0:
            x = dsp.highpass(x, highpass, self.sr)
        if lowpass > 0:
            x = dsp.lowpass_sos(x, lowpass, self.sr)
        return x

    @staticmethod
    def pan(x: np.ndarray, pan: float) -> np.ndarray:
        """Balance control for a stereo buffer (-1 = left, +1 = right)."""
        pan = float(np.clip(pan, -1.0, 1.0))
        x[:, 0] *= min(1.0, 1.0 - pan)
        x[:, 1] *= min(1.0, 1.0 + pan)
        return x

    def compress(self, x: np.ndarray, amount: float, threshold_db: float = -18.0, block: int = 512) -> np.ndarray:
        """Simple feed-forward RMS compressor (block based, smoothed attack/release).

        Works in place on ``x`` and in chunks so that long tracks stay memory friendly.
        """
        if amount <= 0 or len(x) == 0:
            return x
        ratio = 1.0 + 5.0 * amount
        n = len(x)
        nb = int(np.ceil(n / block))
        ms = np.empty(nb, dtype=np.float64)
        for i in range(0, nb, 4096):
            seg = x[i * block: (i + 4096) * block]
            power = (seg.astype(np.float32) ** 2).mean(axis=1) if seg.ndim == 2 else seg.astype(np.float32) ** 2
            k = int(np.ceil(len(power) / block))
            pad = np.zeros(k * block, dtype=np.float32)
            pad[: len(power)] = power
            ms[i: i + k] = np.mean(pad.reshape(k, block), axis=1, dtype=np.float64)
        level_db = 10 * np.log10(ms + 1e-12)
        over = np.maximum(0.0, level_db - threshold_db)
        target = -over * (1.0 - 1.0 / ratio)
        # one-pole smoothing (fast attack, slower release)
        att = np.exp(-block / (0.005 * self.sr))
        rel = np.exp(-block / (0.12 * self.sr))
        gr = np.empty_like(target)
        g = 0.0
        for i, v in enumerate(target):
            coef = att if v < g else rel
            g = coef * g + (1 - coef) * v
            gr[i] = g
        makeup_db = -float(np.mean(gr)) * 0.5
        centers = np.arange(nb) * block + block / 2
        chunk = 1 << 20
        for s0 in range(0, n, chunk):
            idx = np.arange(s0, min(n, s0 + chunk))
            gains = (10 ** ((np.interp(idx, centers, gr) + makeup_db) / 20)).astype(x.dtype)
            if x.ndim == 2:
                x[s0: s0 + len(idx)] *= gains[:, None]
            else:
                x[s0: s0 + len(idx)] *= gains
        return x

    def delay(self, mono: np.ndarray, beats: float = 0.75) -> np.ndarray:
        """Tempo-synced (dotted 8th by default) ping-pong delay -> stereo."""
        n = len(mono)
        out = np.zeros((n, 2), dtype=np.float32)
        d = int(round(beats * 60.0 / self.bpm * self.sr))
        if d <= 0:
            return out
        src = dsp.lowpass_sos(mono, 5000, self.sr).astype(np.float32)
        gain, k = 1.0, 1
        while k * d < n:
            gain *= self.delay_feedback
            if gain < 0.02:
                break
            ch = (k - 1) % 2
            out[k * d:, ch] += src[: n - k * d] * gain
            k += 1
        return out

    def reverb(self, mono: np.ndarray, seed: int = 7) -> np.ndarray:
        """Convolution reverb with a synthetic, decorrelated stereo impulse response."""
        n_ir = int(self.reverb_size * self.sr)
        if n_ir < 2 or len(mono) == 0:
            return np.zeros((len(mono), 2), dtype=np.float32)
        rng = np.random.default_rng(seed)
        t = dsp.time_axis(n_ir, self.sr)
        decay = np.exp(-6.9 * t / self.reverb_size)
        pre = int(0.02 * self.sr)
        out = np.zeros((len(mono), 2), dtype=np.float32)
        for ch in range(2):
            ir = rng.standard_normal(n_ir) * decay
            ir = dsp.lowpass_sos(ir, 6000, self.sr)
            ir = np.concatenate([np.zeros(pre), ir])
            ir /= np.sqrt(np.sum(ir ** 2)) + 1e-12
            wet = signal.oaconvolve(mono.astype(np.float32), ir.astype(np.float32))[: len(mono)]
            out[:, ch] = wet.astype(np.float32)
        return out

    # ------------------------------------------------------------------ high level
    def process_track(self, name: str, stereo: np.ndarray, duck: Optional[np.ndarray]):
        """Apply EQ, compression, volume, pan and sidechain to one track.

        Returns ``(dry_stereo, reverb_send_mono, delay_send_mono)``.
        """
        mix = self.settings(name)
        x = self.eq(stereo, mix.highpass, mix.lowpass).astype(np.float32, copy=False)
        x = self.compress(x, mix.compress)
        x = self.pan(x, mix.pan)
        x *= np.float32(db_to_gain(mix.volume_db))
        if duck is not None and mix.sidechain > 0:
            depth = np.float32(mix.sidechain * (0.7 + 0.3 * self.intensity))
            for s0 in range(0, len(x), 1 << 20):
                x[s0: s0 + (1 << 20)] *= (1.0 - depth * duck[s0: s0 + (1 << 20)])[:, None]
        mono = x.mean(axis=1, dtype=np.float32)
        return x, mono * np.float32(mix.reverb_send), mono * np.float32(mix.delay_send)

    def master(self, stereo: np.ndarray, peak: float = 0.95) -> np.ndarray:
        """Low-cut, glue compression, soft limiting and peak normalisation."""
        x = dsp.highpass(stereo.astype(np.float32, copy=False), 25, self.sr)
        x = self.compress(x, 0.35 + 0.25 * self.intensity, threshold_db=-14.0)
        p = float(np.max(np.abs(x))) or 1.0
        x *= np.float32(1.3 / p)
        np.tanh(x, out=x)
        p = float(np.max(np.abs(x))) or 1.0
        x *= np.float32(peak / p)
        return x
