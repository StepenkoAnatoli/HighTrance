"""Parser-level behaviour of --review on both entry points (no rendering)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          cwd=ROOT, timeout=60)


def test_main_rejects_review_with_gui(tmp_path):
    proc = run(str(ROOT / "main.py"), "--review", "--gui", "--output", str(tmp_path))
    assert proc.returncode == 2
    assert "--review cannot be combined with --gui" in proc.stderr


def test_cli_rejects_review_with_gui(tmp_path):
    proc = run("-m", "ui.cli", "--review", "--gui", "--output", str(tmp_path))
    assert proc.returncode == 2
    assert "--review cannot be combined with --gui" in proc.stderr


def test_main_review_help_mentions_flag():
    proc = run(str(ROOT / "main.py"), "--help")
    assert proc.returncode == 0
    assert "--review" in proc.stdout


def test_cli_review_help_mentions_flag():
    proc = run("-m", "ui.cli", "--help")
    assert proc.returncode == 0
    assert "--review" in proc.stdout
