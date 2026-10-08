"""
Web UI (Gradio) for the generator.

Spec: docs/superpowers/specs/2026-10-08-gradio-web-ui-design.md

Launch with ``python main.py --web`` or ``python -m ui.web``. The page owns
its parameters: CLI generation flags (``--style`` etc.) are ignored under
``--web`` (documented contract, design D1) and files always go to ``output/``.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Windows defaults to the local code page (e.g. cp1252), which cannot encode
# the ❌/✅ status glyphs. Force UTF-8 (same preamble as main.py / ui/cli.py).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import gradio as gr

from config.settings import (BPM_RANGE, COMMON_KEYS, DEFAULTS, LENGTH_LIMITS,
                             MASTERING, SCALES, STYLES)
from core.generator import TranceGenerator
from core.seed import MAX_SEED, generate_seed
from synthesis.audio_render import RENDERERS

_STYLE_LABELS = {"goa": "Goa", "hightech": "High-Tech", "hybrid": "Hybrid"}


def generate_track(style, bpm, length, key, scale, seed, intensity,
                   renderer, audio_format, render_audio, master,
                   progress=gr.Progress()):
    """Generate one track for the web UI (design §6 handler contract).

    Returns ``(status, player, midi_file, audio_file)``; file outputs are
    ``None`` when there is nothing to show. Never raises into the event loop —
    unexpected exceptions are printed to the server's stderr first.
    """
    try:
        # Friendly pre-check; TranceGenerator's constructor stays authoritative.
        try:
            length = float(length)
        except (TypeError, ValueError):
            length = -1.0
        lo, hi = LENGTH_LIMITS
        if not lo <= length <= hi:
            return f"❌ Length must be between {lo:g} and {hi:g} minutes.", None, None, None

        if seed in (None, 0, ""):
            seed = generate_seed()
        else:
            seed = int(seed)

        # The compose phase has no callback of its own — seed the overlay here.
        progress(0.0, desc="Generating layers…")

        generator = TranceGenerator(
            style=style, bpm=float(bpm), length_minutes=length, key=key,
            seed=seed, intensity=float(intensity),
            scale=None if scale in (None, "auto") else scale,
            renderer=renderer,
        )
        result = generator.generate(
            render_audio=bool(render_audio),
            audio_format=audio_format,
            master=bool(master),
            progress=lambda msg, frac: progress(frac, desc=msg),
        )

        duration = float(result["duration_seconds"])
        status = [
            f"✅ {result['style']} · {result['bpm']:g} BPM · {result['key']} "
            f"({result['scale']}) · {result['length_minutes']:g} min",
            f"Seed {result['seed']} — reuse it for the exact same track",
            f"Duration {int(duration // 60)}:{int(duration % 60):02d} · "
            f"generated in {result['generation_time']} s",
        ]
        if not render_audio:
            status.append("MIDI only (audio rendering off)")
        for err in result.get("errors", []):
            status.append(f"⚠️ {err}")

        audio = result.get("audio_path")
        audio = str(audio) if audio and Path(audio).exists() else None
        midi = result.get("midi_path")
        midi = str(midi) if midi and Path(midi).exists() else None
        if render_audio and audio is None and not result.get("errors"):
            status.append("⚠️ Audio was not rendered")
        return "\n".join(status), audio, midi, audio
    except Exception as e:  # noqa: BLE001 - the UI must survive anything
        traceback.print_exc()
        return f"❌ {e}", None, None, None


def build_ui() -> gr.Blocks:
    """Build the Blocks app without launching a server (design D3)."""
    style_choices = [(_STYLE_LABELS[s], s) for s in STYLES]
    with gr.Blocks(title="HighTrance — Goa / High-Tech Trance Generator",
                   analytics_enabled=False) as demo:
        gr.Markdown("# 🌀 HighTrance\nGenerate original Goa / High-Tech Trance "
                    "tracks — seed-based & reproducible.")
        with gr.Row():
            with gr.Column(scale=1):
                style = gr.Dropdown(choices=style_choices,
                                    value=DEFAULTS["style"], label="Style")
                bpm = gr.Slider(BPM_RANGE[0], BPM_RANGE[1],
                                value=DEFAULTS["bpm"], step=1, label="BPM")
                length = gr.Slider(LENGTH_LIMITS[0], LENGTH_LIMITS[1],
                                   value=DEFAULTS["length"], step=0.5,
                                   label="Length (minutes)")
                key = gr.Dropdown(choices=list(COMMON_KEYS),
                                  value=DEFAULTS["key"], label="Key")
                scale = gr.Dropdown(choices=["auto"] + sorted(SCALES),
                                    value="auto", label="Scale")
                seed = gr.Number(value=0, precision=0, maximum=MAX_SEED,
                                 label="Seed (0 = random)")
                intensity = gr.Slider(0.5, 1.0, value=DEFAULTS["intensity"],
                                      step=0.05, label="Intensity")
                renderer = gr.Dropdown(choices=list(RENDERERS), value="auto",
                                       label="Renderer")
                audio_format = gr.Dropdown(choices=["wav", "mp3"], value="wav",
                                           label="Audio format")
                render_audio = gr.Checkbox(value=True, label="Render audio")
                master = gr.Checkbox(value=bool(MASTERING["enabled"]),
                                     label="Master audio (EQ / compression / normalisation)")
                generate_btn = gr.Button("🌀 Generate track", variant="primary",
                                         size="lg")
            with gr.Column(scale=1):
                status = gr.Textbox(label="Status", lines=10, interactive=False)
                player = gr.Audio(label="Track", type="filepath")
                with gr.Row():
                    midi_file = gr.File(label="Download MIDI")
                    audio_file = gr.File(label="Download audio")
        generate_btn.click(
            fn=generate_track,
            inputs=[style, bpm, length, key, scale, seed, intensity,
                    renderer, audio_format, render_audio, master],
            outputs=[status, player, midi_file, audio_file],
        )
    return demo


def launch(inbrowser: bool = True, prevent_thread_lock: bool = False,
           server_port: int | None = None):
    """Launch the web UI bound to localhost (design D5/D6)."""
    demo = build_ui().queue(default_concurrency_limit=1)
    return demo.launch(server_name="127.0.0.1", inbrowser=inbrowser, share=False,
                       prevent_thread_lock=prevent_thread_lock,
                       server_port=server_port)


if __name__ == "__main__":
    launch()
