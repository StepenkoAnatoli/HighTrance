"""Plain data containers shared by every part of the generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Note:
    """A musical event. Times are in beats (quarter notes) from the start of the song."""

    start: float
    duration: float
    pitch: int
    velocity: int
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class ControlChange:
    time: float          # beats
    controller: int
    value: int


@dataclass
class Track:
    """One instrument part (kick, bass, acid, lead ...)."""

    name: str
    instrument: str
    channel: int
    program: int
    notes: List[Note] = field(default_factory=list)
    controls: List[ControlChange] = field(default_factory=list)

    def add(self, start: float, duration: float, pitch: int, velocity: int, **params: Any) -> Note:
        note = Note(float(start), float(duration), int(pitch), int(max(1, min(127, velocity))), params)
        self.notes.append(note)
        return note

    def cc(self, time: float, controller: int, value: int) -> None:
        self.controls.append(ControlChange(float(time), int(controller), int(max(0, min(127, value)))))

    def sort(self) -> "Track":
        self.notes.sort(key=lambda n: (n.start, n.pitch))
        self.controls.sort(key=lambda c: (c.time, c.controller))
        return self


@dataclass
class GenerationResult:
    """What :meth:`core.generator.TranceGenerator.generate` returns."""

    song: Any
    midi_path: Optional[Any] = None
    wav_path: Optional[Any] = None
    mp3_path: Optional[Any] = None
    elapsed: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass
class GenerationContext:
    """Everything a generation module needs to know about the song being built."""

    style: str
    preset: Any              # config.settings.StylePreset
    arrangement: Any         # core.arrangement.Arrangement
    harmony: Any             # core.theory.Harmony
    scale: Any               # core.theory.Scale
    bpm: float
    intensity: float

    @property
    def total_beats(self) -> float:
        return self.arrangement.total_beats


@dataclass
class Song:
    """A fully generated (but not yet rendered) track."""

    style: str
    bpm: float
    key: str
    scale: Any
    seed: int
    intensity: float
    length_minutes: float
    arrangement: Any
    harmony: Any
    tracks: List[Track] = field(default_factory=list)
    module_seeds: Dict[str, int] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return self.arrangement.duration_seconds

    def track(self, name: str) -> Track:
        for t in self.tracks:
            if t.name == name:
                return t
        raise KeyError(name)

    @property
    def title(self) -> str:
        return f"{self.style}_{self.key.replace('#', 's')}_{int(round(self.bpm))}bpm_seed{self.seed}"
