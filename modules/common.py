"""Helpers shared by the generation modules."""

from __future__ import annotations

from config.settings import BEATS_PER_BAR, TRACK_LAYOUT
from core.models import GenerationContext, Track

STEP = 0.25           # one 16th note in beats
STEPS_PER_BAR = int(BEATS_PER_BAR / STEP)


def make_track(name: str, instrument: str | None = None) -> Track:
    channel, program = TRACK_LAYOUT[name]
    return Track(name=name, instrument=instrument or name, channel=channel, program=program)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def energy(ctx: GenerationContext, section, bar: float) -> float:
    """Section energy scaled by the user intensity (0.5 = laid back, 1.0 = full power)."""
    return clamp(section.energy_at(bar) * (0.7 + 0.4 * ctx.intensity))


def bar_start(bar: int) -> float:
    return float(bar * BEATS_PER_BAR)


def is_phrase_end(section, bar: int, phrase: int = 8) -> bool:
    return (bar - section.start_bar) % phrase == phrase - 1 or bar == section.end_bar - 1


def is_pre_drop(section, bar: int) -> bool:
    """Last 2 bars of a build-up: thin-out + silence-hole before the drop.

    Research (myloops 'tension before a drop', Blueprint huge-drop guide):
    a 1-bar hole reads as a glitch; the classic tension bar is the LAST bar
    where rhythmic elements get stripped and the riser carries the bar."""
    return section.kind == "build" and bar >= section.end_bar - 1


def velocity(base: float, rng, spread: int = 6) -> int:
    return int(max(1, min(127, round(base + rng.randint(-spread, spread)))))
