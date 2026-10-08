"""
Main Generator – Orchestrates the entire track creation process.

user choices + seed → arrangement → harmony → independent modules
(drums, bass, leads, pads, fx) → MIDI (+ optional mixed WAV/MP3).
"""

from __future__ import annotations

import random
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config.settings import (AI, BPM_MAX, BPM_MIN, DEFAULT_LENGTH_RANGE, DEFAULTS, LENGTH_LIMITS, MASTERING,
                             MAJOR_SCALES, OUTPUT, SCALES, STRUCTURE, STYLE_LABELS, STYLES, get_preset)
from core.arrangement import Arrangement, arrangement_to_dict, build_arrangement
from core.models import GenerationContext, Song, Track
from core.seed import SeedManager, derive_seed, generate_seed
from core.theory import Harmony, Scale, key_name, parse_key, scale_quality
from modules import bass, drums, fx, leads, pads
from synthesis.midi_engine import song_to_midi

ModuleFn = Callable[[GenerationContext, random.Random], List[Track]]

#: Independent generation modules, in mixing order.
MODULES: Dict[str, ModuleFn] = {
    "drums": drums.generate,
    "bass": bass.generate,
    "leads": leads.generate,
    "pads": pads.generate,
    "fx": fx.generate,
}

TRACK_ORDER = ["kick", "percussion", "bass", "acid", "lead", "arp", "pad", "texture", "fx"]


def _auto(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in ("", "auto", "random"))


class TranceGenerator:
    def __init__(
        self,
        style: str = DEFAULTS["style"],
        bpm: Optional[float] = DEFAULTS["bpm"],
        length_minutes: Optional[float] = DEFAULTS["length"],
        key: Optional[str] = DEFAULTS["key"],
        seed: Optional[int] = None,
        intensity: float = DEFAULTS["intensity"],
        output_dir="output",
        scale: Optional[str] = None,
        sample_rate: int = DEFAULTS["sample_rate"],
        bit_depth: int = DEFAULTS["bit_depth"],
        audio_format: str = OUTPUT["audio_format"],
        renderer: str = "auto",
        soundfont: Optional[str] = None,
        verbose: bool = True,
    ):
        """Create a generator. ``bpm``, ``length_minutes``, ``key`` and ``scale`` may be
        ``None``/``"auto"`` to let the seed choose them within the style's range."""
        self.style = (style or DEFAULTS["style"]).lower()
        if self.style not in STYLES:
            raise ValueError(f"Unknown style {style!r}; choose from {', '.join(STYLES)}")
        self.preset = get_preset(self.style)
        self.seed = int(seed) if seed is not None else generate_seed()
        self.seeds = SeedManager(self.seed)
        choice = self.seeds.rng("parameters")

        # --- tempo (138–148 BPM) ---
        if _auto(bpm):
            lo, hi = self.preset.bpm_range
            self.bpm = choice.randint(max(lo, BPM_MIN), min(hi, BPM_MAX))
        else:
            self.bpm = float(bpm)
            if not BPM_MIN <= self.bpm <= BPM_MAX:
                raise ValueError(f"BPM must be between {BPM_MIN} and {BPM_MAX} (got {bpm})")
            if self.bpm.is_integer():
                self.bpm = int(self.bpm)

        # --- length ---
        if _auto(length_minutes):
            self.length_minutes = round(choice.uniform(*DEFAULT_LENGTH_RANGE), 2)
        else:
            self.length_minutes = float(length_minutes)
            if not LENGTH_LIMITS[0] <= self.length_minutes <= LENGTH_LIMITS[1]:
                raise ValueError(f"Length must be between {LENGTH_LIMITS[0]:g} and {LENGTH_LIMITS[1]:g} minutes")

        # --- key / scale ---
        key = choice.choice(self.preset.keys) if _auto(key) else key
        self.root, quality = parse_key(key)
        if _auto(scale):
            pool = [s for s in self.preset.scales if scale_quality(s) == quality]
            if not pool:
                pool = list(MAJOR_SCALES[:2]) if quality == "major" else ["phrygian", "minor"]
            self.scale_name = choice.choice(pool)
        else:
            if scale not in SCALES:
                raise ValueError(f"Unknown scale {scale!r}; choose from {', '.join(SCALES)}")
            self.scale_name = scale
        self.key = key_name(self.root, scale_quality(self.scale_name))
        self.scale = Scale(self.root, self.scale_name)

        # --- intensity ---
        self.intensity = float(intensity)
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError("Intensity must be between 0.0 and 1.0")

        self.output_dir = Path(output_dir)
        self.sample_rate = int(sample_rate)
        self.bit_depth = int(bit_depth)
        self.audio_format = audio_format
        self.renderer = renderer
        self.soundfont = soundfont
        self.verbose = verbose

        # Calculate total beats
        self.total_beats = self.length_minutes * self.bpm

    # ------------------------------------------------------------------ composition
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def build_arrangement(self) -> Arrangement:
        return build_arrangement(self.bpm, self.length_minutes, self.seeds.rng("arrangement"), STRUCTURE)

    def build_harmony(self, arrangement: Arrangement) -> Harmony:
        rng = self.seeds.rng("harmony")
        p = self.preset
        drop_prog = rng.choice(p.progressions)       # shared by both drops -> song identity
        roots: List[int] = []
        for section in arrangement.sections:
            if section.kind == "drop":
                prog = drop_prog
            elif section.kind == "breakdown":
                prog = rng.choice(p.breakdown_progressions)
            elif section.kind in ("intro", "outro"):
                prog = (0, 0, 0, 0) if rng.random() < 0.7 else rng.choice(p.progressions)
            else:
                prog = rng.choice(p.progressions)
            roots.extend(prog[(i // p.chord_bars) % len(prog)] for i in range(section.bars))
        return Harmony(self.scale, roots)

    def context(self, arrangement: Arrangement, harmony: Harmony) -> GenerationContext:
        return GenerationContext(style=self.style, preset=self.preset, arrangement=arrangement, harmony=harmony,
                                 scale=self.scale, bpm=self.bpm, intensity=self.intensity)

    def run_module(self, name: str, ctx: GenerationContext, seed: Optional[int] = None) -> List[Track]:
        """Run one module with its own independent random stream."""
        module_seed = seed if seed is not None else derive_seed(self.seed, "module", name)
        return MODULES[name](ctx, random.Random(module_seed))

    def compose(self) -> Song:
        """Generate the complete song in memory (no files written)."""
        arrangement = self.build_arrangement()
        harmony = self.build_harmony(arrangement)
        ctx = self.context(arrangement, harmony)
        song = Song(style=self.style, bpm=self.bpm, key=self.key, scale=self.scale, seed=self.seed,
                    intensity=self.intensity, length_minutes=self.length_minutes,
                    arrangement=arrangement, harmony=harmony)
        tracks: List[Track] = []
        for name in MODULES:
            song.module_seeds[name] = derive_seed(self.seed, "module", name)
            tracks.extend(self.run_module(name, ctx))
        song.tracks = sorted(tracks, key=lambda t: TRACK_ORDER.index(t.name) if t.name in TRACK_ORDER else 99)
        return song

    def regenerate_module(self, song: Song, module: str, seed: Optional[int] = None) -> Song:
        """Re-create only one module's tracks (e.g. a new bassline), keeping everything else."""
        if module not in MODULES:
            raise ValueError(f"Unknown module {module!r}; choose from {', '.join(MODULES)}")
        seed = seed if seed is not None else generate_seed()
        ctx = self.context(song.arrangement, song.harmony)
        new_tracks = {t.name: t for t in self.run_module(module, ctx, derive_seed(seed, "module", module))}
        song.tracks = [new_tracks.pop(t.name, t) for t in song.tracks] + list(new_tracks.values())
        song.module_seeds[module] = derive_seed(seed, "module", module)
        return song

    # ------------------------------------------------------------------ files
    def generate(self, render_audio: bool = False, audio_format: Optional[str] = None,
                 song: Optional[Song] = None, progress=None, master: Optional[bool] = None) -> Dict:
        """
        Main generation method.
        Returns a dictionary with information about the generated track.

        ``master`` runs the post-render mastering stage (EQ / compression /
        normalisation, see ``synthesis.audio_processor``); ``None`` honours
        ``MASTERING["enabled"]``.
        """
        fmt = None
        if render_audio:
            requested_format = self.audio_format if audio_format is None else audio_format
            if not isinstance(requested_format, str) or requested_format.strip().lower() not in ("wav", "mp3"):
                raise ValueError("audio_format must be 'wav' or 'mp3'")
            fmt = requested_format.strip().lower()

        start_time = time.time()
        self._log(f"→ Style      : {STYLE_LABELS[self.style]}")
        self._log(f"→ BPM        : {self.bpm}")
        self._log(f"→ Length     : {self.length_minutes} min")
        self._log(f"→ Key        : {self.key} ({self.scale.label()})")
        self._log(f"→ Seed       : {self.seed}")
        self._log(f"→ Intensity  : {self.intensity}")

        self._log("\nGenerating layers...")
        song = song or self.compose()

        midi_dir = self.output_dir / "midi"
        audio_dir = self.output_dir / "audio"
        midi_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        stem = f"{song.title}_{timestamp}"
        midi_path = song_to_midi(song).save(f"{stem}.mid", output_dir=midi_dir)

        result = {
            "style": self.style,
            "bpm": self.bpm,
            "key": self.key,
            "scale": self.scale_name,
            "seed": self.seed,
            "intensity": self.intensity,
            "length_minutes": self.length_minutes,
            "duration_seconds": round(song.duration_seconds, 1),
            "arrangement": arrangement_to_dict(song.arrangement),
            "sections": [(s.label, s.start_bar, s.bars) for s in song.arrangement.sections],
            "tracks": {t.name: len(t.notes) for t in song.tracks},
            "midi_path": midi_path,
            "audio_path": None,
            "song": song,
            "errors": [],
        }

        if render_audio:
            from synthesis.audio_render import AudioGenerator
            try:
                audio_dir.mkdir(parents=True, exist_ok=True)
                audio_gen = AudioGenerator(soundfont_path=self.soundfont, sample_rate=self.sample_rate,
                                           bit_depth=self.bit_depth, renderer=self.renderer)
                self._log("Rendering audio (built-in synthesizer)..." if self.renderer != "fluidsynth"
                          else "Rendering audio (FluidSynth)...")
                result["audio_path"] = audio_gen.render(midi_path, "wav", audio_dir / f"{stem}.wav",
                                                        song=song, progress=progress)

                do_master = MASTERING["enabled"] if master is None else bool(master)
                if do_master:
                    # optional stage: a mastering failure keeps the raw render
                    try:
                        from synthesis.audio_processor import process_audio
                        self._log("Mastering audio (EQ / compression / normalisation)...")
                        result["audio_path"] = process_audio(result["audio_path"])
                        self._log(f"Mastered audio: {result['audio_path']}")
                    except Exception as e:
                        result["errors"].append(f"Mastering failed: {e}")
                        self._log(f"Mastering failed: {e}")

                if fmt == "mp3":   # keep the WAV even if the MP3 conversion is not possible
                    from synthesis.audio_render import wav_to_mp3
                    result["audio_path"] = wav_to_mp3(result["audio_path"])
                self._log(f"Audio rendered: {result['audio_path']}")
            except Exception as e:  # keep the MIDI even if audio fails
                result["errors"].append(f"Audio rendering failed: {e}")
                self._log(f"Audio rendering failed: {e}")

            if AI["enabled"] and result["audio_path"]:
                try:
                    from ai.refiner import refine_track
                    self._log("Refining audio with local AI model...")
                    result["ai_audio_path"] = refine_track(result)
                except Exception as e:  # optional path – never lose the main result
                    result["errors"].append(f"AI refinement failed: {e}")

        result["generation_time"] = round(time.time() - start_time, 2)
        self._log(f"\nGeneration completed in {result['generation_time']} seconds")
        self._log(f"MIDI saved to: {midi_path}")
        return result
