"""Built-in synthesizer voices: psy kick, drum kit, rolling bass, TB-303 acid,
supersaw lead, pluck arp, evolving pads, drone textures and FX.

Each voice renders one :class:`core.models.Note` into a mono ``float64`` buffer
whose peak is roughly 1.0 at full velocity (velocity is applied by the caller).
"""

from __future__ import annotations

import zlib
from typing import Callable, Dict

import numpy as np

from config.settings import GM, StylePreset
from core.models import Note
from synthesis import dsp

_GM_TO_DRUM = {v: k for k, v in GM.items()}


def _noise(name: str, n: int) -> np.ndarray:
    """Deterministic white noise (same seed for the same sound -> reproducible audio)."""
    return np.random.default_rng(zlib.crc32(name.encode())).uniform(-1.0, 1.0, n)


def _norm(x: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    return x / peak if peak > 1e-9 else x


# ---------------------------------------------------------------------------
# Drums
# ---------------------------------------------------------------------------

def kick(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    length = max(0.12, preset.kick_decay)
    n = int(length * sr)
    t = dsp.time_axis(n, sr)
    punch = preset.kick_punch
    f = 42.0 + (preset.kick_pitch - 42.0) * np.exp(-t / (0.018 + 0.02 * (1.0 - punch)))
    body = dsp.sine(dsp.phase_from_freq(f, n, sr))
    amp = np.exp(-t / (length * 0.45)) * np.clip((length - t) / 0.03, 0.0, 1.0)
    out = np.tanh(body * amp * (1.6 + 2.5 * punch))
    click = dsp.highpass(_noise("kick", n) * np.exp(-t / 0.0025), 1500, sr) * 0.35 * punch
    return _norm(out + click)


_TONED = {  # drum name -> (base Hz, decay s)
    "tom_low": (95, 0.22), "tom_mid_low": (115, 0.2), "tom_mid": (135, 0.18), "tom_high": (180, 0.16),
    "conga_low": (175, 0.18), "conga_open": (225, 0.16), "conga_mute": (270, 0.04),
    "bongo_low": (320, 0.1), "bongo_high": (430, 0.08),
}


def percussion(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    name = note.params.get("drum") or _GM_TO_DRUM.get(note.pitch, "hat_closed")

    def env_len(seconds):
        n = int(seconds * sr)
        return n, dsp.time_axis(n, sr)

    if name in ("hat_closed", "hat_pedal"):
        n, t = env_len(0.09)
        return _norm(dsp.highpass(_noise(name, n), 7500, sr) * np.exp(-t / 0.018))
    if name == "hat_open":
        n, t = env_len(0.3)
        return _norm(dsp.highpass(_noise(name, n), 6500, sr) * np.exp(-t / 0.075))
    if name in ("shaker", "tambourine"):
        n, t = env_len(0.1)
        env = (1 - np.exp(-t / 0.006)) * np.exp(-t / 0.035)
        x = dsp.bandpass(_noise(name, n), 4000, 11000, sr) * env
        if name == "tambourine":
            x *= 1.0 + 0.5 * dsp.sine(t * 90)
        return _norm(x)
    if name == "ride":
        n, t = env_len(0.6)
        metal = sum(dsp.square(dsp.phase_from_freq(f, n, sr), f, sr) for f in (342, 486, 593, 807, 921, 1053))
        x = dsp.highpass(metal * 0.15 + _noise(name, n), 5000, sr) * np.exp(-t / 0.22)
        return _norm(x)
    if name == "crash":
        n, t = env_len(2.2)
        return _norm(dsp.highpass(_noise(name, n), 3000, sr) * np.exp(-t / 0.7))
    if name == "clap":
        n, t = env_len(0.3)
        env = np.zeros(n)
        for k in range(3):
            tk = t - k * 0.009
            env += np.where(tk >= 0, np.exp(-np.clip(tk, 0, None) / 0.006), 0.0)
        tk = t - 0.027
        env += np.where(tk >= 0, 0.8 * np.exp(-np.clip(tk, 0, None) / 0.07), 0.0)
        return _norm(dsp.bandpass(_noise(name, n), 900, 6000, sr) * env)
    if name in ("snare", "snare2"):
        n, t = env_len(0.25)
        tone = dsp.sine(dsp.phase_from_freq(190 * (1 + 0.5 * np.exp(-t / 0.01)), n, sr)) * np.exp(-t / 0.045)
        crisp = dsp.bandpass(_noise(name, n), 1500, 9000, sr) * np.exp(-t / 0.08)
        return _norm(0.6 * tone + crisp)
    if name in ("rim", "claves", "cowbell"):
        n, t = env_len(0.12)
        freqs = {"rim": (1700, 460), "claves": (2500, 2500), "cowbell": (540, 800)}[name]
        x = sum(dsp.square(dsp.phase_from_freq(f, n, sr), f, sr) for f in freqs)
        x = dsp.bandpass(x, 400, 6000, sr) * np.exp(-t / (0.06 if name == "cowbell" else 0.015))
        return _norm(x)
    base, decay = _TONED.get(name, (200, 0.12))
    n, t = env_len(decay * 3)
    f = base * (1 + 0.45 * np.exp(-t / 0.015))
    body = dsp.sine(dsp.phase_from_freq(f, n, sr)) * np.exp(-t / decay)
    slap = dsp.bandpass(_noise(name, n), 1000, 5000, sr) * np.exp(-t / 0.006) * 0.4
    return _norm(body + slap)


# ---------------------------------------------------------------------------
# Melodic voices
# ---------------------------------------------------------------------------

def _osc(wave: str, phase: np.ndarray, f, sr: int) -> np.ndarray:
    return dsp.square(phase, f, sr) if wave == "square" else dsp.saw(phase, f, sr)


def bass(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    p = note.params
    f0 = dsp.midi_to_hz(note.pitch)
    n_gate = max(1, int(dur * sr))
    n = n_gate + int(0.012 * sr)
    t = dsp.time_axis(n, sr)
    det = p.get("detune", 0.006)
    wave = p.get("wave", "saw")
    osc = 0.5 * (_osc(wave, dsp.phase_from_freq(f0 * (1 + det), n, sr), f0 * (1 + det), sr)
                 + _osc(wave, dsp.phase_from_freq(f0 * (1 - det), n, sr, 0.37), f0 * (1 - det), sr))
    sub = dsp.sine(dsp.phase_from_freq(f0, n, sr))
    fc = p.get("cutoff", 900.0) * (1.0 + p.get("env", 2.0) * np.exp(-t / 0.045))
    x = dsp.lowpass_sweep(0.75 * osc + 0.8 * sub, fc, sr, q=1.0)
    return _norm(x * dsp.adsr(n, n_gate, sr, 0.002, 0.07, 0.75, 0.012))


def acid(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    p = note.params
    f_to = dsp.midi_to_hz(note.pitch)
    n_gate = max(1, int(dur * sr))
    n = n_gate + int(0.01 * sr)
    t = dsp.time_axis(n, sr)
    slide_from = p.get("slide_from")
    if slide_from is not None:
        f_from = dsp.midi_to_hz(slide_from)
        f = f_from * (f_to / f_from) ** np.clip(t / 0.06, 0.0, 1.0)
    else:
        f = np.full(n, f_to)
    osc = _osc(p.get("wave", "saw"), dsp.phase_from_freq(f, n, sr), f, sr)
    accent = bool(p.get("accent"))
    env_amt = p.get("env", 2.0) * (1.7 if accent else 1.0)
    fc = p.get("cutoff", 500.0) * (1.0 + env_amt * np.exp(-t / (0.08 if accent else 0.16)))
    y = dsp.lowpass_sweep(osc, fc, sr, q=float(p.get("resonance", 6.0)))
    y = np.tanh(_norm(y) * (2.5 if accent else 1.6))
    attack = 0.0005 if slide_from is not None else 0.003
    amp = dsp.adsr(n, n_gate, sr, attack, 0.2, 0.85, 0.008) * (1.0 if accent else 0.8)
    return y * amp


def lead(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    """Soft, singing goa lead.

    Genre-mixing research (myloops psytrance lead guide, iZotope harshness
    notes): leads get fatiguing when a wide supersaw + hard gate + full
    resonance all hit the 2-4 kHz presence band at once. The recipe here:
    few detuned voices, a rounded-off top end, velocity-driven gentle
    brightness, and a slower filter release so notes breathe.
    """
    p = note.params
    f0 = dsp.midi_to_hz(note.pitch)
    n_gate = max(1, int(dur * sr))
    n = n_gate + int(0.18 * sr)
    t = dsp.time_axis(n, sr)
    vib = 1.0 + 0.004 * np.sin(dsp.TWO_PI * 5.0 * t) * np.clip((t - 0.14) / 0.3, 0.0, 1.0)
    rng = np.random.default_rng(note.pitch)
    x = np.zeros(n)
    # Narrow stack (was +-1.1% spread): fewer voices, small detune -> warm
    # chorus instead of a fizzy wall of sawtooth.
    detunes = (-0.006, -0.002, 0.0, 0.002, 0.006)
    for d in detunes:
        f = f0 * (1 + d) * vib
        x += dsp.saw(dsp.phase_from_freq(f, n, sr, rng.random()), f, sr)
    x *= 0.2  # stack gain; _norm restores peak later, this keeps tanh sane
    # Softening filter: default cutoff down from 5 kHz to 2.6 kHz, and the
    # whole result is wrapped in a mild tanh so the top rounds off like an
    # analog saw played at moderate level.
    cutoff = p.get("cutoff", 2600.0)
    x = dsp.lowpass(x, cutoff, sr, q=0.7)
    x = np.tanh(x * 1.2)
    # Tame the ear band: a gentle dip around 3.2 kHz instead of a broad notch
    # (iZotope: 1-3 dB dynamic-ish cut, not a permanent dull of the whole lead).
    x = dsp.peaking(x, 3200.0, -2.0, sr, q=1.4)
    gate = dsp.adsr(n, n_gate, sr, 0.02, 0.35, 0.6, 0.2)  # slower softer gate
    return (x / (np.max(np.abs(x)) + 1e-9)) * gate * (0.75 + 0.25 * p.get("vel", 1.0))


def arp(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    p = note.params
    f0 = dsp.midi_to_hz(note.pitch)
    n_gate = max(1, int(dur * sr))
    n = n_gate + int(0.06 * sr)
    t = dsp.time_axis(n, sr)
    ph = dsp.phase_from_freq(f0, n, sr)
    x = 0.6 * dsp.saw(ph, f0, sr) + 0.5 * dsp.square(ph * 1.002, f0 * 1.002, sr)
    fc = p.get("cutoff", 2500.0) * (1.0 + 3.0 * np.exp(-t / 0.04))
    x = dsp.lowpass_sweep(x, fc, sr, q=2.0)
    return _norm(x) * dsp.adsr(n, n_gate, sr, 0.002, 0.12, 0.3, 0.05)


def pad(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    p = note.params
    f0 = dsp.midi_to_hz(note.pitch)
    n_gate = max(1, int(dur * sr))
    n = n_gate + int(1.5 * sr)
    t = dsp.time_axis(n, sr)
    rng = np.random.default_rng(note.pitch + 1000)
    x = np.zeros(n)
    for d in np.linspace(-0.014, 0.014, 7):
        f = f0 * (1 + d)
        x += dsp.saw(dsp.phase_from_freq(f, n, sr, rng.random()), f, sr)
    lfo = 0.5 + 0.5 * np.sin(dsp.TWO_PI * 0.13 * t + rng.random() * 6.28)
    fc = p.get("cutoff", 2000.0) * (0.6 + 0.8 * lfo)
    x = dsp.lowpass_sweep(x, fc, sr, q=0.8, block=512)
    return _norm(x) * dsp.adsr(n, n_gate, sr, p.get("attack", 1.0), 1.0, 0.85, 1.5)


def texture(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    p = note.params
    f0 = dsp.midi_to_hz(note.pitch)
    n_gate = max(1, int(dur * sr))
    n = n_gate + int(2.0 * sr)
    t = dsp.time_axis(n, sr)
    lfo = 0.5 + 0.5 * np.sin(dsp.TWO_PI * p.get("lfo", 0.1) * t)
    fc = p.get("cutoff", 800.0) * (0.5 + 1.5 * lfo)
    if p.get("kind") == "wind":
        x = dsp.lowpass_sweep(_noise(f"wind{note.pitch}", n), fc * 3, sr, q=4.0, block=512)
        x = dsp.highpass(x, 200, sr)
    else:
        ph = dsp.phase_from_freq(f0, n, sr)
        x = dsp.saw(ph, f0, sr) + dsp.saw(ph * 1.003 + 0.3, f0 * 1.003, sr) + dsp.sine(ph)
        x = dsp.lowpass_sweep(x, fc, sr, q=2.5, block=512)
    return _norm(x) * dsp.adsr(n, n_gate, sr, min(3.0, dur / 3 + 0.01), 1.0, 1.0, 2.0)


def fx(note: Note, dur: float, sr: int, preset: StylePreset) -> np.ndarray:
    p = note.params
    kind = p.get("fx", "sweep")
    if kind == "impact":
        n = int(2.5 * sr)
        t = dsp.time_axis(n, sr)
        boom = dsp.sine(dsp.phase_from_freq(45 + 90 * np.exp(-t / 0.05), n, sr)) * np.exp(-t / 0.6)
        crash = dsp.lowpass(_noise("impact", n), 3000, sr) * np.exp(-t / 0.25)
        return _norm(boom + 0.5 * crash)
    if kind in ("zap", "laser"):
        n = int(max(0.08, min(dur, 0.4)) * sr)
        t = dsp.time_axis(n, sr)
        sweep = float(p.get("sweep", 1.0))
        f = 80 + 4500 * np.exp(-t / (0.02 * sweep))
        ph = dsp.phase_from_freq(f, n, sr)
        x = dsp.square(ph, f, sr) if kind == "laser" else dsp.sine(ph)
        return _norm(x * np.exp(-t / 0.08))
    if kind == "bubble":
        n = int(max(0.1, dur) * sr)
        t = dsp.time_axis(n, sr)
        rate = float(p.get("rate", 12.0))
        f = 300 + 900 * np.mod(t * rate, 1.0)
        x = dsp.sine(dsp.phase_from_freq(f, n, sr)) * (0.5 + 0.5 * dsp.square(t * rate * 0.5, rate * 0.5, sr))
        return _norm(dsp.lowpass(x, 2500, sr, q=4.0)) * np.sin(np.pi * t / t[-1])
    n = max(2, int(dur * sr))
    t = dsp.time_axis(n, sr)
    pos = t / t[-1]
    noise = _noise(kind, n)
    if kind == "riser":
        fc = 200 * (9000 / 200) ** pos
        f = 110 * 2 ** (2 * pos)
        tone = dsp.saw(dsp.phase_from_freq(f, n, sr), f, sr) * 0.3
        x = dsp.lowpass_sweep(noise + tone, fc, sr, q=3.0, block=256)
        return _norm(x) * pos ** 2
    if kind == "downlifter":
        fc = 8000 * (200 / 8000) ** pos
        x = dsp.lowpass_sweep(noise, fc, sr, q=2.0, block=256)
        return _norm(x) * (1 - pos) ** 2
    # sweep / whoosh
    fc = 300 + 7000 * np.sin(np.pi * pos)
    x = dsp.lowpass_sweep(noise, fc, sr, q=3.0, block=256)
    return _norm(x) * np.sin(np.pi * pos)


VOICES: Dict[str, Callable[[Note, float, int, StylePreset], np.ndarray]] = {
    "kick": kick, "percussion": percussion, "bass": bass, "acid": acid, "lead": lead,
    "arp": arp, "pad": pad, "texture": texture, "fx": fx,
}
