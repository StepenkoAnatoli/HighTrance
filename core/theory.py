"""Small music-theory helpers: key parsing, scales and per-bar harmony."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from config.settings import FLAT_ALIASES, MAJOR_SCALES, NOTE_NAMES, SCALES

_KEY_RE = re.compile(r"^\s*([A-Ga-g])([#b♯♭]?)\s*(m|min|minor|maj|major|M)?\s*$")


def parse_key(key: str) -> Tuple[int, str | None]:
    """Parse ``"Am"``, ``"F#m"``, ``"Bb minor"``, ``"E"`` ... into ``(pitch_class, quality)``.

    ``quality`` is ``"minor"``, ``"major"`` or ``None`` when not specified
    (a bare note name such as ``"E"`` is treated as *major*-third flavour, the
    way the key list in ``config.settings.COMMON_KEYS`` uses it).
    """
    m = _KEY_RE.match(key or "")
    if not m:
        raise ValueError(f"Invalid key {key!r} (examples: Am, F#m, Dm, E)")
    letter, accidental, quality = m.groups()
    name = letter.upper() + accidental.replace("♯", "#").replace("♭", "b").replace("b", "B")
    name = FLAT_ALIASES.get(name.upper(), name.upper())
    if name not in NOTE_NAMES:
        raise ValueError(f"Invalid key {key!r}")
    if quality in ("m", "min", "minor"):
        q = "minor"
    elif quality in ("maj", "major", "M"):
        q = "major"
    else:
        q = "major"
    return NOTE_NAMES.index(name), q


def key_name(root: int, quality: str) -> str:
    return NOTE_NAMES[root % 12] + ("m" if quality == "minor" else "")


def scale_quality(scale: str) -> str:
    return "major" if scale in MAJOR_SCALES else "minor"


@dataclass(frozen=True)
class Scale:
    root: int                 # pitch class 0..11
    name: str

    @property
    def intervals(self) -> List[int]:
        return SCALES[self.name]

    def pitch(self, degree: int, octave: int = 4) -> int:
        """MIDI pitch of a (possibly negative / >7) scale degree. Octave 4 => C4 = 60."""
        octave_shift, idx = divmod(int(degree), 7)
        return 12 * (octave + 1 + octave_shift) + self.root + self.intervals[idx]

    def chord(self, degree: int, octave: int = 4, size: int = 3) -> List[int]:
        return [self.pitch(degree + 2 * i, octave) for i in range(size)]

    def contains(self, pitch: int) -> bool:
        return (pitch - self.root) % 12 in self.intervals

    def label(self) -> str:
        return f"{NOTE_NAMES[self.root]} {self.name.replace('_', ' ')}"


class Harmony:
    """Root scale-degree for each bar of the track."""

    def __init__(self, scale: Scale, roots: Sequence[int]):
        self.scale = scale
        self.roots = list(roots)

    def root(self, bar: int) -> int:
        if not self.roots:
            return 0
        return self.roots[min(max(bar, 0), len(self.roots) - 1)]

    def chord_degrees(self, bar: int, size: int = 3) -> List[int]:
        r = self.root(bar)
        return [r + 2 * i for i in range(size)]
