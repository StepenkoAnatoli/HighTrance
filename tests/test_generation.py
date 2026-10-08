"""Tests for the Goa / High-Tech trance generator."""

import subprocess
import sys
import wave
from pathlib import Path

import mido
import numpy as np
import pytest

from config.settings import BPM_MAX, BPM_MIN, DEFAULT_LENGTH_RANGE, GM, STRUCTURE
from core.arrangement import build_arrangement, create_arrangement, get_section_at_beat, is_build, is_drop
from core.generator import MODULES, TranceGenerator
from core.seed import SeedManager
from core.theory import Scale, parse_key
from synthesis.audio_render import render_song_audio, write_wav
from synthesis.midi_engine import MidiEngine, song_to_midi

ROOT = Path(__file__).resolve().parent.parent
SECTION_ORDER = ["intro", "build1", "drop1", "breakdown", "build2", "drop2", "outro"]


def compose(**kw):
    kw.setdefault("verbose", False)
    return TranceGenerator(**kw).compose()


def midi_bytes(song, tmp_path, name):
    path = song_to_midi(song).save(name, tmp_path)
    return Path(path).read_bytes()


# --------------------------------------------------------------------------- theory / seed

def test_parse_key():
    assert parse_key("Am") == (9, "minor")
    assert parse_key("F#m") == (6, "minor")
    assert parse_key("Bbm") == (10, "minor")
    assert parse_key("E") == (4, "major")
    with pytest.raises(ValueError):
        parse_key("H#x")


def test_scale_pitch():
    s = Scale(4, "phrygian")          # E phrygian
    assert s.pitch(0, 4) == 64
    assert s.pitch(1, 4) == 65        # b2
    assert s.pitch(7, 4) == 76        # octave
    assert s.pitch(-1, 4) == 62


def test_seed_streams_independent_and_reproducible():
    a, b = SeedManager(5), SeedManager(5)
    assert a.rng("bass").random() == b.rng("bass").random()
    assert a.rng("bass").random() != a.rng("drums").random()


# --------------------------------------------------------------------------- arrangement

def test_arrangement_structure_and_energy_arc():
    arr = build_arrangement(145, 7.0)
    assert [s.name for s in arr.sections] == SECTION_ORDER
    assert abs(arr.duration_seconds / 60 - 7.0) < 0.5
    for prev, nxt in zip(arr.sections, arr.sections[1:]):
        assert prev.end_bar == nxt.start_bar
        assert prev.bars % 8 == 0
    by = {s.name: s for s in arr.sections}
    assert by["drop2"].energy_start >= by["drop1"].energy_end      # massive second drop
    assert by["breakdown"].energy_end < by["drop1"].energy_start
    assert not by["breakdown"].has("kick")


def test_create_arrangement_dict_api():
    arr = create_arrangement(1000, STRUCTURE)
    assert arr["sections"] == SECTION_ORDER
    assert arr["timings"]["outro"]["end"] == pytest.approx(1000, abs=0.05)
    assert get_section_at_beat(arr, 0) == "intro"
    assert is_drop("drop2") and is_build("build1")


# --------------------------------------------------------------------------- generation

@pytest.mark.parametrize("style", ["goa", "hightech", "hybrid"])
def test_all_styles_generate_all_layers(style):
    song = compose(style=style, seed=11, length_minutes=6)
    names = {t.name for t in song.tracks}
    assert {"kick", "percussion", "bass", "acid", "lead", "arp", "pad", "fx"} <= names
    for t in song.tracks:
        assert t.notes, t.name
        for n in t.notes:
            assert 0 <= n.pitch <= 127 and 1 <= n.velocity <= 127 and n.duration > 0
            assert 0 <= n.start < song.arrangement.total_beats


def test_same_seed_same_track_different_seed_different_track(tmp_path):
    a = midi_bytes(compose(style="goa", seed=123), tmp_path, "a.mid")
    b = midi_bytes(compose(style="goa", seed=123), tmp_path, "b.mid")
    c = midi_bytes(compose(style="goa", seed=124), tmp_path, "c.mid")
    assert a == b
    assert a != c


def test_auto_parameters_within_ranges():
    for seed in range(1, 15):
        g = TranceGenerator(style="hybrid", bpm=None, length_minutes=None, key=None, seed=seed, verbose=False)
        assert BPM_MIN <= g.bpm <= BPM_MAX
        assert DEFAULT_LENGTH_RANGE[0] <= g.length_minutes <= DEFAULT_LENGTH_RANGE[1]


@pytest.mark.parametrize("kwargs", [dict(bpm=120), dict(bpm=150), dict(style="techno"),
                                    dict(intensity=1.5), dict(key="X"), dict(length_minutes=0.1)])
def test_invalid_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        TranceGenerator(verbose=False, **kwargs)


def test_rolling_bass_avoids_kick_and_kick_is_four_on_floor():
    song = compose(style="goa", seed=3)
    drop = song.arrangement.by_name("drop1")
    kicks = [n.start for n in song.track("kick").notes if drop.start_beat <= n.start < drop.start_beat + 16]
    assert kicks == [drop.start_beat + i for i in range(16)]
    bass = [n for n in song.track("bass").notes if drop.start_beat <= n.start < drop.end_beat]
    assert bass
    assert all((n.start * 4) % 4 != 0 for n in bass)       # never on the beat -> K-B-B-B roll
    assert not [n for n in song.track("kick").notes
                if song.arrangement.by_name("breakdown").start_beat <= n.start
                < song.arrangement.by_name("breakdown").end_beat]


def test_notes_follow_scale():
    song = compose(style="hightech", seed=9, key="F#m")
    for name in ("bass", "lead", "pad"):
        assert all(song.scale.contains(n.pitch) for n in song.track(name).notes), name


def test_style_character_differs():
    goa = compose(style="goa", seed=21)
    tech = compose(style="hightech", seed=21)
    tribal = {GM[k] for k in ("conga_mute", "conga_open", "conga_low", "bongo_high", "bongo_low")}
    goa_tribal = sum(n.pitch in tribal for n in goa.track("percussion").notes)
    tech_tribal = sum(n.pitch in tribal for n in tech.track("percussion").notes)
    assert goa_tribal > tech_tribal
    assert len(tech.track("fx").notes) > len(goa.track("fx").notes)


def test_regenerate_single_module_keeps_others():
    gen = TranceGenerator(style="goa", seed=77, verbose=False)
    song = gen.compose()
    drums_before = [(n.start, n.pitch) for n in song.track("percussion").notes]
    bass_before = [(n.start, n.pitch) for n in song.track("bass").notes]
    gen.regenerate_module(song, "bass", seed=999)
    assert [(n.start, n.pitch) for n in song.track("percussion").notes] == drums_before
    assert [(n.start, n.pitch) for n in song.track("bass").notes] != bass_before
    assert set(MODULES) == {"drums", "bass", "leads", "pads", "fx"}


# --------------------------------------------------------------------------- MIDI

def test_midi_file_contents(tmp_path):
    song = compose(style="hightech", seed=5, bpm=146, key="Em")
    path = song_to_midi(song).save("t.mid", tmp_path)
    mid = mido.MidiFile(path)
    assert mid.type == 1
    tempos = [m.tempo for m in mid.tracks[0] if m.type == "set_tempo"]
    assert round(mido.tempo2bpm(tempos[0])) == 146
    names = [t.name for t in mid.tracks[1:]]
    assert names[:3] == ["kick", "percussion", "bass"]
    assert abs(mid.length - song.duration_seconds) < 3


def test_midi_engine_handles_overlaps_and_cc_timing(tmp_path):
    eng = MidiEngine(bpm=140)
    eng.add_notes("x", [{"note": 60, "start": 0, "duration": 2, "velocity": 100},
                        {"note": 60, "start": 1, "duration": 1, "velocity": 100}], channel=0, program=81)
    eng.add_control_change("x", 74, 64, 1.5)
    mid = mido.MidiFile(eng.save("o.mid", tmp_path))
    t, events = 0, []
    for m in mid.tracks[1]:
        t += m.time
        if m.type in ("note_on", "note_off", "control_change"):
            events.append((t, m.type))
    assert events == [(0, "note_on"), (480, "note_off"), (480, "note_on"), (720, "control_change"),
                      (960, "note_off")]
    assert eng.get_total_beats() == 2.0


# --------------------------------------------------------------------------- audio

def test_render_audio_and_wav(tmp_path):
    song = compose(style="hybrid", seed=4, length_minutes=1)
    sr = 8000
    audio = render_song_audio(song, sr)
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert np.isfinite(audio).all()
    assert 0.5 < np.abs(audio).max() <= 1.0
    assert len(audio) / sr >= song.duration_seconds
    path = write_wav(audio, tmp_path / "x.wav", sr)
    with wave.open(path) as wf:
        assert wf.getnchannels() == 2 and wf.getframerate() == sr and wf.getsampwidth() == 2


def test_generate_writes_files(tmp_path):
    gen = TranceGenerator(style="goa", seed=8, length_minutes=1, output_dir=tmp_path, sample_rate=8000,
                          verbose=False)
    result = gen.generate(render_audio=True)
    assert Path(result["midi_path"]).exists() and Path(result["midi_path"]).parent == tmp_path / "midi"
    assert Path(result["audio_path"]).exists() and Path(result["audio_path"]).parent == tmp_path / "audio"
    assert result["seed"] == 8 and not result["errors"]


def test_main_cli(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "main.py"), "--style", "hightech", "--seed", "1",
                           "--length", "1", "--bpm", "145", "--key", "F#m", "--output", str(tmp_path)],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Track summary" in proc.stdout
    assert list((tmp_path / "midi").glob("*.mid"))


def test_main_cli_rejects_bad_bpm(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "main.py"), "--bpm", "200", "--output", str(tmp_path)],
                          capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert proc.returncode == 1
    assert "BPM must be between" in proc.stdout
