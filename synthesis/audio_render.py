"""
Audio Generator / Renderer
Turns generated songs (built-in synthesizer) or MIDI files (FluidSynth) into
WAV or MP3.

* ``builtin``  – pure NumPy/SciPy synthesizer + mixer, no external tools needed.
  This is the sound-designed path (rolling bass, acid squelch, sidechain ...).
* ``fluidsynth`` – renders the exported General-MIDI file with a SoundFont via
  ``midi2audio`` or the ``fluidsynth`` command-line tool.
* ``auto`` – built-in when a :class:`core.models.Song` is available, otherwise
  FluidSynth.

MP3 export uses ``ffmpeg`` if it is installed.
"""

from __future__ import annotations

import shutil
import subprocess
import wave
from dataclasses import replace
from pathlib import Path
from typing import Dict, Optional

import numpy as np

try:  # pyfluidsynth may also raise OSError when the native library is missing
    import fluidsynth  # noqa: F401
    FLUIDSYNTH_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the system
    FLUIDSYNTH_AVAILABLE = False

from config.settings import DEFAULTS, OUTPUT, get_mix, get_preset
from synthesis.instruments import VOICES
from synthesis.mixer import Mixer

RENDERERS = ("auto", "builtin", "fluidsynth")


# ---------------------------------------------------------------------------
# Built-in synthesis
# ---------------------------------------------------------------------------

def _note_key(note, dur: float):
    params = tuple(sorted((k, round(v, 1) if isinstance(v, float) else v)
                          for k, v in note.params.items() if k != "pan"))
    return note.pitch, round(dur, 4), params


def render_track(track, bpm: float, sample_rate: int, n_samples: int, preset) -> np.ndarray:
    """Render one :class:`core.models.Track` to a stereo float32 buffer."""
    voice = VOICES[track.instrument]
    out = np.zeros((n_samples, 2), dtype=np.float32)
    cache: Dict = {}
    spb = 60.0 / bpm
    for note in track.notes:
        start = int(round(note.start * spb * sample_rate))
        if start >= n_samples:
            continue
        dur = note.duration * spb
        key = _note_key(note, dur)
        buf = cache.get(key)
        if buf is None:
            buf = voice(note, dur, sample_rate, preset).astype(np.float32)
            cache[key] = buf
        end = min(n_samples, start + len(buf))
        gain = (note.velocity / 127.0) ** 1.3
        pan = float(np.clip(note.params.get("pan", 0.0), -1.0, 1.0))
        theta = (pan + 1.0) * np.pi / 4.0
        seg = buf[: end - start] * gain
        out[start:end, 0] += seg * (np.cos(theta) * np.sqrt(2.0))
        out[start:end, 1] += seg * (np.sin(theta) * np.sqrt(2.0))
    return out


def render_song_audio(song, sample_rate: int = DEFAULTS["sample_rate"], progress=None) -> np.ndarray:
    """Synthesize and mix a whole song. Returns a stereo float32 array in [-1, 1]."""
    preset = get_preset(song.style)
    spb = 60.0 / song.bpm
    n = int((song.arrangement.total_beats * spb + preset.reverb_size + 1.0) * sample_rate)
    overrides = {}
    lead_mix = get_mix("lead")
    overrides["lead"] = replace(lead_mix,
                                reverb_send=lead_mix.reverb_send if preset.lead_reverb else 0.08,
                                delay_send=lead_mix.delay_send if preset.lead_delay else 0.0)
    if not preset.bass_sidechain:
        overrides["bass"] = replace(get_mix("bass"), sidechain=0.0)
    mixer = Mixer(intensity=song.intensity, sample_rate=sample_rate, bpm=song.bpm,
                  reverb_size=preset.reverb_size, delay_feedback=preset.delay_feedback, overrides=overrides)

    kick_times = []
    for t in song.tracks:
        if t.instrument == "kick":
            kick_times.extend(nt.start * spb for nt in t.notes)
    duck = mixer.sidechain_curve(kick_times, n) if kick_times else None

    master = np.zeros((n, 2), dtype=np.float32)
    reverb_bus = np.zeros(n, dtype=np.float32)
    delay_bus = np.zeros(n, dtype=np.float32)
    for i, track in enumerate(song.tracks):
        if progress:
            progress(f"Rendering {track.name}", i / (len(song.tracks) + 1))
        stereo = render_track(track, song.bpm, sample_rate, n, preset)
        dry, rev, dly = mixer.process_track(track.name, stereo, duck)
        master += dry
        reverb_bus += rev
        delay_bus += dly
        del stereo, dry

    if progress:
        progress("Mixing", len(song.tracks) / (len(song.tracks) + 1))
    delayed = mixer.delay(delay_bus)
    master += delayed
    reverb_bus += delayed.mean(axis=1) * 0.5
    del delayed
    wet = mixer.reverb(reverb_bus, seed=song.seed % (2**32))
    del reverb_bus, delay_bus
    if duck is not None:   # pump the reverb tail with the kick as well
        wet *= (1.0 - np.float32(0.5) * duck)[:, None]
    master += wet
    del wet
    return mixer.master(master)


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def write_wav(audio: np.ndarray, path, sample_rate: int = DEFAULTS["sample_rate"],
              bit_depth: int = DEFAULTS["bit_depth"]) -> str:
    """Write a float stereo/mono array as 16- or 24-bit PCM WAV."""
    if bit_depth not in (16, 24):
        raise ValueError("bit_depth must be 16 or 24")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(audio)
    if data.ndim == 1:
        data = data[:, None]
    scale = 32767 if bit_depth == 16 else 8388607
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(data.shape[1])
        wf.setsampwidth(bit_depth // 8)
        wf.setframerate(sample_rate)
        for s0 in range(0, len(data), 1 << 18):   # chunked -> low memory for long tracks
            chunk = np.clip(data[s0: s0 + (1 << 18)].astype(np.float64), -1.0, 1.0)
            ints = np.round(chunk * scale).astype("<i4")
            if bit_depth == 16:
                frames = ints.astype("<i2").tobytes()
            else:
                flat = ints.reshape(-1)
                frames = np.stack([flat & 0xFF, (flat >> 8) & 0xFF, (flat >> 16) & 0xFF],
                                  axis=1).astype(np.uint8).tobytes()
            wf.writeframes(frames)
    return str(path)


def wav_to_mp3(wav_path, mp3_path=None, bitrate: str = "320k") -> str:
    """Convert WAV to MP3 with ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("MP3 export needs ffmpeg on your PATH (e.g. `sudo apt install ffmpeg`).")
    wav_path = Path(wav_path)
    mp3_path = Path(mp3_path) if mp3_path else wav_path.with_suffix(".mp3")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-b:a", bitrate, str(mp3_path)],
                   check=True)
    return str(mp3_path)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class AudioGenerator:
    def __init__(
        self,
        soundfont_path: Optional[str] = None,
        sample_rate: int = DEFAULTS["sample_rate"],
        bit_depth: int = DEFAULTS["bit_depth"],
        renderer: str = "auto",
    ):
        if renderer not in RENDERERS:
            raise ValueError(f"renderer must be one of {RENDERERS}")
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.renderer = renderer
        self.soundfont_path = soundfont_path or self._find_default_soundfont()

    @staticmethod
    def _find_default_soundfont() -> Optional[str]:
        """Try to find a common SoundFont on the system."""
        common_paths = [
            "/usr/share/sounds/sf2/FluidR3_GM.sf2",
            "/usr/share/soundfonts/FluidR3_GM.sf2",
            "/usr/share/soundfonts/default.sf2",
            "soundfonts/FluidR3_GM.sf2",
            "FluidR3_GM.sf2",
        ]
        for path in common_paths:
            if Path(path).exists():
                return path
        return None

    @property
    def fluidsynth_ready(self) -> bool:
        if not self.soundfont_path:
            return False
        try:
            import midi2audio  # noqa: F401
            return True
        except ImportError:
            return shutil.which("fluidsynth") is not None

    def _default_output(self, stem: str, suffix: str) -> Path:
        output_dir = Path(OUTPUT["audio_folder"])
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{stem}{suffix}"

    def render_midi_to_wav(self, midi_path, output_path=None, gain: float = 0.7) -> str:
        """Render a MIDI file to WAV with FluidSynth + a SoundFont. Returns the WAV path."""
        midi_path = Path(midi_path)
        if not midi_path.exists():
            raise FileNotFoundError(f"MIDI file not found: {midi_path}")
        output_path = Path(output_path) if output_path else self._default_output(midi_path.stem, ".wav")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.soundfont_path or not Path(self.soundfont_path).exists():
            raise RuntimeError("No SoundFont (.sf2) found. Pass soundfont_path=... or use the built-in renderer.")
        try:
            from midi2audio import FluidSynth as Midi2AudioFS
            Midi2AudioFS(sound_font=self.soundfont_path, sample_rate=self.sample_rate).midi_to_audio(
                str(midi_path), str(output_path))
            return str(output_path)
        except ImportError:
            pass
        exe = shutil.which("fluidsynth")
        if not exe:
            raise RuntimeError("FluidSynth is not available. Install the fluidsynth program "
                               "(and optionally `pip install midi2audio`), or use the built-in renderer.")
        subprocess.run([exe, "-ni", "-g", str(gain), "-F", str(output_path), "-r", str(self.sample_rate),
                        str(self.soundfont_path), str(midi_path)], check=True, capture_output=True)
        return str(output_path)

    def render_song(self, song, output_path=None, progress=None) -> str:
        """Render a generated song with the built-in synthesizer + mixer to WAV."""
        output_path = Path(output_path) if output_path else self._default_output(song.title, ".wav")
        audio = render_song_audio(song, self.sample_rate, progress=progress)
        return write_wav(audio, output_path, self.sample_rate, self.bit_depth)

    def render(self, midi_path=None, output_format: str = "wav", output_path=None, song=None, progress=None) -> str:
        """
        Main render method. Renders ``song`` with the built-in synth (or ``midi_path``
        with FluidSynth) to ``output_format`` ("wav" or "mp3").
        """
        fmt = output_format.lower()
        if fmt not in ("wav", "mp3"):
            raise ValueError(f"Format '{output_format}' not supported. Use 'wav' or 'mp3'.")
        target = Path(output_path) if output_path else None
        wav_target = target.with_suffix(".wav") if target else None

        use_builtin = self.renderer == "builtin" or (self.renderer == "auto" and song is not None)
        if use_builtin:
            if song is None:
                raise ValueError("The built-in renderer needs the generated song (song=...).")
            wav = self.render_song(song, wav_target, progress=progress)
        else:
            if midi_path is None:
                raise ValueError("midi_path is required for FluidSynth rendering.")
            wav = self.render_midi_to_wav(midi_path, wav_target)

        if fmt == "mp3":
            mp3 = wav_to_mp3(wav, target.with_suffix(".mp3") if target else None)
            return mp3
        return wav


# Convenience function
def render_midi(midi_file: str, output_file: Optional[str] = None) -> str:
    generator = AudioGenerator(renderer="fluidsynth")
    return generator.render(midi_file, output_path=output_file)
