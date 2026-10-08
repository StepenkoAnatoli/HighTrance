# tests/test_length_limits.py
"""Hard 3-6 minute length limits (spec D2) and the REVIEW config block."""
import subprocess
import sys
from pathlib import Path

import pytest

from config.settings import DEFAULTS, DEFAULT_LENGTH_RANGE, LENGTH_LIMITS, REVIEW
from core.generator import TranceGenerator

ROOT = Path(__file__).resolve().parents[1]


def make(**kw):
    kw.setdefault("style", "goa")
    kw.setdefault("seed", 1)
    kw.setdefault("verbose", False)
    return TranceGenerator(**kw)


def test_constants():
    assert LENGTH_LIMITS == (3.0, 6.0)
    assert DEFAULT_LENGTH_RANGE == (3.0, 6.0)
    assert LENGTH_LIMITS[0] <= DEFAULTS["length"] <= LENGTH_LIMITS[1]


def test_review_block_shape():
    assert REVIEW["llm"]["base_url"] and REVIEW["llm"]["model"]
    assert REVIEW["llm"]["temperature"] == 0.2
    assert REVIEW["history_rounds"] == 6


@pytest.mark.parametrize("value", [3.0, 4.5, 6.0])
def test_accepted_lengths(value):
    assert make(length_minutes=value).length_minutes == value


@pytest.mark.parametrize("value", [2.9, 6.1, 8.0, 0.1])
def test_rejected_lengths(value):
    with pytest.raises(ValueError, match="Length must be between"):
        make(length_minutes=value)


def test_auto_length_within_limits():
    for seed in range(5):
        g = TranceGenerator(style="goa", bpm=None, length_minutes=None, key=None,
                            seed=seed, verbose=False)
        assert DEFAULT_LENGTH_RANGE[0] <= g.length_minutes <= DEFAULT_LENGTH_RANGE[1]


def test_cli_rejects_too_long(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "main.py"), "--length", "8",
                           "--output", str(tmp_path)],
                          capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert proc.returncode != 0
    assert "Length must be between 3 and 6 minutes" in (proc.stdout + proc.stderr)
