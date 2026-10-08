"""
Optional AI refinement (Path B).

Takes the procedurally generated track and asks a *local* MusicGen model
(``facebook/musicgen-melody`` via Meta's ``audiocraft``) to re-imagine an
excerpt of it with higher-fidelity audio. The rendered mix is used as melody
(chroma) conditioning, so the AI version follows the generated riffs.

Everything here is optional: the rest of the program never imports torch.
Install with ``pip install torch audiocraft`` and enable it via
``config.settings.AI["enabled"] = True`` (or call :class:`AIRefiner` directly).
Model weights are downloaded into the Hugging Face cache on first use.
"""

from __future__ import annotations

import wave
from math import isfinite
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from config.settings import AI, STYLE_LABELS

SUPPORTED_MODELS = {"musicgen": "facebook/musicgen-melody"}

STYLE_PROMPTS = {
    "goa": ("classic 1990s goa trance, hypnotic rolling 16th-note bassline, psychedelic eastern melodic "
            "lead, lush atmospheric pads, tribal percussion, analog acid squelch"),
    "hightech": ("high-tech psytrance, driving precise rolling bass, sharp tb-303 acid lines, futuristic "
                 "sound design, complex glitchy percussion, aggressive energy"),
    "hybrid": ("psychedelic trance blending classic goa melodies with modern high-tech psytrance production, "
               "rolling bass, acid lines, tribal and glitch percussion"),
}


class RefinerUnavailable(RuntimeError):
    """Raised when the optional AI dependencies are not installed."""


def build_prompt(style: str, bpm: float, key: str, scale: Optional[str] = None) -> str:
    """Text prompt describing the generated track."""
    desc = STYLE_PROMPTS.get(style, STYLE_PROMPTS["hybrid"])
    mode = f" {scale.replace('_', ' ')}" if scale else ""
    return f"{STYLE_LABELS.get(style, style)}: {desc}, {int(round(bpm))} bpm, key of {key}{mode}, instrumental"


def read_wav(path) -> Tuple[np.ndarray, int]:
    """Read a 16/24-bit PCM WAV into a float32 ``(samples, channels)`` array."""
    with wave.open(str(path), "rb") as wf:
        sr, ch, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float32) / 8388608.0
    else:
        raise ValueError("Only 16- or 24-bit PCM WAV files are supported")
    return data.reshape(-1, ch), sr


class AIRefiner:
    def __init__(self, model: str = AI["model"], device: str = AI["device"]):
        if model not in SUPPORTED_MODELS:
            raise ValueError(f"AI model {model!r} is not supported; available: {', '.join(SUPPORTED_MODELS)}")
        self.model_name = model
        self.device = device
        self._model = None

    @staticmethod
    def is_available() -> bool:
        try:
            import audiocraft  # noqa: F401
            import torch  # noqa: F401
            return True
        except ImportError:
            return False

    def _load(self):
        try:
            import torch
            from audiocraft.data.audio import audio_write
            from audiocraft.models import MusicGen
        except ImportError as e:
            raise RefinerUnavailable("AI refinement needs: pip install torch audiocraft") from e
        if self._model is None:
            self._model = MusicGen.get_pretrained(SUPPORTED_MODELS[self.model_name], device=self.device)
        return torch, self._model, audio_write

    def refine(self, audio_path, prompt: str, output_path=None, duration: float = 30.0,
               offset: Optional[float] = None) -> str:
        """Generate an AI-refined excerpt of ``audio_path``. Returns the output WAV path.

        ``offset`` (seconds) selects the excerpt; by default the middle of the track
        (usually inside the first drop / breakdown).
        """
        if duration <= 0:
            raise ValueError("duration must be positive")
        audio, sr = read_wav(audio_path)
        total = len(audio) / sr
        if offset is None:
            offset = max(0.0, total / 2 - duration / 2)
        if not isfinite(offset) or offset < 0 or offset >= total:
            raise ValueError(f"offset must be between 0 and the audio duration ({total:g} seconds)")
        torch, model, audio_write = self._load()
        seg = audio[int(offset * sr): int((offset + duration) * sr)]
        melody = torch.from_numpy(np.ascontiguousarray(seg.T)).float()[None]   # (1, channels, samples)
        model.set_generation_params(duration=min(duration, len(seg) / sr))
        out = model.generate_with_chroma([prompt], melody.to(self.device), sr)
        audio_path = Path(audio_path)
        target = Path(output_path) if output_path else audio_path.with_name(audio_path.stem + "_ai.wav")
        written = audio_write(str(target.with_suffix("")), out[0].cpu(), model.sample_rate,
                              strategy="loudness", loudness_compressor=True)
        return str(written)


def refine_track(result: dict, duration: float = 30.0) -> str:
    """Convenience: refine the audio of a ``TranceGenerator.generate`` result dict."""
    if not result.get("audio_path") or not str(result["audio_path"]).endswith(".wav"):
        raise ValueError("AI refinement needs a rendered WAV (generate with render_audio=True, format wav)")
    prompt = build_prompt(result["style"], result["bpm"], result["key"], result.get("scale"))
    return AIRefiner().refine(result["audio_path"], prompt, duration=duration)
