"""Low-level DSP building blocks (NumPy / SciPy): band-limited oscillators,
envelopes and (time-varying) filters."""

from __future__ import annotations

import numpy as np
from scipy import signal

TWO_PI = 2.0 * np.pi


def midi_to_hz(pitch: float) -> float:
    return 440.0 * 2.0 ** ((pitch - 69) / 12.0)


def time_axis(n: int, sr: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / sr


def phase_from_freq(freq, n: int, sr: int, phase0: float = 0.0) -> np.ndarray:
    """Running phase in *cycles* for a constant or per-sample frequency."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    return phase0 + np.concatenate(([0.0], np.cumsum(f[:-1]))) / sr


def _polyblep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt[m]
    out[m] = x * x + x + x + 1.0
    return out


def saw(phase: np.ndarray, freq, sr: int) -> np.ndarray:
    """Band-limited (PolyBLEP) sawtooth."""
    dt = np.clip(np.broadcast_to(np.asarray(freq, dtype=np.float64), phase.shape) / sr, 1e-9, 0.5)
    t = np.mod(phase, 1.0)
    return 2.0 * t - 1.0 - _polyblep(t, dt)


def square(phase: np.ndarray, freq, sr: int, pw: float = 0.5) -> np.ndarray:
    """Band-limited (PolyBLEP) pulse wave."""
    dt = np.clip(np.broadcast_to(np.asarray(freq, dtype=np.float64), phase.shape) / sr, 1e-9, 0.5)
    t = np.mod(phase, 1.0)
    out = np.where(t < pw, 1.0, -1.0)
    return out + _polyblep(t, dt) - _polyblep(np.mod(t + 1.0 - pw, 1.0), dt)


def sine(phase: np.ndarray) -> np.ndarray:
    return np.sin(TWO_PI * phase)


def adsr(n_total: int, n_gate: int, sr: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """ADSR envelope; ``n_gate`` samples of key-down, then release over ``r`` seconds."""
    t = time_axis(n_total, sr)
    a = max(a, 1e-4)
    d = max(d, 1e-4)
    r = max(r, 1e-4)

    def level(x):
        return np.where(x < a, x / a, s + (1.0 - s) * np.exp(-(x - a) / d))

    env = level(t)
    gate_t = n_gate / sr
    at_gate = float(level(np.array([gate_t]))[0])
    rel = at_gate * np.clip(1.0 - (t - gate_t) / r, 0.0, 1.0)
    return np.where(t < gate_t, env, rel)


def fade_edges(x: np.ndarray, sr: int, fade: float = 0.002) -> np.ndarray:
    n = min(len(x) // 2, max(1, int(fade * sr)))
    ramp = np.linspace(0.0, 1.0, n)
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _lp_coeffs(fc: np.ndarray, q: float, sr: int):
    """RBJ biquad low-pass coefficients, vectorised over ``fc``."""
    fc = np.clip(fc, 20.0, 0.45 * sr)
    w0 = TWO_PI * fc / sr
    alpha = np.sin(w0) / (2.0 * max(q, 0.1))
    cosw = np.cos(w0)
    a0 = 1.0 + alpha
    b0 = (1.0 - cosw) / 2.0 / a0
    b1 = (1.0 - cosw) / a0
    a1 = -2.0 * cosw / a0
    a2 = (1.0 - alpha) / a0
    return b0, b1, b0, a1, a2


def lowpass(x: np.ndarray, fc: float, sr: int, q: float = 0.707) -> np.ndarray:
    b0, b1, b2, a1, a2 = (float(c[0]) for c in _lp_coeffs(np.array([float(fc)]), q, sr))
    return signal.lfilter([b0, b1, b2], [1.0, a1, a2], x)


def lowpass_sweep(x: np.ndarray, fc_curve: np.ndarray, sr: int, q: float = 0.707, block: int = 64) -> np.ndarray:
    """Resonant low-pass whose cutoff follows ``fc_curve`` (updated every ``block`` samples)."""
    n = len(x)
    if n == 0:
        return x
    starts = np.arange(0, n, block)
    b0, b1, b2, a1, a2 = _lp_coeffs(np.asarray(fc_curve, dtype=np.float64)[starts], q, sr)
    y = np.empty(n, dtype=np.float64)
    zi = np.zeros(2)
    for i, s in enumerate(starts):
        e = min(n, s + block)
        y[s:e], zi = signal.lfilter([b0[i], b1[i], b2[i]], [1.0, a1[i], a2[i]], x[s:e], zi=zi)
    return y


def _dtype(x: np.ndarray):
    """Keep float32 buffers in float32 (halves memory for long tracks)."""
    return np.float32 if np.asarray(x).dtype == np.float32 else np.float64


def highpass(x: np.ndarray, fc: float, sr: int, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, min(fc, 0.45 * sr), btype="highpass", fs=sr, output="sos")
    return signal.sosfilt(sos.astype(_dtype(x)), x, axis=0)


def lowpass_sos(x: np.ndarray, fc: float, sr: int, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, min(fc, 0.45 * sr), btype="lowpass", fs=sr, output="sos")
    return signal.sosfilt(sos.astype(_dtype(x)), x, axis=0)


def bandpass(x: np.ndarray, lo: float, hi: float, sr: int, order: int = 2) -> np.ndarray:
    hi = min(hi, 0.45 * sr)
    lo = min(lo, hi * 0.9)
    sos = signal.butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return signal.sosfilt(sos, x, axis=0)


def soft_clip(x: np.ndarray, drive: float = 1.0) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)
