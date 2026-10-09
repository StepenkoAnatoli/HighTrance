"""FX: risers, downlifters, impacts, zaps, sweeps and psychedelic bubbles."""

from __future__ import annotations

import random
from typing import List

from config.settings import FX_PITCHES
from core.models import GenerationContext, Track
from modules.common import STEP, STEPS_PER_BAR, bar_start, energy, is_phrase_end, make_track


def _fx(track: Track, start: float, duration: float, kind: str, vel: int, **params) -> None:
    track.add(start, duration, FX_PITCHES[kind], vel, fx=kind, **params)


def generate(ctx: GenerationContext, rng: random.Random) -> List[Track]:
    p = ctx.preset
    track = make_track("fx")
    density = p.fx_density * (0.5 + 0.5 * ctx.intensity)

    for section in ctx.arrangement.sections:
        if not section.has("fx"):
            continue
        # risers over the last bars of each build
        if section.kind == "build":
            rise_bars = min(8, section.bars)
            start = bar_start(section.end_bar - rise_bars)
            _fx(track, start, rise_bars * 4.0, "riser", 100)
        # impact + downlifter on the first beat of drops and the breakdown
        if section.kind in ("drop", "breakdown"):
            _fx(track, section.start_beat, 2.0, "impact", 118 if section.kind == "drop" else 95)
            _fx(track, section.start_beat, 8.0, "downlifter", 90)
        if section.kind == "intro":
            _fx(track, section.start_beat, min(16.0, section.bars * 4.0), "sweep", 70)

        for bar in range(section.start_bar, section.end_bar):
            e = energy(ctx, section, bar)
            t0 = bar_start(bar)
            # one whoosh per 16-bar phrase inside drops – signposts, not clutter
            if section.kind == "drop" and (bar - section.start_bar) % 16 == 15 and rng.random() < 0.6:
                _fx(track, t0, 4.0, "sweep", 80)
            # psychedelic bubbles / gurgles only in calm passages (classic goa PUHE)
            if section.kind in ("intro", "breakdown", "outro") and rng.random() < density * 0.3:
                s = rng.randrange(STEPS_PER_BAR)
                _fx(track, t0 + s * STEP, rng.choice([0.5, 1.0, 2.0]), "bubble", 75 + rng.randint(-10, 10),
                    rate=round(rng.uniform(6, 22), 1))
    return [track.sort()]
