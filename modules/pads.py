"""Atmospheric pads (evolving chords) and drone textures."""

from __future__ import annotations

import random
from typing import List

from core.models import GenerationContext, Track
from modules.common import bar_start, energy, make_track, velocity


def _pads(ctx: GenerationContext, rng: random.Random) -> Track:
    p = ctx.preset
    track = make_track("pad")
    octave = 3 if ctx.scale.pitch(0, 3) >= 50 else 4
    for section in ctx.arrangement.sections:
        if not section.has("pad"):
            continue
        span = 2 if section.kind == "breakdown" else p.chord_bars
        add9 = rng.random() < 0.5
        for bar in range(section.start_bar, section.end_bar, span):
            e = energy(ctx, section, bar)
            length = min(span, section.end_bar - bar) * 4.0
            root = ctx.harmony.root(bar)
            degrees = [root, root + 2, root + 4, root + 7] + ([root + 8] if add9 else [])
            if section.kind == "breakdown":
                vel, attack = 96, 1.5
            elif section.kind == "drop":
                vel, attack = 58, 0.3
            else:
                vel, attack = 70 + 20 * e, 0.8
            cutoff = 500 + 5000 * p.pad_brightness * (0.4 + e)
            for i, d in enumerate(degrees):
                track.add(bar_start(bar), length * 0.98, ctx.scale.pitch(d, octave), velocity(vel, rng, 3),
                          cutoff=cutoff, attack=attack, pan=(-0.5 + i / max(1, len(degrees) - 1)) * 0.7)
    return track.sort()


def _texture(ctx: GenerationContext, rng: random.Random) -> Track:
    track = make_track("texture")
    octave = 2 if ctx.scale.pitch(0, 2) >= 40 else 3
    for section in ctx.arrangement.sections:
        if not section.has("texture"):
            continue
        for bar in range(section.start_bar, section.end_bar, 8):
            length = min(8, section.end_bar - bar) * 4.0
            e = energy(ctx, section, bar)
            for d in (0, 4):
                track.add(bar_start(bar), length, ctx.scale.pitch(d, octave), velocity(60 + 25 * e, rng, 4),
                          kind=rng.choice(["drone", "wind"]), cutoff=300 + 1500 * e,
                          lfo=round(rng.uniform(0.05, 0.25), 3))
    return track.sort()


def generate(ctx: GenerationContext, rng: random.Random) -> List[Track]:
    pad_rng = random.Random(rng.getrandbits(64))
    tex_rng = random.Random(rng.getrandbits(64))
    return [_pads(ctx, pad_rng), _texture(ctx, tex_rng)]
