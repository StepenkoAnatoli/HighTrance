"""Track structure: Intro → Build-up → Drop 1 → Breakdown → Build 2 → Drop 2 → Outro.

Section lengths come from ``config.settings.STRUCTURE`` (ratios of the total
length), lightly varied by the seed and quantised to 8-bar (or 4-bar) phrases
so that everything lands on musical phrase boundaries.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

from config.settings import BEATS_PER_BAR, SECTION_ORDER, STRUCTURE

#: Section name -> (kind, energy at start, energy at end, active layers)
SECTION_PROFILES: Dict[str, Tuple[str, float, float, FrozenSet[str]]] = {
    "intro": ("intro", 0.15, 0.35,
              frozenset({"kick", "percussion", "bass", "pad", "texture", "fx"})),
    "build1": ("build", 0.34, 0.66,
               frozenset({"kick", "percussion", "bass", "acid", "arp", "pad", "texture", "fx"})),
    "drop1": ("drop", 0.78, 0.86,
              frozenset({"kick", "percussion", "bass", "acid", "lead", "arp", "pad", "fx"})),
    "breakdown": ("breakdown", 0.20, 0.40,
                  frozenset({"pad", "texture", "lead", "arp", "fx"})),
    "build2": ("build", 0.40, 0.90,
               frozenset({"kick", "percussion", "bass", "acid", "arp", "lead", "pad", "fx"})),
    "drop2": ("drop", 0.95, 1.00,
              frozenset({"kick", "percussion", "bass", "acid", "lead", "arp", "pad", "fx"})),
    "outro": ("outro", 0.45, 0.15,
              frozenset({"kick", "percussion", "bass", "acid", "pad", "texture", "fx"})),
}

SECTION_LABELS = {
    "intro": "Intro", "build1": "Build-up", "drop1": "First Drop", "breakdown": "Breakdown",
    "build2": "Second Build", "drop2": "Massive Second Drop", "outro": "Outro",
}


@dataclass(frozen=True)
class Section:
    name: str
    kind: str
    start_bar: int
    bars: int
    energy_start: float
    energy_end: float
    layers: FrozenSet[str]

    @property
    def end_bar(self) -> int:
        return self.start_bar + self.bars

    @property
    def start_beat(self) -> float:
        return float(self.start_bar * BEATS_PER_BAR)

    @property
    def end_beat(self) -> float:
        return float(self.end_bar * BEATS_PER_BAR)

    @property
    def label(self) -> str:
        return SECTION_LABELS.get(self.name, self.name.title())

    def progress(self, bar: float) -> float:
        """0..1 position of an absolute bar inside this section."""
        return min(1.0, max(0.0, (bar - self.start_bar) / max(1, self.bars)))

    def energy_at(self, bar: float) -> float:
        p = self.progress(bar)
        return self.energy_start + (self.energy_end - self.energy_start) * p

    def has(self, layer: str) -> bool:
        return layer in self.layers


@dataclass
class Arrangement:
    sections: List[Section]
    bpm: float

    @property
    def total_bars(self) -> int:
        return self.sections[-1].end_bar if self.sections else 0

    @property
    def total_beats(self) -> float:
        return float(self.total_bars * BEATS_PER_BAR)

    @property
    def duration_seconds(self) -> float:
        return self.total_beats * 60.0 / self.bpm

    def section_at(self, bar: int) -> Section:
        for s in self.sections:
            if s.start_bar <= bar < s.end_bar:
                return s
        return self.sections[-1]

    def bars(self):
        """Iterate ``(bar_index, section)`` over the whole song."""
        for s in self.sections:
            for b in range(s.start_bar, s.end_bar):
                yield b, s

    def by_name(self, name: str) -> Section:
        for s in self.sections:
            if s.name == name:
                return s
        raise KeyError(name)


def _allocate(total_units: int, weights: List[float]) -> List[int]:
    """Largest-remainder allocation with at least one unit per section."""
    n = len(weights)
    total_units = max(total_units, n)
    wsum = sum(weights)
    raw = [w / wsum * total_units for w in weights]
    alloc = [max(1, int(r)) for r in raw]
    while sum(alloc) < total_units:
        i = max(range(n), key=lambda k: raw[k] - alloc[k])
        alloc[i] += 1
    while sum(alloc) > total_units:
        i = max((k for k in range(n) if alloc[k] > 1), key=lambda k: alloc[k] - raw[k])
        alloc[i] -= 1
    return alloc


def build_arrangement(bpm: float, length_minutes: float, rng: random.Random | None = None,
                      structure: Dict[str, float] | None = None) -> Arrangement:
    """Create the section layout for a track of roughly ``length_minutes`` at ``bpm``."""
    if bpm <= 0 or length_minutes <= 0:
        raise ValueError("bpm and length must be positive")
    structure = structure or STRUCTURE
    total_bars = max(len(SECTION_ORDER), round(length_minutes * bpm / BEATS_PER_BAR))
    phrase = 8 if total_bars >= 16 * len(SECTION_ORDER) else 4 if total_bars >= 4 * len(SECTION_ORDER) else 1
    weights = []
    for name in SECTION_ORDER:
        w = structure.get(name, 0.1)
        if rng is not None:
            w *= rng.uniform(0.9, 1.1)
        weights.append(w)
    units = _allocate(max(1, round(total_bars / phrase)), weights)

    sections: List[Section] = []
    bar = 0
    for name, u in zip(SECTION_ORDER, units):
        kind, e0, e1, layers = SECTION_PROFILES[name]
        sections.append(Section(name, kind, bar, u * phrase, e0, e1, layers))
        bar += u * phrase
    return Arrangement(sections, float(bpm))


# ---------------------------------------------------------------------------
# Simple dictionary API (beat-based) – handy for scripts and other modules
# ---------------------------------------------------------------------------

def create_arrangement(total_beats: float, structure: Dict[str, float] | None = None) -> Dict:
    """
    Creates a complete arrangement based on total beats and structure ratios.

    Returns a dictionary containing:
    - sections: list of section names in order
    - timings: dict with start and end beat for each section
    - total_beats: total length in beats
    """
    if structure is None:
        structure = STRUCTURE

    # Normalize ratios so they always sum to 1.0
    total_ratio = sum(structure.values())
    if total_beats <= 0 or total_ratio <= 0:
        raise ValueError("total_beats and structure ratios must be positive")
    normalized = {k: v / total_ratio for k, v in structure.items()}

    sections = list(normalized.keys())
    timings = {}
    current_beat = 0.0

    for section in sections:
        duration = total_beats * normalized[section]
        timings[section] = {
            "start": round(current_beat, 2),
            "end": round(current_beat + duration, 2),
            "duration": round(duration, 2),
        }
        current_beat += duration

    return {
        "sections": sections,
        "timings": timings,
        "total_beats": round(total_beats, 2),
    }


def arrangement_to_dict(arrangement: Arrangement) -> Dict:
    """Express a (phrase-quantised) :class:`Arrangement` in the ``create_arrangement`` format."""
    return {
        "sections": [s.name for s in arrangement.sections],
        "timings": {s.name: {"start": s.start_beat, "end": s.end_beat,
                             "duration": s.end_beat - s.start_beat}
                    for s in arrangement.sections},
        "total_beats": arrangement.total_beats,
    }


def get_section_at_beat(arrangement: Dict, beat: float) -> str:
    """Return the name of the section that is playing at a specific beat."""
    for section, timing in arrangement["timings"].items():
        if timing["start"] <= beat < timing["end"]:
            return section
    return "outro"


def is_drop(section: str) -> bool:
    """Helper to check if a section is a drop."""
    return section in ["drop1", "drop2"]


def is_build(section: str) -> bool:
    """Helper to check if a section is a build-up."""
    return section in ["build1", "build2"]


def is_breakdown(section: str) -> bool:
    return section == "breakdown"
