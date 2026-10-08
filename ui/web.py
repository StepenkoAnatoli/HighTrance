"""
Web UI (Gradio) for the generator.

Specs:
- docs/superpowers/specs/2026-10-08-gradio-web-ui-design.md   (step 3: the page)
- docs/superpowers/specs/2026-10-08-web-history-zip-design.md (step 4: history + bundle)

Launch with ``python main.py --web`` or ``python -m ui.web``. The page owns
its parameters: CLI generation flags (``--style`` etc.) are ignored under
``--web`` (documented contract, design D1) and files always go to ``output/``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
import zipfile
from datetime import datetime
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

# History + bundle storage live under the same CWD-relative output_dir the
# generator writes to (step-4 design D1/r14); output/ is gitignored.
HISTORY_PATH = Path("output") / "history.json"
BUNDLES_DIR = Path("output") / "bundles"
HISTORY_LIMIT = 10
HISTORY_COLUMNS = ["Time", "Style", "BPM", "Len(min)", "Key", "Scale",
                   "Seed", "Renderer", "Dur(s)", "Status"]


# ---------------------------------------------------------------------------
# History store (step-4 design D1)
# ---------------------------------------------------------------------------

def _load_history():
    """Best-effort read of ``output/history.json``; never raises (D1)."""
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]


def _save_history(entries):
    """Atomic overwrite: dump to a ``.tmp`` sibling, then ``os.replace`` (D1)."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_PATH.with_name(HISTORY_PATH.name + ".tmp")
    tmp.write_text(json.dumps(entries, indent=1, ensure_ascii=True),
                   encoding="utf-8")
    os.replace(tmp, HISTORY_PATH)


def _append_entry(entry):
    """Insert newest-first, cap at ``HISTORY_LIMIT``, persist; returns the list."""
    entries = _load_history()
    entries.insert(0, entry)
    del entries[HISTORY_LIMIT:]
    _save_history(entries)
    return entries


def _failed_entry(inputs, error):
    """A ``failed`` row built from the handler inputs alone (exception path)."""
    return {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **inputs,
            "duration_seconds": None, "generation_time": None,
            "status": "failed", "error": error,
            "midi": None, "audio": None}


def _history_grid(entries):
    """Pre-formatted (all ``str``) rows for the readonly Dataframe (D2/D6)."""
    grid = []
    for e in entries:
        bpm = f"{float(e['bpm']):g}" if e.get("bpm") is not None else ""
        length = f"{float(e['length']):g}" if e.get("length") is not None else ""
        dur = (f"{float(e['duration_seconds']):.0f}"
               if e.get("duration_seconds") is not None else "")
        grid.append([
            str(e.get("time", "")), str(e.get("style", "")), bpm, length,
            str(e.get("key", "")), str(e.get("scale", "")),
            str(e.get("seed", "")), str(e.get("renderer", "")), dur,
            str(e.get("status", "")),
        ])
    return grid


def _history_choices(entries):
    """Unique ``#N …`` strings, newest first (D2; f2′: seed-suffixed)."""
    choices = []
    for i, e in enumerate(entries, start=1):
        try:
            choices.append(
                f"#{i} {e['time']} {e['style']} {float(e['length']):g}min "
                f"{float(e['bpm']):g}bpm seed={int(e['seed'])}")
        except (KeyError, TypeError, ValueError):
            continue
    return choices


def _history_outputs_from(entries, value_index=0):
    """The ``(grid, dropdown update)`` pair for a handler return (D2/r-f1)."""
    choices = _history_choices(entries)
    value = (choices[value_index]
             if value_index is not None and choices
             and 0 <= value_index < len(choices) else None)
    return _history_grid(entries), gr.update(choices=choices, value=value)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def generate_track(style, bpm, length, key, scale, seed, intensity,
                   renderer, audio_format, render_audio, master,
                   progress=gr.Progress()):
    """Generate one track for the web UI (design §6 handler contract).

    Returns ``(status, player, midi_file, audio_file, history_df,
    history_dropdown)``; file outputs are ``None`` when there is nothing to
    show. Never raises into the event loop — unexpected exceptions are printed
    to the server's stderr first and still recorded as a ``failed`` history
    entry. The length pre-check is a form error, NOT a run: it writes no
    history row (step-4 design D1/f3).
    """
    inputs = dict(style=style, bpm=bpm, length=length, key=key, scale=scale,
                  seed=seed, intensity=intensity, renderer=renderer,
                  format=audio_format, render_audio=render_audio,
                  master=master)
    try:
        # Friendly pre-check; TranceGenerator's constructor stays authoritative.
        try:
            length = float(length)
        except (TypeError, ValueError):
            length = -1.0
        lo, hi = LENGTH_LIMITS
        if not lo <= length <= hi:
            grid, upd = _history_outputs_from(_load_history(),
                                              value_index=None)
            return (f"❌ Length must be between {lo:g} and {hi:g} minutes.",
                    None, None, None, grid, upd)

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
        errors = list(result.get("errors") or [])
        for err in errors:
            status.append(f"⚠️ {err}")

        audio = result.get("audio_path")
        audio = str(audio) if audio and Path(audio).exists() else None
        midi = result.get("midi_path")
        midi = str(midi) if midi and Path(midi).exists() else None

        # Step-4 status matrix (design §Status matrix / D6(d)).
        if not render_audio:
            entry_status = "MIDI only"
        elif audio is not None:
            entry_status = "warnings" if errors else "OK"
        else:
            entry_status = "failed"
        entry_error = errors[0] if errors else None
        if entry_status == "failed" and not errors:
            # The real generator always fills errors on a failed render; this
            # is only the defensive branch — keep status text and enum aligned.
            entry_error = "Audio was not rendered"
            status.append("⚠️ Audio was not rendered")

        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "style": result["style"],
            "bpm": float(result["bpm"]),
            "length": length,
            "key": result["key"],
            "scale": result["scale"],
            "seed": result["seed"],
            "intensity": float(intensity),
            "renderer": renderer,
            "format": audio_format,
            "render_audio": bool(render_audio),
            "master": bool(master),
            "duration_seconds": duration,
            "generation_time": float(result["generation_time"]),
            "status": entry_status,
            "error": entry_error,
            "midi": Path(midi).name if midi else None,
            "audio": Path(audio).name if audio else None,
        }
        entries = _append_entry(entry)
        grid, upd = _history_outputs_from(entries, value_index=0)
        return "\n".join(status), audio, midi, audio, grid, upd
    except Exception as e:  # noqa: BLE001 - the UI must survive anything
        traceback.print_exc()
        entries = _append_entry(_failed_entry(inputs, str(e)))
        grid, upd = _history_outputs_from(entries, value_index=0)
        return f"❌ {e}", None, None, None, grid, upd


def load_from_history(choice, style, bpm, length, key, scale, seed, intensity,
                      renderer, audio_format, render_audio, master):
    """Load a history entry's settings back into the controls (design D2).

    Returns the 11 control values + a status line. Invalid or out-of-range
    entries leave the controls untouched and report ⚠. A dropdown value that
    is not among the current choices is rejected by the component before this
    handler runs (design f1′); the reachable failure is a history file that
    shrank since the dropdown was built.
    """
    current = (style, bpm, length, key, scale, seed, intensity, renderer,
               audio_format, render_audio, master)

    def unchanged(msg):
        return (*current, f"⚠️ {msg}")

    if not choice:
        return unchanged("Choose a history entry first.")
    match = re.match(r"^#(\d+) ", str(choice))
    if not match:
        return unchanged("Not a history entry.")
    index = int(match.group(1)) - 1
    entries = _load_history()
    if not 0 <= index < len(entries):
        return unchanged(f"History entry #{index + 1} is gone (list changed).")
    entry = entries[index]
    try:
        assert entry["style"] in STYLES
        assert BPM_RANGE[0] <= float(entry["bpm"]) <= BPM_RANGE[1]
        assert LENGTH_LIMITS[0] <= float(entry["length"]) <= LENGTH_LIMITS[1]
        assert entry["key"] in COMMON_KEYS
        assert entry["scale"] in SCALES or entry["scale"] == "auto"
        assert 0 <= int(entry["seed"]) <= MAX_SEED
        assert 0.5 <= float(entry["intensity"]) <= 1.0
        assert entry["renderer"] in RENDERERS
        assert entry["format"] in ("wav", "mp3")
        assert isinstance(entry.get("render_audio"), bool)
        assert isinstance(entry.get("master"), bool)
    except (AssertionError, KeyError, TypeError, ValueError):
        return unchanged(f"History entry #{index + 1} is invalid (edited?).")
    return (entry["style"], float(entry["bpm"]), float(entry["length"]),
            entry["key"], entry["scale"], int(entry["seed"]),
            float(entry["intensity"]), entry["renderer"], entry["format"],
            bool(entry["render_audio"]), bool(entry["master"]),
            f"✅ Settings loaded from history #{index + 1} — press Generate")


def make_bundle(midi_file, audio_file):
    """Zip the latest run's MIDI (+ audio when present) into ``output/bundles/``.

    Returns ``(zip_path | None, status_note)`` and never raises — deleted
    files between runs yield a friendly note instead (design D3/r-f5). The
    button reads the live MIDI/audio component values, so no session state is
    needed (design D3/f2).
    """
    try:
        if not midi_file:
            return None, "Generate a track first — nothing to bundle yet."
        midi = Path(midi_file)
        if not midi.exists():
            return None, "MIDI file no longer on disk — generate again."
        BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = BUNDLES_DIR / f"{midi.stem}_bundle.zip"
        contents = [midi.name]
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(midi, arcname=midi.name)
            if audio_file:
                audio = Path(audio_file)
                if audio.exists():
                    zf.write(audio, arcname=audio.name)
                    contents.append(audio.name)
                else:
                    contents.append(f"(audio missing: {audio.name})")
        return str(zip_path), f"✅ Bundle ready: {zip_path.name} — " + \
            " + ".join(contents)
    except Exception as e:  # noqa: BLE001 - the UI must survive anything
        traceback.print_exc()
        return None, f"❌ Could not build bundle: {e}"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

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
                with gr.Row():
                    bundle_btn = gr.Button("📦 Bundle (MIDI + audio)")
                    bundle_download = gr.File(label="Bundle ZIP")
                bundle_status = gr.Markdown("")
        # History section — step-4 design D2.
        gr.Markdown("---\n### History")
        history_sel = gr.Dropdown(
            choices=_history_choices(_load_history()), value=None,
            label="Load settings from history")
        load_btn = gr.Button("Load settings")
        gr.Markdown("Files stay on disk in `output/` — this table is a log; "
                    "the Bundle button above covers the current run.")
        history_df = gr.Dataframe(
            headers=HISTORY_COLUMNS, value=_history_grid(_load_history()),
            datatype="str", interactive=False, wrap=True,
            label="Recent generations (last 10)")
        generate_btn.click(
            fn=generate_track,
            inputs=[style, bpm, length, key, scale, seed, intensity,
                    renderer, audio_format, render_audio, master],
            outputs=[status, player, midi_file, audio_file, history_df,
                     history_sel],
        )
        load_btn.click(
            fn=load_from_history,
            inputs=[history_sel, style, bpm, length, key, scale, seed,
                    intensity, renderer, audio_format, render_audio, master],
            outputs=[style, bpm, length, key, scale, seed, intensity,
                     renderer, audio_format, render_audio, master, status],
        )
        bundle_btn.click(
            fn=make_bundle,
            inputs=[midi_file, audio_file],
            outputs=[bundle_download, bundle_status],
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