# HighTrance

A program that generates original music in the styles of **Classic Goa Trance** (1994 – early 2000s) and modern **High-Tech Trance / Psytrance**.

Every track is built from scratch with procedural music theory. HighTrance contains no samples and no pre-written loops. It writes a multi-track General-MIDI file. It can also render the track to WAV or MP3 with its own NumPy/SciPy synthesizer and mixer, or with FluidSynth and a SoundFont.

## Features

- **Styles:**
  - `goa`: hypnotic, psychedelic, eastern scales, tribal percussion, long delays and reverbs.
  - `hightech`: fast, technical, sharp acid, glitchy FX, tight and aggressive.
  - `hybrid`: a blend of the two.
- **Tempo:** 138–148 BPM, chosen by you or picked automatically.
- **Length:** usually 6–9 minutes.
- **Arrangement:** the full trance energy arc. Intro → Build-up → First Drop → Breakdown → Second Build → Massive Second Drop → Outro. Section lengths are quantised to 8-bar phrases.
- **Layers:** each layer is generated independently and has its own seeded random stream:
  - **Drums:** kick, offbeat hats, claps, rides, tribal and organic percussion, ghost notes, polyrhythms, snare rolls, crashes.
  - **Bass:** a rolling 16th-note psy bassline (K-B-B-B and gallop patterns) with a sweeping filter, slight detune and sidechain.
  - **Leads:** a TB-303-style acid line (slides and accents), psychedelic leads and arpeggios.
  - **Pads:** atmospheric pads and evolving textures.
  - **FX:** risers, impacts, downlifters, zaps and bubbles.
- **Mixing:** per-track volume, panning, EQ, compression, kick sidechain, reverb and delay sends, and a master bus with glue compression and a limiter.
- **Reproducible:** the same seed and the same settings always give the same track.
- **Export:** a multi-track `.mid` file, plus optional `.wav` (16- or 24-bit) or `.mp3`.
- **Interfaces:** a CLI, a simple Tkinter GUI, and a Python API.

## Installation

```bash
pip install -r requirements.txt
```

Optional extras:

| Feature | Requirement |
|---|---|
| MP3 export | `ffmpeg` on your `PATH` (`sudo apt install ffmpeg`) |
| FluidSynth rendering | FluidSynth (`sudo apt install fluidsynth`) and a `.sf2` SoundFont, such as `FluidR3_GM.sf2` |
| GUI | Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu) |
| AI refiner (`ai/refiner.py`, off by default) | `pip install torch audiocraft`, then set `AI["enabled"] = True` in `config/settings.py` |

The built-in synthesizer needs only NumPy and SciPy, so WAV rendering works without FluidSynth.

## Usage

```bash
# MIDI only (fast, about 1 s)
python main.py --style goa --bpm 145 --key F#m --seed 1234

# MIDI and WAV, rendered with the built-in synth
python main.py --style hightech --length 7 --seed 42 --render-audio

# GUI
python main.py --gui
```

`main.py` options: `--style {goa,hightech,hybrid}`, `--bpm`, `--length` (minutes), `--key` (for example `Am`, `F#m`, `Dm`), `--seed`, `--intensity {0.5…1.0}`, `--output`, `--render-audio`, `--gui`.

The extended CLI adds `auto` values, scale selection, MP3 and renderer choice:

```bash
python -m ui.cli --style goa --bpm auto --length auto --key auto --seed 7 \
                 --scale phrygian_dominant --render-audio --format mp3
python -m ui.cli --render-audio --renderer fluidsynth --soundfont /path/to/FluidR3_GM.sf2
```

The available scales are `minor`, `harmonic_minor`, `phrygian`, `phrygian_dominant`, `double_harmonic`, `hungarian_minor`, `dorian`, `locrian`, `mixolydian` and `major`.

Output files go to `output/midi/` and `output/audio/`. Both folders are ignored by git.

### Python API

```python
from core.generator import TranceGenerator

gen = TranceGenerator(style="goa", bpm=144, length_minutes=7, key="Em", seed=2024, intensity=0.9)
result = gen.generate(render_audio=True)       # dict: midi_path, audio_path, sections, tracks, ...

song = gen.compose()                           # in-memory Song (tracks of notes)
song = gen.regenerate_module(song, "leads", seed=99)   # re-roll one layer only
```

## Project structure

```
main.py               entry point (CLI / GUI)
config/settings.py    defaults, styles, structure ratios, sound and mix presets
core/                 seed handling, music theory, arrangement, data model, TranceGenerator
modules/              drums, bass, leads (acid / lead / arp), pads, fx
synthesis/            MIDI engine, DSP, instruments, mixer, audio rendering
ui/                   CLI and Tkinter GUI
ai/                   optional MusicGen-based refiner
tests/                pytest test-suite
```

## Notes

- A full 7–9 minute render with the built-in synth takes about 1 minute and about 1.5 GB of RAM. To make it faster and lighter, use a lower `--sample-rate` with `python -m ui.cli`.
- The MIDI file uses General-MIDI programs (drums on channel 10), so it opens in any DAW for further production.

## Tests

```bash
python -m pytest
```
