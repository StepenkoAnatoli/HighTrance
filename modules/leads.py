"""Psychedelic leads, hypnotic arpeggios and TB-303 style acid lines."""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

from core.models import GenerationContext, Track
from modules.bass import cutoff_to_cc
from modules.common import (STEP, STEPS_PER_BAR, bar_start, clamp, energy, is_pre_drop, make_track,
                            velocity)

MotifNote = Tuple[int, int, int, bool]   # (step, length in steps, degree, ornament)


# ---------------------------------------------------------------------------
# Lead melody
# ---------------------------------------------------------------------------

def _motif(ctx: GenerationContext, rng: random.Random, bars: int = 2) -> List[MotifNote]:
    p = ctx.preset
    eastern = "eastern" in p.lead_style
    lengths = [2, 2, 3, 4, 4, 6, 8] if eastern else [1, 1, 2, 2, 3, 4]
    moves = [-2, -1, -1, 1, 1, 2, 3, -3] if eastern else [-4, -2, -1, 1, 2, 4, 7, -7]
    notes: List[MotifNote] = []
    deg = rng.choice([0, 2, 4, 7])
    s = 0
    total = bars * STEPS_PER_BAR
    while s < total:
        if rng.random() < p.lead_density + 0.2:
            length = min(rng.choice(lengths), total - s)
            deg = int(clamp(deg + rng.choice(moves), -3, 11))
            notes.append((s, length, deg, length >= 2 and rng.random() < p.ornament_prob))
            s += length
        else:
            s += rng.choice([1, 2])
    if not notes:
        notes.append((0, 4, 0, False))
    return notes


def _vary(motif: List[MotifNote], rng: random.Random) -> List[MotifNote]:
    """Answer phrase: keep the first half, re-pitch the second half."""
    half = max(n[0] for n in motif) // 2
    return [(s, l, d if s < half else int(clamp(d + rng.choice([-2, -1, 1, 2, 3]), -3, 11)), o)
            for s, l, d, o in motif]


def _play_motif(track: Track, ctx: GenerationContext, motif: List[MotifNote], start_bar: int,
                stretch: int, vel: float, cutoff: float, octave: int, double: bool, rng: random.Random,
                end_beat: float) -> None:
    p = ctx.preset
    for s, length, deg, ornament in motif:
        start = bar_start(start_bar) + s * STEP * stretch
        if start >= end_beat:
            break
        dur = min(length * STEP * stretch * 0.92, end_beat - start)
        bar = int(start // 4)
        d = deg + ctx.harmony.root(bar)
        pitch = ctx.scale.pitch(d, octave)
        params = dict(cutoff=cutoff, wave=p.lead_wave)
        if ornament and dur > 0.3:
            # eastern grace note / mordent: quick neighbour before the main note
            track.add(start, 0.125, ctx.scale.pitch(d + 1, octave), velocity(vel - 15, rng), **params)
            start += 0.125
            dur -= 0.125
        track.add(start, dur, pitch, velocity(vel, rng), **params)
        if double:
            track.add(start, dur, pitch + 12, velocity(vel - 25, rng), **params)


def _lead(ctx: GenerationContext, rng: random.Random) -> Track:
    track = make_track("lead")
    theme = _motif(ctx, rng)
    answer = _vary(theme, rng)
    octave = 4 if ctx.scale.pitch(0, 4) >= 62 else 5
    for section in ctx.arrangement.sections:
        if not section.has("lead"):
            continue
        end = section.end_beat
        for bar in range(section.start_bar, section.end_bar, 2):
            rel = bar - section.start_bar
            e = energy(ctx, section, bar)
            cutoff = 1500 + 6500 * e
            if section.kind == "drop":
                if section.bars > 8 and rel < 8:
                    continue                                   # let the groove breathe first
                motif = answer if (rel // 2) % 4 == 3 else theme
                double = section.name == "drop2" and ctx.intensity > 0.6
                _play_motif(track, ctx, motif, bar, 1, 92 + 20 * e, cutoff, octave, double, rng, end)
            elif section.kind == "breakdown":
                if rel % 4 or section.progress(bar) < 0.25:
                    continue
                # theme in half time with long notes – the emotional moment
                _play_motif(track, ctx, theme if (rel // 4) % 2 == 0 else answer, bar, 2,
                            80 + 20 * e, 900 + 3000 * section.progress(bar), octave, False, rng, end)
            elif section.kind == "build" and section.progress(bar) >= 0.5 and not is_pre_drop(section, bar):
                _play_motif(track, ctx, theme, bar, 1, 70, 500 + 3000 * section.progress(bar), octave,
                            False, rng, min(end - 4, end))
    return track.sort()


# ---------------------------------------------------------------------------
# Arpeggios
# ---------------------------------------------------------------------------

def _arp(ctx: GenerationContext, rng: random.Random) -> Track:
    p = ctx.preset
    track = make_track("arp")
    octave = 4 if ctx.scale.pitch(0, 4) >= 62 else 5
    for section in ctx.arrangement.sections:
        if not section.has("arp"):
            continue
        group = p.arp_grouping
        shape = rng.choice(["up", "down", "updown", "spread"])
        offsets = {"up": [0, 2, 4, 7], "down": [7, 4, 2, 0], "updown": [0, 4, 7, 4],
                   "spread": [0, 7, 2, 9]}[shape][:group]
        for bar in range(section.start_bar, section.end_bar):
            rel = bar - section.start_bar
            e = energy(ctx, section, bar)
            if section.kind == "build" and section.progress(bar) < 0.25:
                continue
            if section.kind == "drop" and (rel // 8) % 2 == 1 and section.bars > 8:
                continue                                       # call & response with the lead
            if section.kind == "breakdown" and section.progress(bar) > 0.85:
                continue
            gate = 0.9 if section.kind == "breakdown" else (0.45 if p.arp_grouping == 4 else 0.6)
            last = 8 if is_pre_drop(section, bar) else STEPS_PER_BAR
            root = ctx.harmony.root(bar)
            cutoff = 800 + 4200 * e
            for s in range(last):
                step_index = bar * STEPS_PER_BAR + s       # continuous -> 3-over-4 drifts across bars
                deg = root + offsets[step_index % len(offsets)]
                vel = 78 + (18 if step_index % len(offsets) == 0 else 0) + 10 * e
                pan = 0.35 if step_index % 2 else -0.35
                track.add(bar_start(bar) + s * STEP, STEP * gate, ctx.scale.pitch(deg, octave),
                          velocity(vel, rng, 4), cutoff=cutoff, pan=pan)
    return track.sort()


# ---------------------------------------------------------------------------
# Acid (TB-303 style)
# ---------------------------------------------------------------------------

def _acid_pattern(ctx: GenerationContext, rng: random.Random) -> List[Optional[Dict]]:
    p = ctx.preset
    degrees = [0, 0, 0, 7, 1, 3, 4, -1, 0, 6]
    pattern: List[Optional[Dict]] = []
    for s in range(STEPS_PER_BAR):
        if rng.random() < p.acid_density or s == 0:
            pattern.append(dict(deg=rng.choice(degrees), accent=rng.random() < p.acid_accent_prob,
                                slide=rng.random() < p.acid_slide_prob, up=rng.random() < 0.15))
        else:
            pattern.append(None)
    return pattern


def _acid(ctx: GenerationContext, rng: random.Random) -> Track:
    p = ctx.preset
    track = make_track("acid")
    octave = 2 if ctx.scale.pitch(0, 2) >= 45 else 3
    track.cc(0, 71, int(clamp(p.acid_resonance / 12) * 127))
    for section in ctx.arrangement.sections:
        if not section.has("acid"):
            continue
        pattern = _acid_pattern(ctx, rng)
        for bar in range(section.start_bar, section.end_bar):
            prog = section.progress(bar)
            if section.kind == "build" and prog < 0.3:
                continue
            if section.kind == "outro" and prog >= 0.5:
                continue
            rel = bar - section.start_bar
            if rel and rel % 4 == 0:                    # slowly evolving line
                i = rng.randrange(STEPS_PER_BAR)
                pattern[i] = None if pattern[i] and i else _acid_pattern(ctx, rng)[i] or pattern[i]
            e = energy(ctx, section, bar)
            if section.kind == "build":
                cutoff = p.acid_cutoff * (0.35 + 1.6 * prog)
            else:   # the classic hand-tweaked filter sweep (LFO over 8 bars)
                cutoff = p.acid_cutoff * (0.7 + 0.9 * e * (0.5 + 0.5 * math.sin(2 * math.pi * rel / 8)))
            track.cc(bar_start(bar), 74, cutoff_to_cc(cutoff))
            last = 8 if is_pre_drop(section, bar) else STEPS_PER_BAR
            root = ctx.harmony.root(bar)
            prev_pitch = None
            for s in range(last):
                step = pattern[s]
                if step is None:
                    prev_pitch = None
                    continue
                pitch = ctx.scale.pitch(root + step["deg"], octave) + (12 if step["up"] else 0)
                nxt = pattern[s + 1] if s + 1 < last else None
                slide_out = step["slide"] and nxt is not None
                dur = STEP * 1.02 if slide_out else STEP * 0.55
                params = dict(cutoff=cutoff, resonance=p.acid_resonance, accent=step["accent"],
                              wave=p.acid_wave, env=1.0 + 2.0 * e)
                if prev_pitch is not None:
                    params["slide_from"] = prev_pitch
                track.add(bar_start(bar) + s * STEP, dur, pitch, 120 if step["accent"] else 88, **params)
                prev_pitch = pitch if slide_out else None
    return track.sort()


def generate(ctx: GenerationContext, rng: random.Random) -> List[Track]:
    # Separate sub-streams keep lead / arp / acid independent of each other.
    lead_rng = random.Random(rng.getrandbits(64))
    arp_rng = random.Random(rng.getrandbits(64))
    acid_rng = random.Random(rng.getrandbits(64))
    return [_acid(ctx, acid_rng), _lead(ctx, lead_rng), _arp(ctx, arp_rng)]
