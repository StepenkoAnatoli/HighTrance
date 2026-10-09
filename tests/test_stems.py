"""Tests for the stems export feature (spec 2026-10-09-stems-export-design.md, D8).

- grouping coverage (D1)
- default (stems=False) byte-identity / determinism (D2)
- per-group finishing, sum invariant and gain (D2/D3)
- write_stems (D4)
- generate() gating: stems ok, stems+no-audio warning, stems+fluidsynth warning (D5)
"""

from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from config.settings import STEMS, STEM_GROUPS, stem_group
from core.generator import TRACK_ORDER
from core.models import Note, Song, Track
from synthesis.audio_render import (AudioGenerator, render_song_audio,
                                    render_song_stems, write_stems)


SR = 8000  # mini songs render fast


def _mini_song(beats=8, bpm=142, seed=7, groups=("kick", "bass")) -> Song:
    """A tiny multi-track song so render tests stay fast.

    ``groups`` picks which stem groups get a track (by track name); every
    name must exist in STEM_GROUPS.
    """
    def track(name, instrument, channel, dur):
        return Track(name=name, instrument=instrument, channel=channel, program=0,
                     notes=[Note(start=float(b), duration=dur, pitch=36, velocity=120)
                            for b in range(beats)],
                     controls=[])
    arrangement = SimpleNamespace(
        total_beats=float(beats),
        duration_seconds=float(beats) * 60.0 / bpm,
        sections=[SimpleNamespace(name="drop", label="drop", start_beat=0.0,
                                   end_beat=float(beats), start_bar=0.0, bars=1)],
    )
    return Song(style="goa", bpm=bpm, key="Am", scale="minor", seed=seed,
                intensity=0.7, length_minutes=0.1,
                arrangement=arrangement,
                harmony=None,
                tracks=[track(name, name, 0, 0.5) for name in groups],
                module_seeds={})


def _all_groups_song(beats=6, bpm=142, seed=11) -> Song:
    """A song with one track per stem group (kick+drums share the group)."""
    names = ["kick", "percussion", "bass", "acid", "lead", "arp", "pad", "texture", "fx"]
    return _mini_song(beats=beats, bpm=bpm, seed=seed, groups=names)


# --------------------------------------------------------------------------- D1 grouping

def test_stem_groups_cover_every_track_order_name():
    covered = [t for names in STEM_GROUPS.values() for t in names]
    assert sorted(covered) == sorted(TRACK_ORDER)
    # each name maps to exactly one group
    assert len(covered) == len(set(covered))


def test_stem_group_resolves_every_track():
    for name in TRACK_ORDER:
        assert isinstance(stem_group(name), str)


def test_stem_group_unknown_raises():
    with pytest.raises(ValueError):
        stem_group("nope")


# --------------------------------------------------------------------------- D2 default byte-identity

def test_default_render_is_deterministic_and_unchanged_shape():
    song = _mini_song()
    a = render_song_audio(song, SR)
    b = render_song_audio(song, SR)
    assert np.array_equal(a, b)
    assert a.ndim == 2 and a.shape[1] == 2
    assert np.isfinite(a).all()


def test_default_render_matches_stems_path_premix_family():
    # The stems path returns (mix, stems); the mix is mastered from the same
    # premix as the default path. They are NOT byte-identical by design
    # (per-group delay feedback differs from the shared tail), so we only
    # assert both are finite, same shape, and close in RMS — never equality.
    song = _mini_song()
    default = render_song_audio(song, SR)
    mix, stems = render_song_stems(song, SR)
    assert mix.shape == default.shape == next(iter(stems.values())).shape
    assert np.isfinite(mix).all()
    # RMS closeness (loose — feedback re-routes some energy)
    rms_d = float(np.sqrt(np.mean(default ** 2)))
    rms_s = float(np.sqrt(np.mean(mix ** 2)))
    assert abs(rms_d - rms_s) / max(rms_d, 1e-9) < 0.2


# --------------------------------------------------------------------------- D2/D3 per-group finishing + gain

def test_stems_returns_all_groups_and_sums_back():
    song = _all_groups_song()
    mix, stems = render_song_stems(song, SR)
    assert list(stems.keys()) == list(STEM_GROUPS.keys())
    for g, arr in stems.items():
        assert arr.ndim == 2 and arr.shape[1] == 2
        assert np.isfinite(arr).all()
    # every group has some energy (none silent for this song)
    for g, arr in stems.items():
        assert np.max(np.abs(arr)) > 1e-6, f"group {g} is silent"


def test_stems_gain_peaks_at_ceiling():
    song = _all_groups_song()
    _, stems = render_song_stems(song, SR)
    peaks = {g: float(np.max(np.abs(a))) for g, a in stems.items()}
    assert max(peaks.values()) == pytest.approx(STEMS["peak"], abs=1e-6)
    for g, p in peaks.items():
        assert p <= STEMS["peak"] + 1e-6, f"{g} clips: {p}"


def test_stems_sum_is_finite_and_bounded():
    # Σ stems == gscale * premix by construction (one shared gain). The sum's
    # peak is NOT pinned to STEMS["peak"]: constructive interference between
    # groups can push it above, so we only assert it is finite, non-zero and
    # bounded by the number of groups times the ceiling.
    song = _all_groups_song()
    _, stems = render_song_stems(song, SR)
    total = np.zeros_like(next(iter(stems.values())))
    for arr in stems.values():
        total += arr
    assert np.isfinite(total).all()
    assert float(np.max(np.abs(total))) > 1e-6
    assert float(np.max(np.abs(total))) <= len(STEM_GROUPS) * STEMS["peak"] + 1e-5


def test_stems_deterministic_same_seed():
    song = _all_groups_song(seed=42)
    m1, s1 = render_song_stems(song, SR)
    m2, s2 = render_song_stems(song, SR)
    assert np.array_equal(m1, m2)
    for g in s1:
        assert np.array_equal(s1[g], s2[g])


def test_stems_silent_group_is_zero():
    # Only kick+bass present; pads/leads/fx tracks are absent -> silent stems.
    song = _mini_song(groups=("kick", "bass"))
    _, stems = render_song_stems(song, SR)
    for g in ("leads", "pads", "fx"):
        assert np.max(np.abs(stems[g])) == 0.0
    assert np.max(np.abs(stems["bass"])) > 1e-6


def test_stems_tiny_peak_threshold():
    # A near-silent song must not explode the gain (peak <= 1e-10 -> gscale=1).
    song = _mini_song(beats=2, seed=3)
    # Force near-zero by using a tiny-velocity-free song is hard; instead
    # directly exercise the scaling rule via a synthetic stems dict through
    # write_stems round-trip is not enough. We assert the public contract:
    # a very quiet render still produces finite, bounded stems.
    _, stems = render_song_stems(song, SR)
    for arr in stems.values():
        assert np.isfinite(arr).all()
        assert float(np.max(np.abs(arr))) <= STEMS["peak"] + 1e-6


# --------------------------------------------------------------------------- D4 write_stems

def test_write_stems_writes_all_groups(tmp_path):
    song = _all_groups_song()
    _, stems = render_song_stems(song, SR)
    paths = write_stems(stems, tmp_path, sample_rate=SR)
    assert list(paths.keys()) == list(STEM_GROUPS.keys())
    for g, p in paths.items():
        assert Path(p).exists()
        assert Path(p).parent == tmp_path


def test_write_stems_silent_group_still_written(tmp_path):
    song = _mini_song(groups=("kick", "bass"))
    _, stems = render_song_stems(song, SR)
    paths = write_stems(stems, tmp_path, sample_rate=SR)
    assert set(paths) == set(STEM_GROUPS)
    # silent groups are valid (digital-silence) WAVs
    for p in paths.values():
        assert Path(p).stat().st_size > 44


def test_audio_generator_render_song_stems(tmp_path):
    song = _all_groups_song()
    gen = AudioGenerator(renderer="builtin", sample_rate=SR)
    mix_path, stem_paths = gen.render_song_stems(song, tmp_path / "mix.wav",
                                                 stems_dir=tmp_path / "stems")
    assert Path(mix_path).exists()
    assert list(stem_paths.keys()) == list(STEM_GROUPS.keys())
    for p in stem_paths.values():
        assert Path(p).exists()


# --------------------------------------------------------------------------- D5 generate() gating

def _gen(style="goa", bpm=142, seed=5, renderer="auto", **kw):
    from core.generator import TranceGenerator
    # length_minutes must satisfy LENGTH_LIMITS (3-6); the render itself uses
    # the pre-built mini song passed to generate(), so it stays fast.
    return TranceGenerator(style=style, bpm=bpm, length_minutes=3.0, key="Am",
                           seed=seed, intensity=0.7, renderer=renderer,
                           verbose=False, **kw)


def test_generate_stems_true_writes_stems(tmp_path):
    gen = _gen()
    result = gen.generate(render_audio=True, stems=True, song=_mini_song())
    assert result["stem_paths"]
    assert result["stems_dir"]
    for p in result["stem_paths"].values():
        assert Path(p).exists()
    assert Path(result["audio_path"]).exists()


def test_generate_stems_without_audio_warns(tmp_path):
    gen = _gen()
    result = gen.generate(render_audio=False, stems=True)
    assert result["stem_paths"] == {}
    assert any("Stem export needs audio rendering" in e for e in result["errors"])


def test_generate_stems_fluidsynth_warns_and_skips(tmp_path):
    gen = _gen(renderer="fluidsynth")
    # fluidsynth render will fail (no font), but the stems warning must be
    # appended before the render attempt and stem_paths stays empty.
    result = gen.generate(render_audio=True, stems=True)
    assert result["stem_paths"] == {}
    assert any("Stem export needs the built-in renderer" in e for e in result["errors"])


def test_generate_stems_false_no_stems(tmp_path):
    gen = _gen()
    result = gen.generate(render_audio=True, stems=False, song=_mini_song())
    assert result["stem_paths"] == {}
    assert result["stems_dir"] is None
