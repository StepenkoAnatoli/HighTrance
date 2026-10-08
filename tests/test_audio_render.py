"""Unit tests for SoundFont discovery (design D3) and the FluidSynth render
path's failure modes (design D6).

See docs/superpowers/specs/2026-10-08-fluidsynth-soundfont-design.md.
The happy-path render itself is verified outside pytest (D5 protocol) because
it depends on a system binary that pytest must never silently skip on.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

import synthesis.audio_render as ar
from synthesis.audio_render import AudioGenerator


@pytest.fixture
def fontless(tmp_path, monkeypatch):
    """Point discovery at empty temp locations so tests are hermetic.

    - module dir -> tmp_path/module_soundfonts (empty)
    - system candidates -> a path that does not exist
    - CWD -> tmp_path (empty), so no repo ``soundfonts/`` leaks in
    """
    module_dir = tmp_path / "module_soundfonts"
    module_dir.mkdir()
    monkeypatch.setattr(ar, "SOUNDFONT_DIR", module_dir)
    monkeypatch.setattr(ar, "_SYSTEM_SOUNDFONTS", (str(tmp_path / "no_such.sf2"),))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_explicit_param_wins_over_discovery(fontless):
    (ar.SOUNDFONT_DIR / "GeneralUser-GS.sf2").write_bytes(b"module")
    explicit = fontless / "explicit.sf2"
    explicit.write_bytes(b"explicit")
    gen = AudioGenerator(soundfont_path=str(explicit))
    assert gen.soundfont_path == str(explicit)


def test_module_dir_generaluser_preferred(fontless):
    (ar.SOUNDFONT_DIR / "FluidR3_GM.sf2").write_bytes(b"r3")
    (ar.SOUNDFONT_DIR / "GeneralUser-GS.sf2").write_bytes(b"gu")
    assert AudioGenerator().soundfont_path == str(ar.SOUNDFONT_DIR / "GeneralUser-GS.sf2")


def test_module_dir_fluidr3_fallback(fontless):
    (ar.SOUNDFONT_DIR / "FluidR3_GM.sf2").write_bytes(b"r3")
    assert AudioGenerator().soundfont_path == str(ar.SOUNDFONT_DIR / "FluidR3_GM.sf2")


def test_module_dir_other_sf2_sorted(fontless):
    # Neither pinned candidate present -> alphabetical first wins.
    (ar.SOUNDFONT_DIR / "zeta.sf2").write_bytes(b"z")
    (ar.SOUNDFONT_DIR / "alpha.sf2").write_bytes(b"a")
    assert AudioGenerator().soundfont_path == str(ar.SOUNDFONT_DIR / "alpha.sf2")


def test_cwd_soundfonts_fallback(fontless):
    cwd_sf = Path.cwd() / "soundfonts"
    cwd_sf.mkdir()
    (cwd_sf / "GeneralUser-GS.sf2").write_bytes(b"cwd")
    assert AudioGenerator().soundfont_path == str(cwd_sf / "GeneralUser-GS.sf2")


def test_cwd_legacy_root_fluidr3(fontless):
    legacy = Path.cwd() / "FluidR3_GM.sf2"
    legacy.write_bytes(b"legacy")
    assert AudioGenerator().soundfont_path == str(legacy)


def test_system_fallback(fontless, monkeypatch):
    system_font = fontless / "system.sf2"
    system_font.write_bytes(b"sys")
    monkeypatch.setattr(ar, "_SYSTEM_SOUNDFONTS", (str(system_font),))
    assert AudioGenerator().soundfont_path == str(system_font)


def test_no_font_found_returns_none(fontless):
    assert AudioGenerator().soundfont_path is None


def test_constants_read_at_call_time(fontless):
    # First call sees the empty state ...
    assert AudioGenerator().soundfont_path is None
    # ... dropping a font in afterwards must be picked up by the next call
    # (proves the constants are re-read, not captured at import).
    (ar.SOUNDFONT_DIR / "GeneralUser-GS.sf2").write_bytes(b"late")
    assert AudioGenerator().soundfont_path == str(ar.SOUNDFONT_DIR / "GeneralUser-GS.sf2")


# ---------------------------------------------------------------------------
# D6: render path failure modes (the happy path needs the fluidsynth binary
# and is verified by the manual E2E protocol instead of pytest)
# ---------------------------------------------------------------------------

def test_render_missing_midi_raises(fontless):
    gen = AudioGenerator(soundfont_path=str(fontless / "unused.sf2"))
    with pytest.raises(FileNotFoundError):
        gen.render_midi_to_wav(fontless / "does_not_exist.mid")


def test_render_no_soundfont_raises(fontless):
    midi = fontless / "song.mid"
    midi.write_bytes(b"MThd")
    gen = AudioGenerator(soundfont_path=None)  # discovery finds nothing (fontless)
    with pytest.raises(RuntimeError, match="SoundFont"):
        gen.render_midi_to_wav(midi)


def test_render_no_binary_raises(fontless, monkeypatch):
    midi = fontless / "song.mid"
    midi.write_bytes(b"MThd")
    sf = fontless / "f.sf2"
    sf.write_bytes(b"sf")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    gen = AudioGenerator(soundfont_path=str(sf))
    with pytest.raises(RuntimeError, match="FluidSynth is not available"):
        gen.render_midi_to_wav(midi)


def test_render_nonzero_exit_surfaces_stderr(fontless, monkeypatch):
    midi = fontless / "song.mid"
    midi.write_bytes(b"MThd")
    sf = fontless / "f.sf2"
    sf.write_bytes(b"sf")
    monkeypatch.setattr(shutil, "which", lambda name: r"C:\fake\fluidsynth.exe")
    monkeypatch.setattr(
        ar.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 255, stdout="", stderr="error: '-F' is an illegal option"),
    )
    gen = AudioGenerator(soundfont_path=str(sf))
    with pytest.raises(RuntimeError, match=r"exit 255.*illegal option"):
        gen.render_midi_to_wav(midi)


def test_render_zero_exit_without_output_raises(fontless, monkeypatch):
    """The old midi2audio wrapper exited 0-ish and ignored the missing file;
    the postcondition must catch any invocation that writes nothing."""
    midi = fontless / "song.mid"
    midi.write_bytes(b"MThd")
    sf = fontless / "f.sf2"
    sf.write_bytes(b"sf")
    monkeypatch.setattr(shutil, "which", lambda name: r"C:\fake\fluidsynth.exe")
    monkeypatch.setattr(
        ar.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""),
    )
    gen = AudioGenerator(soundfont_path=str(sf))
    with pytest.raises(RuntimeError, match="wrote no output"):
        gen.render_midi_to_wav(midi, output_path=fontless / "out.wav")
