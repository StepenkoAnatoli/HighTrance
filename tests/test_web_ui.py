"""Tests for the Gradio web UI.

Covers: build without launch, the generate_track handler contract with a
stubbed TranceGenerator (design §6), history + bundle behavior (step-4 design
D6), a launch smoke test on an ephemeral server, and the --web parser contract
on main.py. Heavy generation stays out of pytest.
"""
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import gradio as gr
import pytest

import ui.web as web

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          cwd=ROOT, timeout=120)


@pytest.fixture(autouse=True)
def _history_store_to_tmp(tmp_path, monkeypatch):
    """Every test writes history/bundles under tmp_path, never real output/."""
    monkeypatch.setattr(web, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(web, "BUNDLES_DIR", tmp_path / "bundles")


def _entry(**over):
    """A complete, valid history entry (step-4 D1 schema)."""
    entry = {"time": "2026-10-08 22:15:03", "style": "goa", "bpm": 142.0,
             "length": 4.5, "key": "Am", "scale": "minor", "seed": 777,
             "intensity": 0.85, "renderer": "fluidsynth", "format": "wav",
             "render_audio": True, "master": True, "stems": False,
             "duration_seconds": 269.0,
             "generation_time": 12.3, "status": "OK", "error": None,
             "midi": "track.mid", "audio": "track.wav"}
    entry.update(over)
    return entry


# ---------------------------------------------------------------------------
# D8(a) / D6(f) — build without launch
# ---------------------------------------------------------------------------

def test_build_ui_returns_blocks_without_launching():
    demo = web.build_ui()
    assert isinstance(demo, gr.Blocks)


def test_build_ui_includes_history_and_bundle_components():
    demo = web.build_ui()
    labels = sorted(label for c in demo.blocks.values()
                    if (label := getattr(c, "label", None)))
    joined = "\n".join(labels)
    assert "Load settings from history" in joined
    assert "Recent generations (last 10)" in joined
    assert "Bundle ZIP" in joined


# ---------------------------------------------------------------------------
# D8(b) — handler contract with a stubbed generator
# ---------------------------------------------------------------------------

def _stub(monkeypatch, *, result=None, exc=None, seed=777):
    """Replace TranceGenerator with a recording stub; returns the call log."""
    calls = {"init": [], "generate": []}

    class Stub:
        def __init__(self, **kwargs):
            calls["init"].append(kwargs)

        def generate(self, **kwargs):
            calls["generate"].append(kwargs)
            if exc is not None:
                raise exc
            return dict(result or {})

    monkeypatch.setattr(web, "TranceGenerator", Stub)
    monkeypatch.setattr(web, "generate_seed", lambda: seed)
    return calls


def _result_files(tmp_path, **over):
    """A result dict whose midi_path exists on disk."""
    mid = tmp_path / "track.mid"
    mid.write_bytes(b"MThd-test")
    r = dict(style="goa", bpm=142, key="Am", scale="minor", seed=777,
             length_minutes=4.5, duration_seconds=269.0, midi_path=str(mid),
             audio_path=None, errors=[], generation_time=12.3)
    r.update(over)
    return r


def _progress_recorder():
    calls = []

    def rec(x, desc=None):
        calls.append((x, desc))

    return rec, calls


def test_param_mapping_and_seed_zero_randomised(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, result=_result_files(tmp_path))
    rec, prog_calls = _progress_recorder()

    status, player, midi, audio, stems_files, grid, upd = web.generate_track(
        "goa", 142, 4.5, "Am", "auto", 0, 0.85, "fluidsynth", "wav",
        True, True, False, progress=rec)

    init = calls["init"][0]
    assert init["style"] == "goa" and init["bpm"] == 142
    assert init["length_minutes"] == 4.5 and init["key"] == "Am"
    assert init["intensity"] == 0.85
    assert init["scale"] is None          # "auto" -> None
    assert init["renderer"] == "fluidsynth"
    assert init["seed"] == 777            # seed 0 -> generate_seed()

    gen = calls["generate"][0]
    assert gen["render_audio"] is True
    assert gen["audio_format"] == "wav"   # format goes to generate(), not ctor
    assert gen["master"] is True          # explicit bool, never None
    assert callable(gen["progress"])
    # the pre-compose overlay fires, and the adapter maps (msg, frac) -> progress
    assert prog_calls[0] == (0.0, "Generating layers…")
    gen["progress"]("Rendering kick", 0.5)
    assert prog_calls[-1] == (0.5, "Rendering kick")

    # no audio rendered -> player/audio None, MIDI still offered
    assert player is None and audio is None
    assert Path(midi).exists()
    assert "Seed 777" in status

    # step-4: a history row is recorded (defensive 'failed', audio_path None)
    entry = web._load_history()[0]
    assert entry["status"] == "failed"
    assert entry["error"] == "Audio was not rendered"
    assert entry["midi"] == "track.mid" and entry["audio"] is None
    assert entry["seed"] == 777 and entry["scale"] == "minor"
    assert grid[0][9] == "failed"
    assert upd["choices"][0].startswith("#1 ") and "seed=777" in upd["choices"][0]
    assert upd["value"] == upd["choices"][0]


def test_length_out_of_range_is_friendly_and_skips_generator(monkeypatch):
    calls = _stub(monkeypatch)
    rec, _ = _progress_recorder()

    status, player, midi, audio, stems_files, grid, upd = web.generate_track(
        "goa", 142, 9.0, "Am", "auto", 1, 0.85, "auto", "wav",
        True, True, False, progress=rec)

    assert "❌ Length must be between 3 and 6 minutes." in status
    assert player is None and midi is None and audio is None
    assert calls["init"] == []            # constructor never reached
    assert web._load_history() == []      # a form error is NOT a run (D1/f3)
    assert upd["choices"] == [] and upd["value"] is None


def test_generator_exception_becomes_error_status(monkeypatch, capsys):
    _stub(monkeypatch, exc=RuntimeError("boom"))
    rec, _ = _progress_recorder()

    status, player, midi, audio, stems_files, grid, upd = web.generate_track(
        "goa", 142, 4.5, "Am", "auto", 1, 0.85, "auto", "wav",
        True, True, False, progress=rec)

    assert status.startswith("❌") and "boom" in status
    assert player is None and midi is None and audio is None
    assert "RuntimeError: boom" in capsys.readouterr().err  # traceback to stderr
    entry = web._load_history()[0]
    assert entry["status"] == "failed" and entry["error"] == "boom"
    assert entry["duration_seconds"] is None and entry["midi"] is None
    assert entry["audio"] is None and entry["generation_time"] is None
    assert grid[0][9] == "failed"


def test_errors_echoed_into_status_and_none_audio(monkeypatch, tmp_path):
    result = _result_files(
        tmp_path,
        errors=["MP3 export needs ffmpeg on your PATH.",
                "Mastering failed: too quiet (peak -25.0 dB)"])
    _stub(monkeypatch, result=result)
    rec, _ = _progress_recorder()

    status, player, midi, audio, stems_files, grid, upd = web.generate_track(
        "goa", 142, 4.5, "Am", "auto", 1, 0.85, "auto", "mp3",
        True, True, False, progress=rec)

    assert "⚠️ MP3 export needs ffmpeg" in status
    assert "⚠️ Mastering failed" in status
    assert player is None and audio is None   # audio_path was None
    assert Path(midi).exists()                # MIDI survives render failure
    # matrix: render_audio=True, audio_path None, errors non-empty -> failed
    entry = web._load_history()[0]
    assert entry["status"] == "failed"
    assert entry["error"] == "MP3 export needs ffmpeg on your PATH."
    assert entry["audio"] is None and entry["midi"] == "track.mid"


# ---------------------------------------------------------------------------
# Step-4 D6(a) — history store
# ---------------------------------------------------------------------------

def test_history_append_caps_at_10_newest_first():
    for i in range(12):
        web._append_entry({"time": f"t{i}", "style": "goa", "seed": i})
    entries = web._load_history()
    assert len(entries) == web.HISTORY_LIMIT
    assert [e["time"] for e in entries] == [f"t{i}" for i in range(11, 1, -1)]


def test_history_corrupt_file_tolerated():
    web.HISTORY_PATH.write_text("not json {{{", encoding="utf-8")
    assert web._load_history() == []
    assert isinstance(web.build_ui(), gr.Blocks)   # page still builds (D7-3)


def test_history_atomic_write_leaves_valid_file():
    web._append_entry(_entry())
    assert not web.HISTORY_PATH.with_name(web.HISTORY_PATH.name + ".tmp").exists()
    assert json.loads(web.HISTORY_PATH.read_text(encoding="utf-8"))


def test_history_test_entry_schema_round_trip():
    web._append_entry(_entry())
    assert web._load_history()[0] == _entry()


def test_history_dropdown_labels_unique_same_second():
    # same time + settings, different seeds -> labels must stay unique (f2′)
    for seed in (1, 2):
        web._append_entry(_entry(seed=seed, time="2026-10-08 22:15:03"))
    labels = web._history_choices(web._load_history())
    assert len(labels) == len(set(labels))
    assert labels[0].startswith("#1 ") and labels[1].startswith("#2 ")


def test_history_grid_is_all_strings():
    web._append_entry(_entry(duration_seconds=269.4))
    grid = web._history_grid(web._load_history())
    assert all(isinstance(cell, str) for cell in grid[0])
    assert grid[0][8] == "269" and grid[0][9] == "OK"
    assert web._history_grid([]) == []


# ---------------------------------------------------------------------------
# Step-4 D6(b) — bundle zip
# ---------------------------------------------------------------------------

def test_bundle_zip_contains_midi_and_audio():
    mid = web.BUNDLES_DIR.parent / "song.mid"
    mid.parent.mkdir(parents=True, exist_ok=True)
    wav = web.BUNDLES_DIR.parent / "song.wav"
    mid.write_bytes(b"MThd")
    wav.write_bytes(b"WAV")
    zip_path, note = web.make_bundle(str(mid), str(wav))
    assert zip_path and Path(zip_path).exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == ["song.mid", "song.wav"]
    assert "Bundle ready" in note


def test_bundle_midi_only():
    mid = web.BUNDLES_DIR.parent / "song.mid"
    mid.parent.mkdir(parents=True, exist_ok=True)
    mid.write_bytes(b"MThd")
    zip_path, note = web.make_bundle(str(mid), None)
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == ["song.mid"]
    assert "song.mid" in note


def test_bundle_missing_midi_is_friendly_not_raise():
    mid = web.BUNDLES_DIR.parent / "gone.mid"
    zip_path, note = web.make_bundle(str(mid), None)
    assert zip_path is None
    assert "no longer on disk" in note


def test_bundle_no_run_yet_is_friendly():
    zip_path, note = web.make_bundle(None, None)
    assert zip_path is None
    assert "Generate a track first" in note


def test_bundle_zip_includes_stems_under_stems_prefix():
    mid = web.BUNDLES_DIR.parent / "song.mid"
    mid.parent.mkdir(parents=True, exist_ok=True)
    mid.write_bytes(b"MThd")
    stem = web.BUNDLES_DIR.parent / "drums.wav"
    stem.write_bytes(b"WAV")
    zip_path, note = web.make_bundle(str(mid), None, [str(stem)])
    assert zip_path and Path(zip_path).exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == ["song.mid", "stems/drums.wav"]
    assert "stems/drums.wav" in note


def test_bundle_missing_stem_is_noted_not_fatal():
    mid = web.BUNDLES_DIR.parent / "song.mid"
    mid.parent.mkdir(parents=True, exist_ok=True)
    mid.write_bytes(b"MThd")
    zip_path, note = web.make_bundle(str(mid), None, [str(web.BUNDLES_DIR.parent / "gone.wav")])
    assert zip_path and Path(zip_path).exists()
    assert "stem missing" in note


# ---------------------------------------------------------------------------
# Step-4 D6(c) — load settings from history
# ---------------------------------------------------------------------------

_CURRENT = ("goa", 142.0, 4.5, "Am", "minor", 5, 0.85, "fluidsynth", "wav",
            True, False, False)


def test_load_from_history_round_trip():
    web._save_history([_entry()])
    label = web._history_choices(web._load_history())[0]
    style, bpm, length, key, scale, seed, intensity, renderer, fmt, \
        render_audio, master, stems, note = web.load_from_history(label, *_CURRENT)
    assert (style, bpm, length, key, scale, seed, intensity, renderer,
            fmt, render_audio, master, stems) == ("goa", 142.0, 4.5, "Am", "minor",
                                                   777, 0.85, "fluidsynth", "wav",
                                                   True, True, False)
    assert note.startswith("✅") and "#1" in note


def test_load_from_history_scale_auto_round_trip():
    web._save_history([_entry(scale="auto", seed=3)])
    label = web._history_choices(web._load_history())[0]
    out = web.load_from_history(label, *_CURRENT)
    assert out[4] == "auto" and out[5] == 3
    assert out[-1].startswith("✅")


def test_load_from_history_out_of_range_keeps_controls():
    # dropdown was built from 3 entries; the file now holds 1 -> stale #3
    web._save_history([_entry(seed=1)])
    stale = "#3 2026-10-08 22:15:03 goa 4.5min 142bpm seed=1"
    out = web.load_from_history(stale, *_CURRENT)
    assert out[-1].startswith("⚠️") and "gone" in out[-1]
    assert out[:-1] == _CURRENT          # controls untouched


def test_load_from_history_invalid_entry_keeps_controls():
    entry = _entry(bpm=999999.0)          # out of BPM_RANGE
    web._save_history([entry])
    label = web._history_choices([entry])[0]
    out = web.load_from_history(label, *_CURRENT)
    assert out[-1].startswith("⚠️") and "invalid" in out[-1]
    assert out[:-1] == _CURRENT


def test_load_from_history_no_choice():
    out = web.load_from_history("", *_CURRENT)
    assert out[-1].startswith("⚠️") and "first" in out[-1]


# ---------------------------------------------------------------------------
# Step-4 D6(d) — handler history integration + status matrix
# ---------------------------------------------------------------------------

def test_handler_records_ok_entry(monkeypatch, tmp_path):
    wav = tmp_path / "track.wav"
    wav.write_bytes(b"WAV")
    _stub(monkeypatch, result=_result_files(tmp_path, audio_path=str(wav)))
    rec, _ = _progress_recorder()

    status, player, midi, audio, stems_files, grid, upd = web.generate_track(
        "goa", 142, 4.5, "Am", "minor", 777, 0.85, "fluidsynth", "wav",
        True, True, False, progress=rec)

    assert player == str(wav) and audio == str(wav) and Path(midi).exists()
    entry = web._load_history()[0]
    assert entry["status"] == "OK" and entry["error"] is None
    assert entry["midi"] == "track.mid" and entry["audio"] == "track.wav"
    assert entry["scale"] == "minor" and entry["format"] == "wav"
    assert grid[0][9] == "OK"
    assert upd["choices"][0].startswith("#1 ") and "seed=777" in upd["choices"][0]
    assert upd["value"] == upd["choices"][0]


def test_handler_records_midi_only(monkeypatch, tmp_path):
    _stub(monkeypatch, result=_result_files(tmp_path))
    rec, _ = _progress_recorder()

    status, *_ = web.generate_track(
        "goa", 142, 4.5, "Am", "auto", 777, 0.85, "auto", "wav",
        False, True, False, progress=rec)

    assert "MIDI only" in status
    entry = web._load_history()[0]
    assert entry["status"] == "MIDI only"
    assert entry["audio"] is None and entry["midi"] == "track.mid"


def test_handler_records_warnings_when_audio_kept(monkeypatch, tmp_path):
    wav = tmp_path / "track.wav"
    wav.write_bytes(b"WAV")
    result = _result_files(tmp_path, audio_path=str(wav),
                           errors=["Mastering failed: too quiet"])
    _stub(monkeypatch, result=result)
    rec, _ = _progress_recorder()

    web.generate_track("goa", 142, 4.5, "Am", "auto", 777, 0.85, "auto",
                       "wav", True, True, False, progress=rec)

    entry = web._load_history()[0]
    assert entry["status"] == "warnings"
    assert entry["error"] == "Mastering failed: too quiet"
    assert entry["audio"] == "track.wav"


def test_handler_mp3_requested_stores_actual_wav(monkeypatch, tmp_path):
    # mp3 requested but ffmpeg missing -> audio_path is the WAV (generator r6)
    wav = tmp_path / "track.wav"
    wav.write_bytes(b"WAV")
    result = _result_files(tmp_path, audio_path=str(wav))
    _stub(monkeypatch, result=result)
    rec, _ = _progress_recorder()

    web.generate_track("goa", 142, 4.5, "Am", "auto", 777, 0.85, "auto",
                       "mp3", True, True, False, progress=rec)

    entry = web._load_history()[0]
    assert entry["format"] == "mp3" and entry["audio"] == "track.wav"


# ---------------------------------------------------------------------------
# D8(c) — launch smoke (ephemeral port, real HTTP GET, then close)
# ---------------------------------------------------------------------------

def test_launch_smoke_serves_homepage():
    demo = web.build_ui().queue(default_concurrency_limit=1)
    _, url, _ = demo.launch(server_name="127.0.0.1", inbrowser=False, share=False,
                            prevent_thread_lock=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            assert resp.status == 200
            body = resp.read()
            assert b"gradio" in body.lower() or b"HighTrance" in body
    finally:
        demo.close()


# ---------------------------------------------------------------------------
# D8(d) — parser contract on main.py
# ---------------------------------------------------------------------------

def test_main_rejects_web_with_gui():
    proc = run(str(ROOT / "main.py"), "--web", "--gui")
    assert proc.returncode == 2
    assert "--web cannot be combined" in proc.stderr


def test_main_rejects_web_with_review():
    proc = run(str(ROOT / "main.py"), "--web", "--review")
    assert proc.returncode == 2
    assert "--web cannot be combined" in proc.stderr


def test_main_help_mentions_web():
    proc = run(str(ROOT / "main.py"), "--help")
    assert proc.returncode == 0
    assert "--web" in proc.stdout


def test_parse_arguments_accepts_web_with_generation_flags(monkeypatch):
    """--web parses alongside generation flags; main() then ignores them (D1)."""
    import main as main_module
    monkeypatch.setattr(sys, "argv",
                        ["main.py", "--web", "--style", "goa", "--length", "5.0"])
    args = main_module.parse_arguments()
    assert args.web is True
    assert args.style == "goa"
    assert args.length == 5.0