# HighTrance

A program that generates original music in the styles of **Classic Goa Trance** (1994 – early 2000s) and modern **High-Tech Trance / Psytrance**.

Every track is built from scratch with procedural music theory. HighTrance contains no samples and no pre-written loops. It writes a multi-track General-MIDI file. It can also render the track to WAV or MP3 with its own NumPy/SciPy synthesizer and mixer, or with FluidSynth and a SoundFont.

## Features

- **Styles:**
  - `goa`: hypnotic, psychedelic, eastern scales, tribal percussion, long delays and reverbs.
  - `hightech`: fast, technical, sharp acid, glitchy FX, tight and aggressive.
  - `hybrid`: a blend of the two.
- **Tempo:** 138–148 BPM, chosen by you or picked automatically.
- **Length:** 3–6 minutes.
- **Arrangement:** the full trance energy arc. Intro → Build-up → First Drop → Breakdown → Second Build → Massive Second Drop → Outro. Section lengths are quantised to 8-bar phrases.
- **Layers:** each layer is generated independently and has its own seeded random stream:
  - **Drums:** kick, offbeat hats, claps, rides, tribal and organic percussion, ghost notes, polyrhythms, snare rolls, crashes.
  - **Bass:** a rolling 16th-note psy bassline (K-B-B-B and gallop patterns) with a sweeping filter, slight detune and sidechain.
  - **Leads:** a TB-303-style acid line (slides and accents), psychedelic leads and arpeggios.
  - **Pads:** atmospheric pads and evolving textures.
  - **FX:** risers, impacts, downlifters, zaps and bubbles.
- **Mixing:** per-track volume, panning, EQ, compression, kick sidechain, reverb and delay sends, and a master bus with glue compression and a limiter.
- **Mastering:** rendered audio goes through an optional post-render mastering stage — zero-phase high-pass/EQ, mid-side stereo width, gentle bus compression, a soft-knee peak limiter and peak normalisation (skip it with `--no-master`).
- **Reproducible:** the same seed and the same settings always give the same track.
- **Export:** a multi-track `.mid` file, plus optional `.wav` (16- or 24-bit) or `.mp3`.
- **Interfaces:** a CLI, a Tkinter GUI, a Gradio browser UI, and a Python API.

## Installation

```bash
pip install -r requirements.txt
```

Optional extras:

| Feature | Requirement |
|---|---|
| MP3 export | `ffmpeg` on your `PATH` (`sudo apt install ffmpeg`) |
| FluidSynth rendering | the `fluidsynth` program (Linux: `sudo apt install fluidsynth`; Windows: official zip, see [Audio rendering](#audio-rendering)) and a `.sf2` SoundFont (see [`soundfonts/README.md`](soundfonts/README.md)) |
| GUI | Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu) |
| AI refiner (`ai/refiner.py`, off by default) | `pip install torch audiocraft`, then set `AI["enabled"] = True` in `config/settings.py` |

The built-in synthesizer needs only NumPy and SciPy, so WAV rendering works without FluidSynth.

## Usage

```bash
# MIDI only (fast, about 1 s)
python main.py --style goa --bpm 145 --key F#m --seed 1234

# MIDI and WAV, rendered with the built-in synth
python main.py --style hightech --length 4.5 --seed 42 --render-audio

# GUI
python main.py --gui
```

`main.py` options: `--style {goa,hightech,hybrid}`, `--bpm`, `--length` (minutes), `--key` (for example `Am`, `F#m`, `Dm`), `--seed`, `--intensity {0.5…1.0}`, `--output`, `--render-audio`, `--no-master`, `--gui`, `--web` (browser UI; generation flags are ignored).

The extended CLI adds `auto` values, scale selection, MP3 and renderer choice:

```bash
python -m ui.cli --style goa --bpm auto --length auto --key auto --seed 7 \
                 --scale phrygian_dominant --render-audio --format mp3
python -m ui.cli --render-audio --renderer fluidsynth
python -m ui.cli --render-audio --renderer fluidsynth --soundfont "C:\path\to\Font.sf2"
```

The available scales are `minor`, `harmonic_minor`, `phrygian`, `phrygian_dominant`, `double_harmonic`, `hungarian_minor`, `dorian`, `locrian`, `mixolydian` and `major`.

### Web UI

```bash
python main.py --web
# or: python -m ui.web
```

Opens the Gradio interface in your browser: pick the parameters, press
**Generate track**, listen in the page and download the MIDI/WAV. It binds to
`127.0.0.1` only (no share links, no telemetry) and needs `gradio` from
`requirements.txt`. The page owns its parameters — CLI generation flags
(`--style`, `--length`, `--output`, …) are ignored under `--web`. One
generation runs at a time; a second Generate click is ignored until the
current one finishes.

The page keeps the **last 10 runs** (settings, seed and outcome) in
`output/history.json` and shows them in a table below the controls; pick a row
from the **Load settings from history** dropdown and press **Load settings** to
restore that run's parameters (same seed reproduces the same track). The
**Bundle (MIDI + audio)** button zips the latest run's MIDI and audio into
`output/bundles/` for a single download. History is a log — the files
themselves stay on disk in `output/`.

Output files go to `output/midi/` and `output/audio/`. Both folders are ignored by git.

## Audio rendering

Two renderers, chosen with `--renderer` (on `python -m ui.cli`, or the renderer dropdown in the [Web UI](#web-ui)):

| Renderer | What it is |
|---|---|
| `auto` (default) | built-in NumPy/SciPy synthesizer — zero setup, always available |
| `fluidsynth` | renders the General-MIDI file through a SoundFont (real GM instruments) |
| `builtin` | force the built-in synth |

`python main.py --render-audio` always uses the built-in synth; use `python -m ui.cli`
or the Web UI for renderer choice.

### FluidSynth setup (optional)

**Windows** — no package-manager package exists, install manually:

1. Download the latest `fluidsynth-*-win10-x64-*.zip` from
   <https://github.com/FluidSynth/fluidsynth/releases> (verified with v2.6.1).
2. Extract it anywhere (e.g. `%LOCALAPPDATA%\Programs\FluidSynth`) and add the
   extracted `bin\` folder to your **user** `PATH`.
3. Open a **new** terminal (PATH changes do not apply to already-open ones) and
   check `fluidsynth --version`.

**Linux:** `sudo apt install fluidsynth`.

Then put a `.sf2` SoundFont in `soundfonts/` — download link, checksum and
details in [`soundfonts/README.md`](soundfonts/README.md) — and render:

```bash
python -m ui.cli --render-audio --renderer fluidsynth
```

The SoundFont is auto-discovered from `soundfonts/` (`GeneralUser-GS.sf2` first);
`--soundfont /path/to/Font.sf2` overrides discovery. MP3 export needs `ffmpeg`
on your `PATH` — without it the run keeps the WAV and reports ffmpeg missing.

## Review mode

Generate a track and iterate on it in place:

```bash
python -m ui.cli --style goa --length 5 --render-audio --review
```

After the render the track plays inside the terminal player —
`Space` = play/pause, `J`/`L` = seek ±10 s, `Enter` = done listening.
Type a note in plain language ("slower, but keep the energy") and the
configured LLM proposes changes to the global parameters (`bpm`,
`intensity`, `key`, `length` — the track is always 3–6 minutes). You see
the proposed diff and confirm with `y` before the song re-renders with the
**same seed**, so it stays the same track. Every session writes
`output/reviews/review-<timestamp>/history.json`.

The LLM endpoint is configured in `config/settings.py` under `REVIEW`
(default: a local Ollama server; any OpenAI-compatible API works). Without
an audio output device the mode falls back to printing the file path.

> **CPU-only machines:** `REVIEW["llm"]["timeout"]` defaults to 60 s *per
> request*, and local CPU inference regularly takes longer — every request
> would abort and you would land on the `[r]etry/[q]uit` prompt. Raise the
> value (e.g. to `900`) in `config/settings.py` before first use; a full
> round measured about 13 minutes with it set to `600`.

### Python API

```python
from core.generator import TranceGenerator

gen = TranceGenerator(style="goa", bpm=144, length_minutes=4.5, key="Em", seed=2024, intensity=0.9)
result = gen.generate(render_audio=True)       # dict: midi_path, audio_path, sections, tracks, ...

song = gen.compose()                           # in-memory Song (tracks of notes)
song = gen.regenerate_module(song, "leads", seed=99)   # re-roll one layer only
```

## Project structure

```
main.py               entry point (CLI / GUI / Web)
config/settings.py    defaults, styles, structure ratios, sound and mix presets
core/                 seed handling, music theory, arrangement, data model, TranceGenerator
modules/              drums, bass, leads (acid / lead / arp), pads, fx
synthesis/            MIDI engine, DSP, instruments, mixer, audio rendering
ui/                   CLI, Tkinter and web UI
ai/                   optional MusicGen-based refiner
tests/                pytest test-suite
```

## Notes

- A full 6-minute render with the built-in synth takes about 1 minute and about 1.5 GB of RAM. To make it faster and lighter, use a lower `--sample-rate` with `python -m ui.cli`.
- The MIDI file uses General-MIDI programs (drums on channel 10), so it opens in any DAW for further production.

## Tests

```bash
python -m pytest
```
