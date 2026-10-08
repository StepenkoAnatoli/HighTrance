#!/usr/bin/env python3
"""
Goa Trance & High-Tech Trance Generator
Main entry point – supports both CLI and optional GUI.
"""

import argparse
import sys
from pathlib import Path

# Local imports
from core.generator import TranceGenerator
from core.seed import generate_seed
from config.settings import DEFAULTS
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
        help="Track length in minutes (6-9 recommended)"
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
        help="Also render WAV/MP3 (requires FluidSynth or similar)"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch simple GUI instead of CLI"
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

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
    result = generator.generate(render_audio=args.render_audio)

    # Show summary
    print_summary(result)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nGeneration cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
