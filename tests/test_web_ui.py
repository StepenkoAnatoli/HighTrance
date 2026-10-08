"""Tests for the Gradio web UI (design D8: docs/superpowers/specs/2026-10-08-gradio-web-ui-design.md).

Covers: build without launch, the generate_track handler contract with a
stubbed TranceGenerator (§6), a launch smoke test on an ephemeral server, and
the --web parser contract on main.py. Heavy generation stays out of pytest.
"""
import subprocess
import sys
import urllib.request
from pathlib import Path

import gradio as gr
import pytest

import ui.web as web

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          cwd=ROOT, timeout=120)


# ---------------------------------------------------------------------------
# D8(a) — build without launch
# ---------------------------------------------------------------------------

def test_build_ui_returns_blocks_without_launching():
    demo = web.build_ui()
    assert isinstance(demo, gr.Blocks)


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

    status, player, midi, audio = web.generate_track(
        "goa", 142, 4.5, "Am", "auto", 0, 0.85, "fluidsynth", "wav",
        True, True, progress=rec)

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


def test_length_out_of_range_is_friendly_and_skips_generator(monkeypatch):
    calls = _stub(monkeypatch)
    rec, _ = _progress_recorder()

    status, player, midi, audio = web.generate_track(
        "goa", 142, 9.0, "Am", "auto", 1, 0.85, "auto", "wav",
        True, True, progress=rec)

    assert "❌ Length must be between 3 and 6 minutes." in status
    assert player is None and midi is None and audio is None
    assert calls["init"] == []            # constructor never reached


def test_generator_exception_becomes_error_status(monkeypatch, capsys):
    _stub(monkeypatch, exc=RuntimeError("boom"))
    rec, _ = _progress_recorder()

    status, player, midi, audio = web.generate_track(
        "goa", 142, 4.5, "Am", "auto", 1, 0.85, "auto", "wav",
        True, True, progress=rec)

    assert status.startswith("❌") and "boom" in status
    assert player is None and midi is None and audio is None
    assert "RuntimeError: boom" in capsys.readouterr().err  # traceback to stderr


def test_errors_echoed_into_status_and_none_audio(monkeypatch, tmp_path):
    result = _result_files(
        tmp_path,
        errors=["MP3 export needs ffmpeg on your PATH.",
                "Mastering failed: too quiet (peak -25.0 dB)"])
    _stub(monkeypatch, result=result)
    rec, _ = _progress_recorder()

    status, player, midi, audio = web.generate_track(
        "goa", 142, 4.5, "Am", "auto", 1, 0.85, "auto", "mp3",
        True, True, progress=rec)

    assert "⚠️ MP3 export needs ffmpeg" in status
    assert "⚠️ Mastering failed" in status
    assert player is None and audio is None   # audio_path was None
    assert Path(midi).exists()                # MIDI survives render failure


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
