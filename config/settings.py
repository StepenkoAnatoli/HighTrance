"""
Configuration and default settings for the Goa Trance Generator
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Dict, List, Tuple

# ======================
# DEFAULT VALUES
# ======================

DEFAULTS = {
    "style": "goa",             # Classic Goa Trance
    "bpm": 142,                 # Typical range: 138–148
    "length": 4.5,              # Track length in minutes (3-6)
    "key": "Am",                # Default key
    "intensity": 0.85,          # 0.5 (chill) → 1.0 (full power)
    "sample_rate": 44100,
    "bit_depth": 16,
}

# ======================
# MUSICAL SETTINGS
# ======================

# Allowed style
STYLES = ["goa"]

# Recommended BPM range
BPM_RANGE = (138, 148)

# Common keys used in psytrance / goa
COMMON_KEYS = [
    "Am", "Em", "Dm", "Bm", "F#m", "C#m",
    "A", "E", "D", "B", "F#", "C#"
]

# Track structure ratios (approximate percentage of total length)
STRUCTURE = {
    "intro": 0.15,          # 15%
    "build1": 0.12,         # 12%
    "drop1": 0.20,          # 20%
    "breakdown": 0.18,      # 18%
    "build2": 0.10,         # 10%
    "drop2": 0.18,          # 18%
    "outro": 0.07,          # 7%
}

# ======================
# SOUND DESIGN DEFAULTS
# ======================

# Bass settings
BASS = {
    "goa": {
        "pattern": "16th_rolling",
        "waveform": "saw",
        "filter_mod": True,
        "sidechain": True,
    },
}

# Lead / Melody settings
LEADS = {
    "goa": {
        "style": "eastern_melodic",
        "delay": True,
        "reverb": True,
    },
}

# Drum kit emphasis
DRUMS = {
    "goa": {
        "tribal": True,
        "organic": True,
        "kick_punch": "medium",
    },
}

# ======================
# OUTPUT SETTINGS
# ======================

OUTPUT = {
    "midi_folder": "output/midi",
    "audio_folder": "output/audio",
    "default_format": "midi",       # "midi" or "audio"
    "audio_format": "wav",          # "wav" or "mp3"
}

# ======================
# POST-RENDER MASTERING (synthesis/audio_processor.py)
# ======================

MASTERING = {
    "enabled": True,             # master rendered audio before export (--no-master skips it)
    "highpass_hz": 20.0,         # rumble cleanup; zero-phase, keeps the kick fundamental
    "lowmid_hz": 300.0,          # muddy low-mid bell ...
    "lowmid_db": -2.5,           # ... gentle cut
    "presence_hz": 3500.0,       # presence bell ...
    "presence_db": 1.5,          # ... small boost
    "air_hz": 11000.0,           # air band ...
    "air_db": 1.5,               # ... small boost
    "width": 1.15,               # mid/side stereo width (1.0 = unchanged)
    "threshold_db": -12.0,       # gentle bus compressor (glue, not loudness)
    "ratio": 2.0,
    "attack_ms": 10.0,
    "release_ms": 100.0,
    "knee_threshold": 0.6,       # soft-knee peak control before normalisation ...
    "knee_ceiling": 0.95,        # ... absorbs EQ-boosted transients
    "target_peak_db": -1.0,      # final peak-normalisation ceiling
    "backend": "auto",           # "auto" (pedalboard when installed) | "numpy" | "pedalboard"
                                 # spec: docs/superpowers/specs/2026-10-09-sidechain-pedalboard-design.md
}

# ======================
# HUMAN REVIEW MODE (ui/review.py, ai/reviewer.py)
# ======================

REVIEW = {
    "llm": {
        # Any OpenAI-compatible endpoint: local Ollama, LM Studio, OpenRouter, OpenAI ...
        "base_url": "http://localhost:11434/v1",
        "api_key": "not-needed-for-ollama",
        "model": "llama3.1:8b",
        "temperature": 0.2,
        "timeout": 60.0,
    },
    "history_rounds": 6,      # how many past rounds the LLM sees for context
}

# ======================
# AI REFINEMENT (Path B)
# ======================

AI = {
    "enabled": False,               # Set to True to use local AI refinement
    "model": "musicgen",            # "musicgen" or "riffusion"
    "device": "cpu",                # "cpu" or "cuda"
}

# ======================
# EXTENDED SETTINGS (used internally by the generator)
# ======================

BPM_MIN, BPM_MAX = BPM_RANGE

#: Length range (minutes) used when the length is chosen automatically.
DEFAULT_LENGTH_RANGE: Tuple[float, float] = (3.0, 6.0)
#: Hard limits accepted from the user (minutes).
LENGTH_LIMITS: Tuple[float, float] = (3.0, 6.0)

DEFAULT_INTENSITY = DEFAULTS["intensity"]
DEFAULT_SAMPLE_RATE = DEFAULTS["sample_rate"]
BEATS_PER_BAR = 4
TICKS_PER_BEAT = 480

#: Order of the sections in the energy arc.
SECTION_ORDER: Tuple[str, ...] = tuple(STRUCTURE.keys())

# ---------------------------------------------------------------------------
# Music theory tables
# ---------------------------------------------------------------------------

NOTE_NAMES: List[str] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_ALIASES: Dict[str, str] = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#",
                                "CB": "B", "FB": "E", "E#": "F", "B#": "C"}

#: All scales are heptatonic so scale-degree arithmetic works uniformly.
SCALES: Dict[str, List[int]] = {
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "phrygian_dominant": [0, 1, 4, 5, 7, 8, 10],
    "double_harmonic": [0, 1, 4, 5, 7, 8, 11],
    "hungarian_minor": [0, 2, 3, 6, 7, 8, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    # Major-third modes (used for major keys such as "A" or "F#")
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
}

#: Scales with a major third – chosen when the key has no "m" suffix.
MAJOR_SCALES: Tuple[str, ...] = ("phrygian_dominant", "double_harmonic", "mixolydian", "major")

STYLE_LABELS: Dict[str, str] = {
    "goa": "Classic Goa Trance",
}

# ---------------------------------------------------------------------------
# General MIDI mapping (so the .mid plays sensibly in any GM synth / DAW)
# ---------------------------------------------------------------------------

DRUM_CHANNEL = 9
GM = {
    "kick": 36, "rim": 37, "snare": 38, "clap": 39, "snare2": 40,
    "tom_low": 41, "hat_closed": 42, "tom_mid_low": 45, "hat_pedal": 44,
    "hat_open": 46, "tom_mid": 47, "tom_high": 50, "crash": 49, "ride": 51,
    "tambourine": 54, "cowbell": 56, "bongo_high": 60, "bongo_low": 61,
    "conga_mute": 62, "conga_open": 63, "conga_low": 64, "shaker": 70,
    "claves": 75,
}

#: name -> (midi channel, GM program number)
TRACK_LAYOUT: Dict[str, Tuple[int, int]] = {
    "kick": (DRUM_CHANNEL, 0),
    "percussion": (DRUM_CHANNEL, 0),
    "bass": (0, 38),      # Synth Bass 1
    "acid": (1, 87),      # Lead 8 (bass + lead)
    "lead": (2, 81),      # Lead 2 (sawtooth)
    "arp": (3, 80),       # Lead 1 (square)
    "pad": (4, 89),       # Pad 2 (warm)
    "texture": (5, 95),   # Pad 8 (sweep)
    "fx": (6, 102),       # FX 7 (echoes)
}

#: Pitches used on the FX track (one per FX type – also used for MIDI).
FX_PITCHES: Dict[str, int] = {
    "riser": 72, "downlifter": 71, "impact": 36, "zap": 84,
    "sweep": 76, "bubble": 79, "laser": 88,
}

# ---------------------------------------------------------------------------
# Style presets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StylePreset:
    """All the knobs that make Goa sound like Goa."""

    name: str
    bpm_range: Tuple[int, int]
    keys: Tuple[str, ...]
    scales: Tuple[str, ...]
    #: Root-degree progressions (each entry spans ``chord_bars`` bars).
    progressions: Tuple[Tuple[int, ...], ...]
    breakdown_progressions: Tuple[Tuple[int, ...], ...]
    chord_bars: int = 4
    # --- drums ---
    kick_decay: float = 0.32          # seconds
    kick_pitch: float = 160.0         # Hz at the start of the sweep
    hat_density: float = 0.6          # probability of 16th closed hats
    tribal: float = 0.6               # amount of organic/tribal percussion
    ghost_prob: float = 0.1           # ghost snare probability per 16th
    roll_prob: float = 0.15           # 32nd hat/snare rolls at phrase ends
    polyrhythm: float = 0.2           # 3-over-4 percussion probability
    # --- bass ---
    bass_octave_prob: float = 0.2
    bass_movement_prob: float = 0.25
    bass_gate: float = 0.75
    bass_cutoff: float = 900.0        # Hz
    bass_detune: float = 0.006        # ratio
    # --- leads / arps ---
    lead_density: float = 0.55
    ornament_prob: float = 0.3        # eastern grace notes / trills
    lead_wave: str = "supersaw"
    arp_grouping: int = 3             # 3 = hypnotic 3-over-4 grouping
    # --- acid ---
    acid_density: float = 0.65
    acid_accent_prob: float = 0.25
    acid_slide_prob: float = 0.25
    acid_resonance: float = 6.0
    acid_wave: str = "saw"
    acid_cutoff: float = 500.0
    # --- pads / fx ---
    pad_brightness: float = 0.5
    fx_density: float = 0.5
    # --- space ---
    reverb_size: float = 2.6          # seconds of tail
    delay_feedback: float = 0.45
    # --- linked to the BASS / LEADS / DRUMS tables above ---
    bass_pattern: str = "16th_rolling"
    bass_wave: str = "saw"
    bass_filter_mod: bool = True
    bass_sidechain: bool = True
    lead_style: str = "eastern_melodic"
    lead_delay: bool = True
    lead_reverb: bool = True
    tribal_enabled: bool = True
    organic: bool = True
    kick_punch: float = 0.6           # 0 (soft) .. 1 (hard)


KICK_PUNCH = {"soft": 0.3, "medium": 0.6, "hard": 1.0}


def _table_params(style: str) -> dict:
    """Map the human-readable BASS / LEADS / DRUMS tables onto preset fields."""
    bass, leads, drums = BASS[style], LEADS[style], DRUMS[style]
    return dict(
        bass_pattern=bass["pattern"], bass_wave=bass["waveform"],
        bass_filter_mod=bass["filter_mod"], bass_sidechain=bass["sidechain"],
        lead_style=leads["style"], lead_delay=leads["delay"], lead_reverb=leads["reverb"],
        tribal_enabled=drums["tribal"], organic=drums["organic"],
        kick_punch=KICK_PUNCH.get(drums["kick_punch"], 0.6),
    )


GOA = StylePreset(
    name="goa",
    bpm_range=(138, 145),
    keys=("Em", "Fm", "F#m", "Gm", "Am", "Dm", "E", "F#"),
    scales=("phrygian", "phrygian_dominant", "harmonic_minor", "double_harmonic", "hungarian_minor"),
    progressions=((0, 0, 0, 0), (0, 0, 1, 0), (0, 0, 5, 6), (0, 6, 5, 6), (0, 3, 0, 4), (0, 1, 0, 6)),
    breakdown_progressions=((0, 5, 3, 4), (0, 6, 5, 4), (0, 3, 6, 5), (0, 1, 5, 6)),
    chord_bars=4,
    kick_decay=0.34, kick_pitch=150.0,
    hat_density=0.45, tribal=0.85, ghost_prob=0.05, roll_prob=0.1, polyrhythm=0.35,
    bass_octave_prob=0.3, bass_movement_prob=0.3, bass_gate=0.8, bass_cutoff=800.0, bass_detune=0.008,
    lead_density=0.6, ornament_prob=0.45, lead_wave="supersaw", arp_grouping=3,
    acid_density=0.55, acid_accent_prob=0.2, acid_slide_prob=0.35, acid_resonance=5.0,
    acid_wave="saw", acid_cutoff=450.0,
    pad_brightness=0.55, fx_density=0.45, reverb_size=3.2, delay_feedback=0.5,
    **_table_params("goa"),
)

STYLE_PRESETS: Dict[str, StylePreset] = {"goa": GOA}


def get_preset(style: str) -> StylePreset:
    try:
        return STYLE_PRESETS[style]
    except KeyError:
        raise ValueError(f"Unknown style {style!r}; choose from {', '.join(STYLES)}") from None


# ---------------------------------------------------------------------------
# Mix presets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MixSettings:
    volume_db: float = 0.0
    pan: float = 0.0              # -1 (left) .. +1 (right)
    highpass: float = 0.0         # Hz, 0 = off
    lowpass: float = 0.0          # Hz, 0 = off
    sidechain: float = 0.0        # 0..1 ducking depth triggered by the kick
    reverb_send: float = 0.0      # 0..1
    delay_send: float = 0.0       # 0..1
    compress: float = 0.0         # 0..1 amount of bus compression
    extra: Dict[str, float] = field(default_factory=dict)


MIX_PRESETS: Dict[str, MixSettings] = {
    "kick": MixSettings(volume_db=-1.0, highpass=25, compress=0.3),
    "percussion": MixSettings(volume_db=-6.0, highpass=180, sidechain=0.2, reverb_send=0.12, compress=0.4),
    "bass": MixSettings(volume_db=-2.0, highpass=32, lowpass=4500, sidechain=0.8, compress=0.5),
    "acid": MixSettings(volume_db=-3.0, pan=0.12, highpass=90, sidechain=0.5, reverb_send=0.15, delay_send=0.3),
    "lead": MixSettings(volume_db=-12.0, pan=-0.08, highpass=200, sidechain=0.45, reverb_send=0.35, delay_send=0.35),
    "arp": MixSettings(volume_db=-15.0, pan=0.2, highpass=250, sidechain=0.5, reverb_send=0.3, delay_send=0.45),
    "pad": MixSettings(volume_db=-15.0, highpass=180, lowpass=9000, sidechain=0.65, reverb_send=0.45),
    "texture": MixSettings(volume_db=-19.0, pan=-0.15, highpass=120, sidechain=0.4, reverb_send=0.6),
    "fx": MixSettings(volume_db=-10.0, highpass=60, reverb_send=0.5, delay_send=0.25),
}


def get_mix(track_name: str) -> MixSettings:
    return MIX_PRESETS.get(track_name, MixSettings())


# ======================
# STEMS EXPORT (synthesis/audio_render.py)
# ======================

#: Ceiling a written stem is scaled to. Stems are pre-master, so they are
#: not peak-normalised like the exported mix; one shared gain (see the
#: stems spec, D3) lifts the loudest stem to this peak so no WAV clips.
STEMS = {"peak": 0.95}

#: Per-group stems: group name -> the track names mixed into it. The
#: insertion order is the file / sum order. Every track name in
#: ``TRACK_ORDER`` (``core.generator``) appears in exactly one group;
#: ``stem_group`` raises for an unknown name so a new track type can
#: never silently vanish from the stems.
STEM_GROUPS: Dict[str, Tuple[str, ...]] = {
    "drums": ("kick", "percussion"),
    "bass": ("bass",),
    "leads": ("acid", "lead", "arp"),
    "pads": ("pad", "texture"),
    "fx": ("fx",),
}

#: Reverse map (track name -> group), built once at import time.
_TRACK_TO_STEM: Dict[str, str] = {
    name: group for group, names in STEM_GROUPS.items() for name in names
}


def stem_group(track_name: str) -> str:
    """Return the stem group a track name belongs to.

    Raises ``ValueError`` for an unknown name (the render path catches
    it into ``result["errors"]``; the default, stems-off render never
    calls this).
    """
    try:
        return _TRACK_TO_STEM[track_name]
    except KeyError:
        raise ValueError(
            f"Unknown track name for stem grouping: {track_name!r}") from None


# ======================
# SIDECHAIN (synthesis/mixer.py, synthesis/audio_render.py)
# ======================

SIDECHAIN = {
    # "audio": duck from the rendered kick's amplitude envelope (real, audio-level)
    # "note":  legacy synthetic curve from the kick note-start times
    "mode": "audio",
    "gate": 0.35,         # envelope level below which the duck is fully open
    "hold_ms": 5.0,       # peak-hold window (also gives ~half this as lookahead)
    "release_ms": 110.0,  # decay used by the "note" fallback curve
}
