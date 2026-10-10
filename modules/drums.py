"""Drums: four-on-the-floor kick, hats, claps, rides, tribal/organic percussion,
ghost notes, polyrhythms, rolls, crashes and build-up snare rolls."""

from __future__ import annotations

import random
from typing import Dict, List

from config.settings import GM
from core.models import GenerationContext, Track
from modules.common import (STEP, STEPS_PER_BAR, bar_start, energy, is_phrase_end, is_pre_drop,
                            make_track, velocity)

ORGANIC = ["conga_mute", "conga_open", "conga_low", "bongo_high", "bongo_low", "tom_low", "tom_mid"]
PERC_PAN: Dict[str, float] = {
    "hat_closed": 0.25, "hat_open": -0.1, "shaker": -0.45, "ride": 0.35, "rim": -0.35,
    "conga_mute": 0.4, "conga_open": 0.3, "conga_low": -0.3, "bongo_high": 0.55, "bongo_low": -0.5,
    "tom_low": -0.4, "tom_mid": 0.4, "tom_high": 0.2, "tambourine": 0.5, "claves": -0.6,
    "snare": 0.0, "clap": 0.0, "crash": 0.0, "cowbell": 0.45,
}


def _section_patterns(ctx: GenerationContext, rng: random.Random) -> dict:
    """Fixed 16-step patterns for one section – repetition is what makes trance hypnotic."""
    p = ctx.preset
    hats = [s % 4 == 2 or rng.random() < p.hat_density for s in range(STEPS_PER_BAR)]
    tribal: List[str | None] = [None] * STEPS_PER_BAR
    if p.tribal_enabled:
        for s in range(STEPS_PER_BAR):
            if s % 4 != 0 and rng.random() < p.tribal * 0.4:
                tribal[s] = rng.choice(ORGANIC if p.organic else ["tom_low", "tom_mid", "rim"])
    ghosts = [s % 4 != 0 and rng.random() < p.ghost_prob for s in range(STEPS_PER_BAR)]
    return {
        "hats": hats,
        "tribal": tribal,
        "ghosts": ghosts,
        "shaker": p.organic and rng.random() < 0.7,
        "poly": rng.random() < p.polyrhythm,
        "poly_inst": rng.choice(["rim", "claves", "cowbell"] if not p.organic else ["conga_mute", "claves", "rim"]),
        "kick_var": rng.choice([None, None, "skip_last", "double"]),
        "snare_layer": False,
    }


def _hit(track: Track, beat: float, name: str, vel: int, length: float = 0.1) -> None:
    track.add(beat, length, GM[name], vel, pan=PERC_PAN.get(name, 0.0), drum=name)


def generate(ctx: GenerationContext, rng: random.Random) -> List[Track]:
    p = ctx.preset
    kick = make_track("kick", "kick")
    perc = make_track("percussion", "percussion")

    for section in ctx.arrangement.sections:
        pat = _section_patterns(ctx, rng)
        # Soft, quiet openings: the groove must invite the listener in first.
        vscale = 0.7 if section.kind == "intro" else 0.8 if section.kind == "outro" else 1.0

        def H(track, beat, name, vel, length=0.1):
            _hit(track, beat, name, int(vel * vscale), length)
        for bar in range(section.start_bar, section.end_bar):
            e = energy(ctx, section, bar)
            t0 = bar_start(bar)
            pre_drop = is_pre_drop(section, bar)
            last_bar = bar == section.end_bar - 1
            hole_bar = section.kind == "build" and last_bar   # full strip: drop returns all-at-once
            phrase_end = is_phrase_end(section, bar)
            progress = section.progress(bar)

            # ---------------- kick ----------------
            if section.has("kick") and not (section.kind == "outro" and progress >= 0.85):
                beats = [0, 1, 2, 3]
                if hole_bar:
                    beats = []                    # the hole: silence before impact
                elif pre_drop:
                    beats = [0, 2]                # half-time pulse into the hole
                elif phrase_end and section.kind in ("drop", "build") and pat["kick_var"] == "skip_last":
                    beats = [0, 1, 2]
                elif phrase_end and section.kind == "drop" and pat["kick_var"] == "double":
                    beats = [0, 1, 2, 3, 3.5]
                for b in beats:
                    kick.add(t0 + b, 0.25, GM["kick"], int((118 + 20 * e) if b == int(b) else 98))

            # ---------------- crashes ----------------
            if section.kind == "drop" and (bar - section.start_bar) % 16 == 0:
                H(perc, t0, "crash", 110, 2.0)

            # ---------------- build-up snare roll ----------------
            if section.kind == "build":
                roll_bars = min(4 if section.bars >= 8 else 2, section.bars)
                roll_start = section.end_bar - roll_bars
                if bar >= roll_start:
                    for beat in range(4):
                        if pre_drop and beat >= 2:
                            break
                        rp = ((bar - roll_start) * 4 + beat) / (roll_bars * 4)
                        div = 1 if rp < 0.25 else 2 if rp < 0.5 else 4 if rp < 0.85 else 8
                        for k in range(div):
                            H(perc, t0 + beat + k / div, "snare", int(50 + 70 * rp), 0.5 / div)

            if not section.has("percussion") or pre_drop:
                continue
            if section.kind == "outro" and progress >= 0.85:
                continue

            for s in range(STEPS_PER_BAR):
                t = t0 + s * STEP
                beat_pos = s % 4
                # off-beat open hat – the classic psy "tss"
                if beat_pos == 2 and e > 0.35:
                    H(perc, t, "hat_open", velocity(88, rng), 0.2)
                # rolling closed hats
                if e > 0.45 and pat["hats"][s] and beat_pos != 2:
                    H(perc, t, "hat_closed", velocity(72 if beat_pos == 0 else 58, rng, 8), 0.08)
                # clap / snare on 2 & 4
                if s in (4, 12) and e > 0.55:
                    H(perc, t, "clap", velocity(100, rng, 4), 0.2)
                    if pat["snare_layer"]:
                        H(perc, t, "snare", velocity(85, rng, 4), 0.2)
                # ride on off-beats in high energy parts
                if beat_pos == 2 and e > 0.8:
                    H(perc, t, "ride", velocity(70, rng), 0.3)
                # shaker 16ths (organic goa flavour)
                if pat["shaker"] and e > 0.3:
                    H(perc, t, "shaker", velocity(64 if beat_pos == 2 else 42, rng, 5), 0.08)
                # tribal pattern
                inst = pat["tribal"][s]
                if inst and e > 0.3:
                    H(perc, t, inst, velocity(70 + 25 * e, rng, 10), 0.15)
                # high-tech ghost snares
                if pat["ghosts"][s] and e > 0.55:
                    H(perc, t, "snare", velocity(38, rng, 8), 0.06)
                # 3-over-4 polyrhythm, continuous across bar lines
                if pat["poly"] and e > 0.5 and (bar * STEPS_PER_BAR + s) % 3 == 0:
                    H(perc, t, pat["poly_inst"], velocity(62, rng, 8), 0.08)

            # fills / rolls at phrase ends
            if phrase_end and section.kind != "build" and rng.random() < p.roll_prob * (0.5 + e):
                inst = "snare" if rng.random() < 0.4 else "hat_closed"
                if p.tribal_enabled and p.organic and rng.random() < 0.5:
                    inst = rng.choice(["tom_low", "tom_mid", "conga_open"])
                for k in range(8):
                    H(perc, t0 + 3 + k * 0.125, inst, int(55 + k * 7), 0.06)

    return [kick.sort(), perc.sort()]
