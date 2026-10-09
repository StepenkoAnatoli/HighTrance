"""
Command-line interface helpers: banner, summary and an extended CLI
(``python -m ui.cli --help``) exposing every option of the generator.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Windows defaults to the local code page (e.g. cp1252), which cannot encode
# the arrows and box-drawing characters used in the output. Force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config.settings import (BPM_MAX, BPM_MIN, COMMON_KEYS, DEFAULTS, DEFAULT_LENGTH_RANGE, LENGTH_LIMITS,
                             SCALES, STYLE_LABELS, STYLES)

BANNER = r"""
  _   _ _       _     _____
 | | | (_) __ _| |__ |_   _| __ __ _ _ __   ___ ___
 | |_| | |/ _` | '_ \  | || '__/ _` | '_ \ / __/ _ \
 |  _  | | (_| | | | | | || | | (_| | | | | (_|  __/
 |_| |_|_|\__, |_| |_| |_||_|  \__,_|_| |_|\___\___|
          |___/   Goa Trance Generator
"""


def print_banner() -> None:
    print(BANNER)


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def print_summary(result: Dict) -> None:
    """Pretty-print the dictionary returned by ``TranceGenerator.generate``."""
    print("\n" + "=" * 60)
    print(" Track summary")
    print("=" * 60)
    print(f"  Style      : {STYLE_LABELS.get(result['style'], result['style'])}")
    print(f"  Tempo      : {result['bpm']} BPM")
    print(f"  Key/Scale  : {result['key']} ({result.get('scale', '').replace('_', ' ')})")
    print(f"  Duration   : {_fmt_time(result.get('duration_seconds', result['length_minutes'] * 60))}")
    print(f"  Seed       : {result['seed']}   (re-use it to get the exact same track)")
    if result.get("sections"):
        spb = 4 * 60.0 / float(result["bpm"])
        print("\n  Structure:")
        for label, start_bar, bars in result["sections"]:
            print(f"    {_fmt_time(start_bar * spb):>6}  {label:<22} {bars:>3} bars")
    if result.get("tracks"):
        print("\n  Tracks: " + ", ".join(f"{k} ({v})" for k, v in result["tracks"].items()))
    print(f"\n  MIDI  : {result['midi_path']}")
    if result.get("audio_path"):
        print(f"  Audio : {result['audio_path']}")
    if result.get("stem_paths"):
        stems_dir = result.get("stems_dir") or "(stems)"
        groups = ", ".join(Path(p).stem for p in result["stem_paths"].values())
        print(f"  Stems : {stems_dir}  ({groups})")
    if result.get("ai_audio_path"):
        print(f"  AI    : {result['ai_audio_path']}")
    for err in result.get("errors", []):
        print(f"  ! {err}")
    if "generation_time" in result:
        print(f"\n  Done in {result['generation_time']} s")
    print("=" * 60)


def _auto_or(cast):
    def parse(value: str):
        if value.strip().lower() in ("auto", "random"):
            return None
        return cast(value)
    return parse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ui.cli",
        description="Generate original Goa Trance tracks (extended options).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--style", choices=STYLES, default=DEFAULTS["style"], help="Music style")
    p.add_argument("--bpm", type=_auto_or(float), default=DEFAULTS["bpm"],
                   help=f"Tempo {BPM_MIN}-{BPM_MAX} or 'auto'")
    p.add_argument("--length", type=_auto_or(float), default=DEFAULTS["length"],
                   help=f"Minutes ({LENGTH_LIMITS[0]:g}-{LENGTH_LIMITS[1]:g}) or 'auto' ({DEFAULT_LENGTH_RANGE[0]:g}-{DEFAULT_LENGTH_RANGE[1]:g})")
    p.add_argument("--key", type=_auto_or(str), default=DEFAULTS["key"],
                   help=f"Key, e.g. {', '.join(COMMON_KEYS[:5])} or 'auto'")
    p.add_argument("--scale", choices=sorted(SCALES), default=None, help="Scale/mode (default: style-based)")
    p.add_argument("--intensity", type=float, default=DEFAULTS["intensity"], help="Energy 0.0-1.0")
    p.add_argument("--seed", type=int, default=None, help="Seed for reproducibility")
    p.add_argument("--output", default="output", help="Output folder")
    p.add_argument("--render-audio", action="store_true", help="Also render audio")
    p.add_argument("--stems", action="store_true",
                   help="Also export per-group stems (drums/bass/leads/pads/fx); built-in renderer only")
    p.add_argument("--review", action="store_true",
                   help="Interactive review loop after rendering (implies --render-audio; in-app playback)")
    p.add_argument("--no-master", action="store_true",
                   help="Skip the post-render mastering stage (EQ/compression/normalisation)")
    p.add_argument("--format", choices=["wav", "mp3"], default="wav", help="Audio format")
    p.add_argument("--renderer", choices=["auto", "builtin", "fluidsynth"], default="auto",
                   help="Audio engine (built-in synth or FluidSynth + SoundFont)")
    p.add_argument("--soundfont", default=None, help="SoundFont (.sf2) for FluidSynth")
    p.add_argument("--sample-rate", type=int, default=DEFAULTS["sample_rate"], help="Audio sample rate")
    p.add_argument("--gui", action="store_true", help="Launch the GUI")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.review and args.gui:
        parser.error("--review cannot be combined with --gui")
    if args.gui:
        from ui.gui import launch_gui
        launch_gui()
        return 0
    from core.generator import TranceGenerator

    print_banner()
    try:
        gen = TranceGenerator(style=args.style, bpm=args.bpm, length_minutes=args.length, key=args.key,
                              scale=args.scale, seed=args.seed, intensity=args.intensity,
                              output_dir=args.output, sample_rate=args.sample_rate,
                              audio_format=args.format, renderer=args.renderer, soundfont=args.soundfont)
        result = gen.generate(render_audio=args.render_audio or args.review or args.stems,
                              stems=args.stems,
                              audio_format="wav" if args.review else None,
                              master=False if args.no_master else None)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    print_summary(result)
    if args.review:
        if not result.get("audio_path"):
            print("Review mode needs rendered audio, but no audio was produced.",
                  file=sys.stderr)
            return 1
        from ui.review import ReviewSession
        session = ReviewSession(gen, result,
                                master=False if args.no_master else None,
                                final_format=args.format)
        session.run()
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
