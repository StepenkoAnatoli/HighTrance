#!/usr/bin/env python3
"""
Goa Trance & High-Tech Trance Generator
Main entry point – supports CLI, optional Tkinter GUI and browser (web) UI.
"""

import argparse
import sys
from pathlib import Path

# Windows defaults to the local code page (e.g. cp1252), which cannot encode
# the arrows and box-drawing characters used in the output. Force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Local imports
from core.generator import TranceGenerator
from core.seed import generate_seed
from config.settings import DEFAULTS, LENGTH_LIMITS
from ui.cli import print_banner, print_summary


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate original Goa Trance / High-Tech Trance tracks",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--style",
        choices=["goa", "hightech", "hybrid"],
        default=DEFAULTS["style"],
        help="Music style"
    )
    parser.add_argument(
        "--bpm",
        type=int,
        default=DEFAULTS["bpm"],
        help="Tempo in BPM (recommended 138-148)"
    )
    parser.add_argument(
        "--length",
        type=float,
        default=DEFAULTS["length"],
        help=f"Track length in minutes ({LENGTH_LIMITS[0]:g}-{LENGTH_LIMITS[1]:g})"
    )
    parser.add_argument(
        "--key",
        type=str,
        default=DEFAULTS["key"],
        help="Musical key (e.g. Am, F#m, Dm)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (leave empty for random)"
    )
    parser.add_argument(
        "--intensity",
        type=float,
        default=DEFAULTS["intensity"],
        choices=[round(x * 0.1, 1) for x in range(5, 11)],
        help="Energy/intensity level (0.5 – 1.0)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output",
        help="Output folder for MIDI and audio files"
    )
    parser.add_argument(
        "--render-audio",
        action="store_true",
        help="Also render WAV/MP3 (built-in synth; MP3 export additionally needs ffmpeg)"
    )
    parser.add_argument(
        "--no-master",
        action="store_true",
        help="Skip the post-render mastering stage (EQ/compression/normalisation)"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch simple GUI instead of CLI"
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Interactive review loop after rendering (implies --render-audio; in-app playback)"
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the browser UI (Gradio); CLI generation flags are ignored"
    )

    args = parser.parse_args()
    if args.review and args.gui:
        parser.error("--review cannot be combined with --gui")
    if args.web and (args.gui or args.review):
        parser.error("--web cannot be combined with --gui or --review")
    return args


def main():
    args = parse_arguments()

    # Launch the browser UI if requested (CLI generation flags are ignored;
    # the web page owns its parameters — see ui/web.py)
    if args.web:
        try:
            from ui.web import launch
        except ImportError:
            print("Web UI dependencies not installed. Run: pip install -r requirements.txt")
            sys.exit(1)
        launch()
        return

    # Launch GUI if requested
    if args.gui:
        try:
            from ui.gui import launch_gui
            launch_gui()
            return
        except ImportError:
            print("GUI dependencies not installed. Falling back to CLI.")
    
    # CLI mode
    print_banner()

    # Handle seed
    seed = args.seed if args.seed is not None else generate_seed()
    
    # Create output directory
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    # Initialize generator
    generator = TranceGenerator(
        style=args.style,
        bpm=args.bpm,
        length_minutes=args.length,
        key=args.key,
        seed=seed,
        intensity=args.intensity,
        output_dir=output_path
    )

    # Generate the track
    print("\nGenerating track...")
    result = generator.generate(render_audio=args.render_audio or args.review,
                                audio_format="wav" if args.review else None,
                                master=False if args.no_master else None)

    # Show summary
    print_summary(result)

    # Interactive review loop (spec: docs/superpowers/specs/2026-10-08-human-review-design.md)
    if args.review:
        if not result.get("audio_path"):
            print("Review mode needs rendered audio, but no audio was produced.",
                  file=sys.stderr)
            sys.exit(1)
        from ui.review import ReviewSession
        session = ReviewSession(generator, result,
                                master=False if args.no_master else None,
                                final_format="wav")
        session.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nGeneration cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
