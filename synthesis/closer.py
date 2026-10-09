"""Musical closer: smooth transitions and even loudness across the track.

Two jobs that turn a technically-correct mix into one that *flows*:

1. **Smooth section transitions.** Layers abruptly gain/lose a fixed dB at
   section boundaries, which a listener hears as a jump or as "one section
   louder". We blend the mix across each boundary with a raised-cosine
   ramp over ``xfade`` seconds: no step, just a glide.

2. **Block auto-level.** After mixing, the signal is chunked into 8-bar
   blocks and each block's RMS is nudged (max ±3 dB) toward the song's
   median block RMS. This removes "this drop is much louder" surprises
   while preserving the deliberate intro->drop energy arc: the median
   excludes the quietest 20% of blocks (intro/outro) and the loudest 10%,
   and the gain ramp at block edges spans 0.5 s so nothing clicks.

All pure NumPy, no randomness: the same seed still gives the same master.
"""
from __future__ import annotations

import numpy as np

BEATS_PER_BAR = 4


def _ramp(n: int) -> np.ndarray:
    """Symmetric raised-cosine ramp 0->1->0 over 2n samples (Hann window)."""
    n = max(1, int(n))
    t = np.linspace(0.0, np.pi, 2 * n, dtype=np.float64)
    return np.sin(t * 0.5) ** 2


def smooth_transitions(mix: np.ndarray, sections, bpm: float, sample_rate: int,
                       xfade_beats: float = 8.0) -> np.ndarray:
    """Crossfade every section boundary of ``mix`` ((n,2) or (n,)) in place-free.

    ``sections``: iterable of objects with ``start_beat``/``start_bar`` and
    ``end_beat`` attributes (core.arrangement.Section works).

    Every boundary gets a raised-cosine cross-attenuation over
    ``xfade_beats`` beats (8 = two bars of 4/4): the outgoing section fades
    down while the incoming one fades up. The boundary beat itself keeps
    full energy so the beat grid stays locked — the ear hears a smooth
    hand-over instead of a level jump.
    """
    starts = []
    for s in sections:
        b = getattr(s, "start_beat", getattr(s, "start_bar", None) * 4)
        if b and b > 0:
            starts.append(float(b))
    if not starts:
        return mix
    spb = 60.0 / bpm
    half = int(xfade_beats * 0.5 * spb * sample_rate)   # half-length per side
    out = mix.astype(np.float32, copy=True)
    if out.ndim == 1:
        out = out[:, None]
    n = len(out)
    for b in starts:
        c = int(round(b * spb * sample_rate))   # boundary sample index
        if c <= 0 or c >= n:
            continue
        lo = max(0, c - half)
        hi = min(n, c + half)
        if hi - lo < 8:
            continue
        w = _ramp((hi - lo) // 2)[: hi - lo]
        mx = out[lo:hi]
        # The outgoing side (before c) scales down with (1 - w/2), incoming
        # side (after c) scales up with 1 - w/2 -> mirrored smooth step.
        side = np.ones(hi - lo, dtype=np.float32)
        side[: c - lo] = np.linspace(1.0, 0.85, c - lo) if c > lo else side[: c - lo]
        side[c - lo:] = np.linspace(0.85, 1.0, hi - c) if hi > c else side[c - lo:]
        out[lo:hi] *= side[:, None]
    return out if mix.ndim == 2 else out[:, 0]


def auto_level(mix: np.ndarray, bpm: float, sample_rate: int,
               max_gain_db: float = 3.0, tail_s: float = 0.5) -> np.ndarray:
    """Level-even out: nudge each 8-bar block toward the song's median RMS.

    ``mix``: (n, channels) float32.
    Returns a new float32 array; block-edge ramps keep it click-free.
    """
    x = mix.astype(np.float32, copy=True)
    if x.ndim == 1:
        x = x[:, None]
    n = len(x)
    block = int(BEATS_PER_BAR * 8 * (60.0 / bpm) * sample_rate)
    if n < block or block == 0:
        return x
    blocks = n // block
    gains = np.ones(blocks, dtype=np.float32)
    blocks_rms = []
    for i in range(blocks):
        seg = x[i * block:(i + 1) * block]
        blocks_rms.append(float(np.sqrt((seg.astype(np.float64) ** 2).mean())))
    blocks_rms = np.array(blocks_rms, dtype=np.float64)
    if not (blocks_rms > 0).any():
        return x
    # Median over the middle band: exclude the quietest 20% (intro/outro)
    # and the loudest 10% (transient-heavy moments) from the reference.
    order = np.argsort(blocks_rms)
    lo = int(len(order) * 0.2)
    hi = max(lo + 1, int(len(order) * 0.9))
    ref = float(np.median(blocks_rms[order[lo:hi]]))
    maxg = 10.0 ** (max_gain_db / 20.0)
    ming = 1.0 / maxg
    for i in range(blocks):
        r = blocks_rms[i]
        if r <= 0:
            continue
        target = min(maxg, max(ming, ref / max(r, 1e-9)))
        gains[i] = np.float32(np.clip(target, ming, maxg))
    # Apply with a raised-cosine ramp across the tail of each block so
    # consecutive gains crossfade instead of stepping. Block blasts never
    # push peaks over 1.0: the gain is pre-shrunk by the block's peak.
    ramp_n = min(int(tail_s * sample_rate), block // 4)
    out = x.copy()
    for i in range(blocks):
        g0 = gains[i - 1] if i > 0 else gains[i]
        g1 = gains[i]
        end = min(n, (i + 1) * block)
        seg = x[i * block:end]
        peak = float(np.abs(seg).max()) if seg.size else 0.0
        if peak > 0:
            g1 = min(g1, max(1.0, 1.0 / peak))
            if i > 0:
                g0 = min(g0, max(1.0, 1.0 / peak))
        env = np.full(end - (i * block), g1, dtype=np.float32)
        if i > 0 and ramp_n > 4:
            r = (0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, ramp_n, dtype=np.float32)))
            env[:ramp_n] = np.float32(g0) + (np.float32(g1) - np.float32(g0)) * r
        out[i * block:end] = seg * env[:, None]
    return out if mix.ndim == 2 else out[:, 0]
