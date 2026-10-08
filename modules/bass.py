"""Rolling psytrance basslines.

The bass plays the three 16th notes *between* the kicks of every beat
(``K-B-B-B``) – the hypnotic "rolling" bass of Goa / psytrance.  Goa
favours octave jumps and modal movement (b2, 5th); High-Tech plays tighter,
shorter notes with more movement and 32nd-note "gallops".
"""

from __future__ import annotations

import math
import random
from typing import List, Optional

from core.models import GenerationContext, Track
from modules.common import STEP, STEPS_PER_BAR, bar_start, energy, is_phrase_end, is_pre_drop, make_track


def cutoff_to_cc(hz: float) -> int:
    """Map 40 Hz .. 12 kHz logarithmically onto MIDI CC 0..127 (CC74 = brightness)."""
    hz = min(12000.0, max(40.0, hz))
    return int(round(127 * math.log(hz / 40.0) / math.log(12000.0 / 40.0)))


def _riff(ctx: GenerationContext, rng: random.Random) -> List[Optional[int]]:
    p = ctx.preset
    moves = [1, -1, 4, 2, -2] if p.bass_pattern == "16th_rolling" else [1, -1, 1, 3, -3, 6]
    riff: List[Optional[int]] = []
    for s in range(STEPS_PER_BAR):
        if s % 4 == 0:
            riff.append(None)       # the kick owns the downbeat
            continue
        off = 0
        if rng.random() < p.bass_octave_prob:
            off = 7
        elif s >= 8 and rng.random() < p.bass_movement_prob:
            off = rng.choice(moves)
        riff.append(off)
    return riff


def generate(ctx: GenerationContext, rng: random.Random) -> List[Track]:
    p = ctx.preset
    track = make_track("bass")
    scale = ctx.scale
    octave = 1 if scale.pitch(0, 1) >= 33 else 2
    tech = p.bass_pattern != "16th_rolling"

    for section in ctx.arrangement.sections:
        if not section.has("bass"):
            continue
        main_riff = _riff(ctx, rng)
        fill_riff = _riff(ctx, rng)
        for bar in range(section.start_bar, section.end_bar):
            progress = section.progress(bar)
            if section.kind == "intro" and section.bars >= 8 and progress < 0.5:
                continue
            if section.kind == "outro" and progress >= 0.6:
                continue
            e = energy(ctx, section, bar)
            t0 = bar_start(bar)
            riff = fill_riff if is_phrase_end(section, bar) else main_riff
            root = ctx.harmony.root(bar)
            cutoff = p.bass_cutoff * (0.45 + 0.75 * e)
            track.cc(t0, 74, cutoff_to_cc(cutoff))
            last_step = 8 if is_pre_drop(section, bar) else STEPS_PER_BAR
            for s in range(last_step):
                off = riff[s]
                if off is None:
                    continue
                pitch = scale.pitch(root + off, octave)
                vel = 104 if s % 4 == 2 else 96
                gate = p.bass_gate * STEP
                params = dict(cutoff=cutoff, wave=p.bass_wave, detune=p.bass_detune,
                              env=2.2 if p.bass_filter_mod else 0.0)
                # High-tech gallop: split the last 16th of a beat into two 32nds
                if tech and s % 4 == 3 and e > 0.75 and rng.random() < 0.18:
                    track.add(t0 + s * STEP, gate / 2, pitch, vel, **params)
                    track.add(t0 + s * STEP + STEP / 2, gate / 2, pitch, vel - 6, **params)
                    continue
                track.add(t0 + s * STEP, gate, pitch, vel, **params)
    return [track.sort()]
