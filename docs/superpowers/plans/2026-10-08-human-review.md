# Human Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a terminal review mode — listen to the render in-app, type free-form notes, an LLM proposes global-param changes (bpm/intensity/key/length), human confirms, the same-seed song re-renders.

**Architecture:** Three new units behind injectable seams: `ai/reviewer.py` (LLM proposal + local validator), `synthesis/playback.py` (sounddevice WAV player with terminal keys), `ui/review.py` (session loop with `history.json`), wired to `main.py` and `ui/cli.py` via `--review`. Length is hard-limited app-wide to 3–6 minutes (D2).

**Tech Stack:** Python 3.14, numpy/scipy (existing), `sounddevice`, `openai` (both new), pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-human-review-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- `LENGTH_LIMITS == (3.0, 6.0)`, `DEFAULT_LENGTH_RANGE == (3.0, 6.0)`, `DEFAULTS["length"] == 4.5` — verbatim; violations raise `ValueError("Length must be between …")` from `TranceGenerator.__init__`.
- Editable params only: `bpm` (138–148), `intensity` (0.0–1.0), `length` (3.0–6.0), `key` (must pass `core.theory.parse_key`). `seed`, `scale`, `style` are NEVER editable (spec D8/D9).
- Every re-render uses the same `seed` and an explicit `scale=result["scale"]` (spec §6 — identity guarantee).
- New dependencies allowed: only `sounddevice>=0.4` and `openai>=1.0` in `requirements.txt`.
- The LLM is never trusted: every proposal is validated locally; out-of-range values are rejected and shown, never clamped (D9).
- Windows is the primary platform; keep the UTF-8 `sys.stdout.reconfigure` pattern in entry points.
- Gate for every task: `python -m pytest -q` green before commit. Working branch: `feature/human-review`.

---

### Task 1: Hard 3–6 minute length limit + `REVIEW` config

**Files:**
- Modify: `config/settings.py:18` (`DEFAULTS["length"]`), `config/settings.py:151-153` (ranges), insert `REVIEW` block after `MASTERING` (after line 132)
- Modify: `main.py:20` (import), `main.py:46` (help)
- Modify: `ui/cli.py:18` (import), `ui/cli.py:87` (help)
- Modify: `ui/gui.py:22` (import), `ui/gui.py:59` (combobox values)
- Modify: `tests/test_generation.py:201,214,223,233,265`, `tests/test_mastering.py:166`
- Modify: `README.md:14,52,77,99`
- Test: `tests/test_length_limits.py` (new)

**Interfaces:**
- Consumes: `TranceGenerator.__init__` already validates `LENGTH_LIMITS` (`core/generator.py:87`).
- Produces: `LENGTH_LIMITS = (3.0, 6.0)`, `DEFAULT_LENGTH_RANGE = (3.0, 6.0)`, `DEFAULTS["length"] = 4.5`, `REVIEW` dict (shape below) — Task 2 imports `REVIEW`; every later task relies on the limits.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_length_limits.py -v`
Expected: FAIL — `LENGTH_LIMITS` is `(1.0, 20.0)`, `REVIEW` undefined.

- [ ] **Step 3: Change the config**

In `config/settings.py`:
1. Line 18: `"length": 7.0` → `"length": 4.5` (keep the field; update comment to `# Track length in minutes (3-6)`).
2. Lines 151/153: `DEFAULT_LENGTH_RANGE: Tuple[float, float] = (3.0, 6.0)` and `LENGTH_LIMITS: Tuple[float, float] = (3.0, 6.0)`.
3. Insert after the `MASTERING` dict (after line 132, before the `# AI REFINEMENT` banner):

```python
# ======================
# HUMAN REVIEW MODE (ui/review.py, ai/reviewer.py)
# ======================

REVIEW = {
    "llm": {
        # Any OpenAI-compatible endpoint: local Ollama, LM Studio, OpenRouter, OpenAI ...
        "base_url": "http://localhost:11434/v1",
        "api_key": "not-needed-for-ollama",
        "model": "llama3.1:8b",
        "temperature": 0.2,
        "timeout": 60.0,
    },
    "history_rounds": 6,      # how many past rounds the LLM sees for context
}
```

- [ ] **Step 4: Run the new tests**

Run: `python -m pytest tests/test_length_limits.py -v`
Expected: PASS (all).

- [ ] **Step 5: Fix the fallout (tests, help texts, GUI, README)**

Exact edits:

1. `tests/test_generation.py` — four `length_minutes=1` → `length_minutes=3` (lines 201, 214, 223, 233); line 265 `"--length", "1"` → `"--length", "3"`.
2. `tests/test_mastering.py:166` — `length_minutes=1` → `length_minutes=3`.
3. `main.py` line 20: `from config.settings import DEFAULTS` → `from config.settings import DEFAULTS, LENGTH_LIMITS`; line 46: `help="Track length in minutes (6-9 recommended)"` → `help=f"Track length in minutes ({LENGTH_LIMITS[0]:g}-{LENGTH_LIMITS[1]:g})"`.
4. `ui/cli.py` line 18 import gains `DEFAULT_LENGTH_RANGE` (same import statement); line 87: help → `f"Minutes ({LENGTH_LIMITS[0]:g}-{LENGTH_LIMITS[1]:g}) or 'auto' ({DEFAULT_LENGTH_RANGE[0]:g}-{DEFAULT_LENGTH_RANGE[1]:g})"`.
5. `ui/gui.py` line 22 import gains `LENGTH_LIMITS`; line 59: `values=["auto", 6, 6.5, 7, 7.5, 8, 8.5, 9]` → `values=["auto"] + [v / 2 for v in range(int(LENGTH_LIMITS[0] * 2), int(LENGTH_LIMITS[1] * 2) + 1)]`.
6. `README.md`: line 14 `- **Length:** usually 6–9 minutes.` → `- **Length:** 3–6 minutes.`; line 52 `--length 7` → `--length 4.5`; line 77 `length_minutes=7` → `length_minutes=4.5`; line 99 `A full 7–9 minute render` → `A full 6-minute render`.

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS (old 45 tests + new length tests; render tests are slower — they now render 3 minutes).

- [ ] **Step 7: Commit**

```bash
git add config/settings.py main.py ui/cli.py ui/gui.py tests/test_length_limits.py tests/test_generation.py tests/test_mastering.py README.md
git commit -m "Hard-limit track length to 3-6 minutes; add REVIEW config"
```

---

### Task 2: `ai/reviewer.py` — LLM proposal + local validator

**Files:**
- Create: `ai/reviewer.py`
- Modify: `requirements.txt` (add `openai>=1.0`)
- Test: `tests/test_reviewer.py` (new)

**Interfaces:**
- Consumes: `REVIEW`, `LENGTH_LIMITS`, `BPM_MIN/BPM_MAX` from `config/settings.py` (Task 1); `core.theory.parse_key`.
- Produces (Task 4 depends on these exact names):
  - `ReviewerError(Exception)`
  - `Change(param: str, new: float|int|str, reason: str = "")` dataclass
  - `ReviewProposal(reply: str, changes: List[Change], rejected: List[str])` dataclass
  - `propose_changes(note: str, params: dict, history: list, client=None) -> ReviewProposal`
  - `PARAM_SPEC: dict` — keys exactly `bpm`, `intensity`, `length`, `key`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reviewer.py
"""Validator and prompt contract for the LLM reviewer (no network: fake client)."""
from types import SimpleNamespace

import pytest

from ai.reviewer import (PARAM_SPEC, Change, ReviewProposal, ReviewerError,
                         propose_changes, validate)

PARAMS = {"bpm": 142, "intensity": 0.85, "key": "Am", "length": 4.5, "scale": "minor"}


def fake_client(content=None, error=None, capture=None):
    def create(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        if error is not None:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def proposal_json(reply="ok", changes=()):
    import json
    return json.dumps({"reply": reply, "changes": list(changes)})


# ---------------------------------------------------------------- validator

def test_validate_accepts_in_range():
    accepted, rejected = validate([
        {"param": "bpm", "new": 138, "reason": "slower"},
        {"param": "intensity", "new": 0.9},
        {"param": "length", "new": 6.0},
        {"param": "key", "new": "F#m"},
    ])
    assert rejected == []
    assert [(c.param, c.new) for c in accepted] == [
        ("bpm", 138), ("intensity", 0.9), ("length", 6.0), ("key", "F#m")]


@pytest.mark.parametrize("param,new", [
    ("bpm", 200), ("bpm", 130), ("intensity", 1.5), ("intensity", -0.1),
    ("length", 7.2), ("length", 2.0),
])
def test_validate_rejects_out_of_range(param, new):
    accepted, rejected = validate([{"param": param, "new": new}])
    assert accepted == []
    assert rejected and param in rejected[0]


@pytest.mark.parametrize("param", ["seed", "scale", "style", "wat"])
def test_validate_rejects_non_editable(param):
    accepted, rejected = validate([{"param": param, "new": 1}])
    assert accepted == []
    assert rejected and ("not editable" in rejected[0])


def test_validate_rejects_bad_key():
    accepted, rejected = validate([{"param": "key", "new": "Hm9"}])
    assert accepted == []
    assert rejected and "key" in rejected[0]


def test_validate_rejects_non_numeric():
    accepted, rejected = validate([{"param": "bpm", "new": "fast"}])
    assert accepted == []
    assert rejected


def test_validate_normalizes_integral_bpm():
    accepted, _ = validate([{"param": "bpm", "new": 142.4}])
    assert accepted[0].new == 142 and isinstance(accepted[0].new, int)


def test_param_spec_keys():
    assert set(PARAM_SPEC) == {"bpm", "intensity", "length", "key"}


# ---------------------------------------------------------------- propose

def test_propose_parses_valid_reply():
    client = fake_client(proposal_json("slower", [{"param": "bpm", "new": 138, "reason": "x"}]))
    p = propose_changes("slower please", PARAMS, [], client=client)
    assert p.reply == "slower"
    assert p.changes == [Change("bpm", 138, "x")]
    assert p.rejected == []


def test_propose_collects_rejections():
    client = fake_client(proposal_json("nope", [
        {"param": "bpm", "new": 200}, {"param": "seed", "new": 5}]))
    p = propose_changes("weird", PARAMS, [], client=client)
    assert p.changes == []
    assert len(p.rejected) == 2


def test_propose_empty_changes_is_valid():
    client = fake_client(proposal_json("sounds good", []))
    p = propose_changes("no change", PARAMS, [], client=client)
    assert p.reply == "sounds good" and p.changes == [] and p.rejected == []


def test_propose_garbage_json_raises():
    with pytest.raises(ReviewerError):
        propose_changes("x", PARAMS, [], client=fake_client("not json at all"))


def test_propose_json_embedded_in_prose():
    client = fake_client('Sure! {"reply": "done", "changes": []} hope that helps')
    p = propose_changes("x", PARAMS, [], client=client)
    assert p.reply == "done"


def test_propose_endpoint_error_raises():
    with pytest.raises(ReviewerError):
        propose_changes("x", PARAMS, [], client=fake_client(error=ConnectionError("down")))


def test_prompt_contains_params_history_note():
    capture = {}
    history = [{"n": 1, "note": "tried slower before", "reply": "ok",
                "changes": [{"param": "bpm", "new": 140}]}]
    propose_changes("make it darker", PARAMS, history,
                    client=fake_client(proposal_json(), capture=capture))
    system, user = capture["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    assert "make it darker" in user["content"]
    assert "scale: minor" in user["content"]
    assert "tried slower before" in user["content"]
    assert "138..148" in system["content"] or "138" in system["content"]
    assert capture["model"]  # model comes from REVIEW["llm"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_reviewer.py -v`
Expected: FAIL — `ModuleNotFoundError: ai.reviewer` (or import error for `validate`).

- [ ] **Step 3: Implement `ai/reviewer.py`**

```python
"""LLM-backed review assistant: turn a human's free-form note about the current
track into validated global-parameter changes.

The LLM only ever *suggests* — every proposal is checked against ``PARAM_SPEC``
locally (spec D9: never trust the model).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.settings import BPM_MAX, BPM_MIN, LENGTH_LIMITS, REVIEW
from core.theory import parse_key


class ReviewerError(Exception):
    """The LLM endpoint failed or its output could not be understood."""


#: The only parameters the review loop may change (spec §4) — feeds prompt AND validator.
PARAM_SPEC: Dict[str, Dict[str, Any]] = {
    "bpm": {"kind": "number", "min": BPM_MIN, "max": BPM_MAX, "integer": True,
            "description": "tempo in beats per minute"},
    "intensity": {"kind": "number", "min": 0.0, "max": 1.0,
                  "description": "overall energy, 0.0 (chill) .. 1.0 (full power)"},
    "length": {"kind": "number", "min": LENGTH_LIMITS[0], "max": LENGTH_LIMITS[1],
               "description": "track length in minutes"},
    "key": {"kind": "key", "description": "musical key, e.g. Am, F#m, C#"},
}


@dataclass
class Change:
    param: str
    new: Any
    reason: str = ""


@dataclass
class ReviewProposal:
    reply: str
    changes: List[Change]
    rejected: List[str]


def _spec_text() -> str:
    lines = []
    for name, spec in PARAM_SPEC.items():
        if spec["kind"] == "key":
            rng = "a valid key name (examples: Am, F#m, Dm, C#)"
        else:
            rng = f"{spec['min']:g}..{spec['max']:g}" + (" (integer)" if spec.get("integer") else "")
        lines.append(f"- {name}: {spec['description']}, {rng}")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are a review assistant for a trance music generator. The human listened "
    "to the track and wrote a note about what should change.\n\n"
    "Editable parameters:\n{spec}\n\n"
    'Reply with ONLY a JSON object (no prose, no code fences): '
    '{{"reply": "<short plain-English answer to the human\'s note>", '
    '"changes": [{{"param": "<name>", "new": <value>, "reason": "<short why>"}}]}}\n\n'
    "Rules: only the parameters listed above; \"new\" must be within its range; "
    "omit a change unless the note calls for it (an empty \"changes\" list is "
    "valid); \"reply\" must address the note directly."
)


def _user_message(params: Dict, history: List[Dict], note: str) -> str:
    lines = ["Current parameters:"]
    lines += [f"  {k}: {v}" for k, v in params.items()]
    past = history[-REVIEW["history_rounds"]:] if history else []
    if past:
        lines.append("Recent review history:")
        for h in past:
            changes = ", ".join(f"{c.get('param')}={c.get('new')}"
                                for c in h.get("changes", [])) or "no changes applied"
            lines.append(f"  note: {h.get('note', '(initial render)')} "
                         f"-> {h.get('reply', '')} [{changes}]")
    lines.append(f"Human note: {note}")
    return "\n".join(lines)


def validate(raw_changes: Any) -> Tuple[List[Change], List[str]]:
    """Check every LLM-proposed change against PARAM_SPEC. Reject, never clamp."""
    accepted: List[Change] = []
    rejected: List[str] = []
    if not isinstance(raw_changes, list):
        return accepted, ["LLM returned changes in an unexpected format"]
    for item in raw_changes:
        if not isinstance(item, dict) or "param" not in item or "new" not in item:
            rejected.append(f"malformed change entry: {item!r}")
            continue
        param = str(item["param"])
        if param not in PARAM_SPEC:
            rejected.append(f"{param} is not editable")
            continue
        spec = PARAM_SPEC[param]
        new = item["new"]
        if spec["kind"] == "key":
            if not isinstance(new, str):
                rejected.append(f"{param}: expected a key name, got {new!r}")
                continue
            try:
                parse_key(new)
            except ValueError as e:
                rejected.append(f"{param} {new!r}: {e}")
                continue
        else:
            if isinstance(new, bool) or not isinstance(new, (int, float)):
                rejected.append(f"{param}: expected a number, got {new!r}")
                continue
            if not spec["min"] <= float(new) <= spec["max"]:
                rejected.append(f"{param} {new} outside {spec['min']:g}-{spec['max']:g}")
                continue
            new = int(round(float(new))) if spec.get("integer") else float(new)
        accepted.append(Change(param, new, str(item.get("reason") or "")))
    return accepted, rejected


def _extract_json(text: str) -> Dict:
    start = text.find("{")
    if start < 0:
        raise ReviewerError(f"no JSON object in LLM reply: {text[:120]!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise ReviewerError(f"unparseable LLM output: {e}") from e
    if not isinstance(obj, dict):
        raise ReviewerError("LLM output is not a JSON object")
    return obj


def _default_client():
    # Imported lazily so the module (and its tests) work without the SDK at import
    # time; any import/endpoint failure surfaces as ReviewerError below.
    from openai import OpenAI
    cfg = REVIEW["llm"]
    return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])


def propose_changes(note: str, params: Dict, history: List[Dict],
                    client=None) -> ReviewProposal:
    """Ask the LLM what to change, then validate the answer locally.

    Raises ``ReviewerError`` on endpoint/JSON failures — the caller decides
    whether to retry or quit.
    """
    cfg = REVIEW["llm"]
    try:
        client = client or _default_client()
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(spec=_spec_text())},
                {"role": "user", "content": _user_message(params, history, note)},
            ],
            temperature=cfg["temperature"],
            timeout=cfg["timeout"],
        )
        content = response.choices[0].message.content or ""
    except ReviewerError:
        raise
    except Exception as e:
        raise ReviewerError(f"LLM request failed: {e}") from e

    data = _extract_json(content)
    reply = str(data.get("reply") or "")
    changes, rejected = validate(data.get("changes", []))
    return ReviewProposal(reply, changes, rejected)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_reviewer.py -v`
Expected: PASS (all).

- [ ] **Step 5: Add dependency + commit**

`requirements.txt` — add under a new comment line after the FluidSynth block:

```
# Interactive review mode (spec: docs/superpowers/specs/2026-10-08-human-review-design.md)
openai>=1.0
```

```bash
python -m pip install openai
git add ai/reviewer.py tests/test_reviewer.py requirements.txt
git commit -m "Add LLM reviewer with local param validation"
```

---

### Task 3: `synthesis/playback.py` — terminal-controlled WAV player

**Files:**
- Create: `synthesis/playback.py`
- Modify: `requirements.txt` (add `sounddevice>=0.4`)
- Test: `tests/test_playback.py` (new)

**Interfaces:**
- Consumes: `synthesis.audio_processor.read_wav(path) -> (float32 (n, channels) [-1,1], sample_rate, bit_depth)` — always 2-D; mono comes back as `(n, 1)`.
- Produces (Task 4 depends on these exact names):
  - `PlaybackError(Exception)`
  - `Player(path, stream_factory=None, interactive=True)` with
    `play()`, `pause()`, `toggle()`, `seek(seconds: float)`, `rewind()`, `stop()`, `callback(outdata, frames, time_info=None, status=None)`, `listen() -> None`, and attrs `data`, `samplerate`, `duration`, `position`, `playing`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_playback.py
"""Player decode/stream/seek behaviour — no real device, no keyboard."""
import numpy as np
import pytest

from synthesis.audio_render import write_wav
from synthesis.playback import PlaybackError, Player

SR = 8000


def make_wav(tmp_path, seconds=1.0, channels=2, name="t.wav"):
    n = int(seconds * SR)
    rs = np.random.RandomState(0)
    audio = (rs.rand(n, channels).astype(np.float32) * 0.2) - 0.1
    path = write_wav(audio, tmp_path / name, SR)
    return path, audio


class FakeStream:
    def __init__(self):
        self.started = self.stopped = self.closed = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def close(self): self.closed = True


def player(tmp_path, seconds=1.0, channels=2, **kw):
    path, audio = make_wav(tmp_path, seconds, channels)
    kw.setdefault("interactive", False)
    kw.setdefault("stream_factory", FakeStream)
    return Player(path, **kw), audio


def test_decode_stereo(tmp_path):
    p, audio = player(tmp_path)
    assert p.data.dtype == np.float32 and p.data.shape == audio.shape
    assert p.samplerate == SR
    assert p.duration == pytest.approx(1.0)


def test_mono_promoted_to_stereo(tmp_path):
    p, _ = player(tmp_path, channels=1)
    assert p.data.ndim == 2 and p.data.shape[1] == 2
    assert np.allclose(p.data[:, 0], p.data[:, 1])


def test_playback_fills_frames(tmp_path):
    p, audio = player(tmp_path)
    p.play()
    out = np.zeros((256, 2), dtype=np.float32)
    p.callback(out, 256)
    assert np.allclose(out, audio[:256])
    assert p.position == 256 and p.playing


def test_paused_outputs_silence(tmp_path):
    p, _ = player(tmp_path)
    p.play(); p.pause()
    out = np.ones((256, 2), dtype=np.float32)
    p.callback(out, 256)
    assert not out.any() and p.position == 0


def test_eof_stops_and_silences(tmp_path):
    p, _ = player(tmp_path, seconds=0.1)     # 800 frames
    p.play()
    out = np.zeros((1024, 2), dtype=np.float32)
    p.callback(out, 1024)
    assert not p.playing and p.position == 800
    assert not out[800:].any()


def test_play_after_eof_restarts(tmp_path):
    p, _ = player(tmp_path, seconds=0.1)
    p.play()
    p.callback(np.zeros((1024, 2), np.float32), 1024)
    assert not p.playing and p.position == 800
    p.play()
    assert p.position == 0 and p.playing


def test_seek_clamps(tmp_path):
    p, _ = player(tmp_path, seconds=1.0)
    p.seek(-50.0)
    assert p.position == 0
    p.seek(10_000.0)
    assert p.position == len(p.data)
    p.seek(-0.5)
    assert p.position == len(p.data) - int(0.5 * SR)


def test_rewind(tmp_path):
    p, _ = player(tmp_path)
    p.seek(0.4)
    p.rewind()
    assert p.position == 0


def test_toggle_and_stop(tmp_path):
    p, _ = player(tmp_path)
    p.toggle()
    assert p.playing
    p.toggle()
    assert not p.playing
    p.play(); p.stop()
    assert not p.playing and p._stream is None


def test_non_interactive_listen_returns_without_device(tmp_path):
    p, _ = player(tmp_path)
    p.listen()          # no keyboard, no device — returns immediately
    assert p._stream is None


def test_missing_file_raises(tmp_path):
    with pytest.raises(Exception):
        Player(tmp_path / "nope.wav")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_playback.py -v`
Expected: FAIL — `ModuleNotFoundError: synthesis.playback`.

- [ ] **Step 3: Implement `synthesis/playback.py`**

```python
"""In-app WAV playback with terminal controls (spec §5).

Space = play/pause, J/L = seek -/+10 s, Enter = done listening.
``sinteractive=False`` and an injected ``stream_factory`` keep the class
testable without an audio device or a keyboard.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from synthesis.audio_processor import read_wav

SEEK_SECONDS = 10.0


class PlaybackError(Exception):
    """No usable audio output device (the caller falls back to manual listening)."""


class Player:
    def __init__(self, path, stream_factory: Optional[Callable[[], object]] = None,
                 interactive: bool = True):
        data, sample_rate, _bits = read_wav(Path(path))
        if data.ndim == 1:                       # defensive: read_wav is 2-D already
            data = data.reshape(-1, 1)
        if data.shape[1] == 1:                   # mono -> stereo
            data = np.column_stack([data, data])
        self.data = np.ascontiguousarray(data, dtype=np.float32)
        self.samplerate = int(sample_rate)
        self.duration = len(self.data) / self.samplerate
        self.path = str(path)
        self.position = 0                        # frame index
        self.playing = False
        self._lock = threading.Lock()
        self._stream = None
        self._stream_factory = stream_factory or self._default_factory
        self._interactive = interactive

    # ------------------------------------------------------------- stream
    def _default_factory(self):
        try:
            import sounddevice as sd
            return sd.OutputStream(samplerate=self.samplerate, channels=2,
                                   dtype="float32", callback=self.callback)
        except Exception as e:
            raise PlaybackError(f"audio output unavailable: {e}") from e

    def _ensure_stream(self) -> None:
        if self._stream is None:
            stream = self._stream_factory()
            start = getattr(stream, "start", None)
            if callable(start):
                start()
            self._stream = stream

    def callback(self, outdata, frames, time_info=None, status=None) -> None:
        """Pull ``frames`` stereo frames at ``position``; silence when paused/EOF."""
        outdata[:] = 0.0
        with self._lock:
            if not self.playing:
                return
            end = min(self.position + frames, len(self.data))
            n = end - self.position
            if n <= 0:
                self.playing = False
                return
            outdata[:n] = self.data[self.position:end]
            self.position = end
            if self.position >= len(self.data):
                self.playing = False

    # ------------------------------------------------------------- controls
    def play(self) -> None:
        with self._lock:
            if self.position >= len(self.data):  # replay after EOF
                self.position = 0
            self.playing = True
        self._ensure_stream()

    def pause(self) -> None:
        with self._lock:
            self.playing = False

    def toggle(self) -> None:
        (self.pause if self.playing else self.play)()

    def seek(self, seconds: float) -> None:
        with self._lock:
            self.position = int(max(0, min(len(self.data),
                                           self.position + seconds * self.samplerate)))

    def rewind(self) -> None:
        with self._lock:
            self.position = 0

    def stop(self) -> None:
        with self._lock:
            self.playing = False
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------- keyboard
    def _read_key(self) -> str:
        if sys.platform == "win32":
            import msvcrt
            key = msvcrt.getch()
            if key in (b"\xe0", b"\x00"):        # swallow arrow-key second byte
                msvcrt.getch()
                return ""
            if key in (b"\r", b"\n"):
                return "\r"
            if key == b" ":
                return " "
            if key in (b"j", b"J"):
                return "j"
            if key in (b"l", b"L"):
                return "l"
            return ""
        import sys as _sys
        import termios
        import tty
        fd = _sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            key = _sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if key in ("\r", "\n"):
            return "\r"
        if key == " ":
            return " "
        if key in ("j", "J"):
            return "j"
        if key in ("l", "L"):
            return "l"
        return ""

    def listen(self) -> None:
        """Block until Enter; Space/J/L control playback meanwhile.

        Non-interactive mode returns immediately (tests, headless use).
        Ctrl+C raises KeyboardInterrupt, handled by the caller.
        """
        if not self._interactive:
            return
        self._ensure_stream()
        while True:
            key = self._read_key()
            if key == "\r":
                return
            if key == " ":
                self.toggle()
            elif key == "j":
                self.seek(-SEEK_SECONDS)
            elif key == "l":
                self.seek(SEEK_SECONDS)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_playback.py -v`
Expected: PASS (all).

- [ ] **Step 5: Add dependency + commit**

`requirements.txt` — add `sounddevice>=0.4` under the same review-mode comment as Task 2 (move the comment above both lines if needed).

```bash
python -m pip install sounddevice
git add synthesis/playback.py tests/test_playback.py requirements.txt
git commit -m "Add terminal-controlled WAV playback player"
```

---

### Task 4: `ui/review.py` — the session loop

**Files:**
- Create: `ui/review.py`
- Test: `tests/test_review_loop.py` (new)

**Interfaces:**
- Consumes: `propose_changes` / `ReviewerError` / `Change` / `ReviewProposal` (Task 2); `Player` / `PlaybackError` (Task 3); the `result` dict from `TranceGenerator.generate()` (keys: `style`, `bpm`, `intensity`, `key`, `length_minutes`, `scale`, `seed`, `audio_path`, `errors`); the `REVIEW` config is not read directly here.
- Produces (Task 5 depends on it): `ReviewSession(generator, result, *, master=None, final_format="wav", reviewer=None, player_factory=None, generate_fn=None, input_fn=input, out=print)` with `run() -> dict` (keys `history`, `final_audio`, `applied_rounds`, `rounds`) and attrs `history_path`, `params`, `history`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_loop.py
"""ReviewSession loop against fakes: reviewer, player and renderer are injected."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.reviewer import Change, ReviewProposal, ReviewerError
from synthesis.playback import PlaybackError
from ui.review import ReviewSession


def round0(tmp_path):
    return {"style": "goa", "bpm": 142, "intensity": 0.85, "key": "Am",
            "length_minutes": 4.5, "scale": "minor", "seed": 8,
            "audio_path": str(tmp_path / "audio" / "r0.wav"), "errors": []}


def fake_generator(tmp_path):
    return SimpleNamespace(output_dir=tmp_path, sample_rate=8000, bit_depth=16,
                           renderer="auto", soundfont=None, verbose=False)


class FakePlayer:
    def __init__(self, path=None):
        self.path, self.stopped, self.rewound = path, False, False

    def listen(self): pass
    def seek(self, seconds): pass
    def rewind(self): self.rewound = True
    def stop(self): self.stopped = True


def scripted_input(*answers):
    answers, prompts = iter(list(answers)), []

    def read(prompt):
        prompts.append(prompt)
        try:
            return next(answers)
        except StopIteration:
            pytest.fail(f"unexpected prompt: {prompt!r}")
    return read, prompts


def reviewer_returning(proposal, calls=None):
    def review(note, params, history):
        if calls is not None:
            calls.append((note, dict(params), list(history)))
        return proposal
    return review


def build(tmp_path, *, proposal=None, reviewer=None, inputs=(), generate_fn=None,
          player_factory=None, final_format="wav", out_lines=None):
    read, prompts = scripted_input(*inputs)
    out = out_lines if out_lines is not None else []
    session = ReviewSession(
        fake_generator(tmp_path), round0(tmp_path), master=False,
        final_format=final_format,
        reviewer=reviewer or reviewer_returning(proposal),
        player_factory=player_factory or (lambda p: FakePlayer(p)),
        generate_fn=generate_fn,
        input_fn=read, out=(lambda msg: out.append(str(msg))))
    return session, prompts, out


def test_confirm_applies_changes_and_records_history(tmp_path):
    calls = []
    def gen(params):
        calls.append(dict(params))
        r = round0(tmp_path); r["bpm"] = params["bpm"]
        r["audio_path"] = str(tmp_path / "audio" / "r1.wav")
        return r
    proposal = ReviewProposal("slower", [Change("bpm", 138, "pace")], [])
    session, prompts, out = build(tmp_path, proposal=proposal,
                                  inputs=["slower", "y", "q"], generate_fn=gen)
    summary = session.run()
    assert calls and calls[0]["bpm"] == 138
    assert calls[0]["scale"] == "minor"          # identity: explicit scale
    assert calls[0]["length"] == 4.5
    history = json.loads(Path(session.history_path).read_text(encoding="utf-8"))
    assert history["rounds"][0]["params"]["bpm"] == 142
    assert history["rounds"][1]["params"]["bpm"] == 138
    assert history["rounds"][1]["note"] == "slower"
    assert summary["applied_rounds"] == 1 and summary["final_audio"].endswith(".wav")
    assert any("Apply?" in p for p in prompts)


def test_declined_proposal_renders_nothing(tmp_path):
    def gen(params):
        pytest.fail("render must not happen")
    proposal = ReviewProposal("slower", [Change("bpm", 138)], [])
    session, prompts, out = build(tmp_path, proposal=proposal,
                                  inputs=["slower", "n", "q"], generate_fn=gen)
    session.run()
    history = json.loads(Path(session.history_path).read_text(encoding="utf-8"))
    assert len(history["rounds"]) == 2           # round 0 + recorded note
    assert "params" not in history["rounds"][1]  # nothing applied


def test_zero_change_proposal_skips_confirm(tmp_path):
    def gen(params):
        pytest.fail("render must not happen")
    proposal = ReviewProposal("sounds good", [], ["bpm 200 outside 138-148"])
    session, prompts, out = build(tmp_path, proposal=proposal,
                                  inputs=["meh", "q"], generate_fn=gen)
    session.run()
    assert not any("Apply?" in p for p in prompts)
    assert any("rejected:" in line for line in out)


def test_render_failure_rolls_back(tmp_path):
    def gen(params):
        raise RuntimeError("synth exploded")
    proposal = ReviewProposal("slower", [Change("bpm", 138)], [])
    out_lines = []
    session, _, _ = build(tmp_path, proposal=proposal,
                          inputs=["slower", "y", "q"], generate_fn=gen,
                          out_lines=out_lines)
    session.run()
    assert session.params["bpm"] == 142          # rolled back
    assert any("Render failed" in m for m in out_lines)
    history = json.loads(Path(session.history_path).read_text(encoding="utf-8"))
    assert history["rounds"][1]["error"] == "synth exploded"
    assert "params" not in history["rounds"][1]


def test_render_returning_no_audio_is_a_failure(tmp_path):
    def gen(params):
        return {"audio_path": None, "errors": ["Audio rendering failed: boom"]}
    proposal = ReviewProposal("slower", [Change("bpm", 138)], [])
    out_lines = []
    session, _, _ = build(tmp_path, proposal=proposal,
                          inputs=["slower", "y", "q"], generate_fn=gen,
                          out_lines=out_lines)
    session.run()
    assert session.params["bpm"] == 142
    assert any("boom" in m for m in out_lines)


def test_llm_error_retry_keeps_note(tmp_path):
    calls, state = [], {"first": True}
    def review(note, params, history):
        calls.append(note)
        if state["first"]:
            state["first"] = False
            raise ReviewerError("endpoint down")
        return ReviewProposal("ok", [], [])
    proposal = None
    session, _, _ = build(tmp_path, reviewer=review,
                          inputs=["my note", "r", "q"], generate_fn=lambda p: pytest.fail("no render"))
    session.run()
    assert calls == ["my note", "my note"]       # same note preserved on retry


def test_llm_error_quit_saves_session(tmp_path):
    def review(note, params, history):
        raise ReviewerError("endpoint down")
    session, _, out = build(tmp_path, reviewer=review,
                            inputs=["anything", "q"],
                            generate_fn=lambda p: pytest.fail("no render"))
    summary = session.run()
    assert Path(session.history_path).exists()
    assert "final_audio" in summary


def test_no_device_falls_back_to_manual_permanently(tmp_path):
    out_lines, attempts = [], []
    def factory(path):
        attempts.append(path)
        raise PlaybackError("no device")
    session, prompts, _ = build(tmp_path,
                                proposal=ReviewProposal("done", [], []),
                                inputs=["", "first note", "", "q"],  # two listen rounds
                                generate_fn=lambda p: pytest.fail("no render"),
                                player_factory=factory,
                                out_lines=out_lines)
    session.run()
    assert len(attempts) == 1                # spec §5: fallback is permanent, no retry
    assert sum("Listen externally" in m for m in out_lines) == 2
    assert sum("Press Enter when ready" in p for p in prompts) == 2


def test_keyboard_interrupt_saves_and_stops_player(tmp_path):
    class InterruptingPlayer(FakePlayer):
        def listen(self):
            raise KeyboardInterrupt
    touched = []
    session, prompts, out = build(
        tmp_path,
        reviewer=lambda *a: pytest.fail("note never reached"),
        inputs=[],  # no prompts may be consumed
        generate_fn=lambda p: pytest.fail("no render"),
        player_factory=lambda p: touched.append(p) or InterruptingPlayer(p))
    summary = session.run()
    assert touched and summary["final_audio"].endswith(".wav")
    assert Path(session.history_path).exists()


def test_mp3_conversion_on_exit_only_when_requested(tmp_path, monkeypatch):
    converted = []
    monkeypatch.setattr("synthesis.audio_render.wav_to_mp3",
                        lambda p: converted.append(p) or p.replace(".wav", ".mp3"))
    session, _, _ = build(tmp_path, final_format="wav", inputs=["q"],
                          generate_fn=lambda p: pytest.fail("no render"))
    wav_summary = session.run()
    session2, _, _ = build(tmp_path, final_format="mp3", inputs=["q"],
                           generate_fn=lambda p: pytest.fail("no render"))
    mp3_summary = session2.run()
    assert wav_summary["final_audio"].endswith(".wav") and not converted
    assert mp3_summary["final_audio"].endswith(".mp3") and len(converted) == 1


def test_empty_note_rewinds_player(tmp_path):
    class RecordingPlayer(FakePlayer):
        pass
    players = []
    def factory(path):
        p = RecordingPlayer(path)
        players.append(p)
        return p
    session, _, _ = build(tmp_path, proposal=ReviewProposal("x", [], []),
                          inputs=["", "q"],
                          generate_fn=lambda p: pytest.fail("no render"),
                          player_factory=factory)
    session.run()
    assert players and players[0].rewound


def test_default_generate_copies_identity(tmp_path, monkeypatch):
    """The real re-render path keeps seed/scale/format and passes master through."""
    captured = {}

    class RecordingGen:
        def __init__(self, **kwargs):
            captured["ctor"] = kwargs

        def generate(self, **kwargs):
            captured["gen"] = kwargs
            return {"audio_path": str(tmp_path / "audio" / "new.wav"), "errors": []}

    monkeypatch.setattr("core.generator.TranceGenerator", RecordingGen)
    session, _, _ = build(tmp_path, proposal=ReviewProposal("x", [], []),
                          inputs=["q"],
                          generate_fn=None)     # force the default generate_fn
    result = session._default_generate({**session.params, "bpm": 138})
    ctor = captured["ctor"]
    assert ctor["seed"] == 8 and ctor["scale"] == "minor"
    assert ctor["bpm"] == 138 and ctor["length_minutes"] == 4.5
    assert ctor["key"] == "Am" and ctor["intensity"] == 0.85
    assert ctor["audio_format"] == "wav" and ctor["sample_rate"] == 8000
    assert captured["gen"]["master"] is False   # --no-master carried through
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_review_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: ui.review`.

- [ ] **Step 3: Implement `ui/review.py`**

```python
"""Interactive review loop (spec §6): listen → note → LLM proposal → confirm →
same-seed re-render. Every round is appended to ``history.json`` (flushed per
round, crash-safe); a failed render rolls back to the last good params."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ai.reviewer import ReviewerError, propose_changes
from synthesis.playback import Player, PlaybackError


class ReviewSession:
    def __init__(self, generator, result: Dict, *, master=None,
                 final_format: str = "wav",
                 reviewer: Optional[Callable] = None,
                 player_factory: Optional[Callable] = None,
                 generate_fn: Optional[Callable[[Dict], Dict]] = None,
                 input_fn: Callable[[str], str] = input,
                 out: Callable[[str], None] = print):
        if not result.get("audio_path"):
            raise ValueError("review session needs a rendered audio file")
        self.generator = generator
        self.result = result
        self.master = master                      # None | False — carried through every round
        self.final_format = (final_format or "wav").lower()
        self.reviewer = reviewer or propose_changes
        self.player_factory = player_factory or Player
        self.generate_fn = generate_fn or self._default_generate
        self._input = input_fn
        self.out = out
        self.seed = result["seed"]
        self.style = result["style"]
        # scale is resolved once (round 0) and passed explicitly every round —
        # omitting it would re-draw it from the parameter RNG stream (spec §6).
        self.params: Dict = {"bpm": result["bpm"], "intensity": result["intensity"],
                             "key": result["key"], "length": result["length_minutes"],
                             "scale": result["scale"]}
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.session_dir = Path(generator.output_dir) / "reviews" / f"review-{stamp}"
        self.history_path = self.session_dir / "history.json"
        self.history = {"created": datetime.now().isoformat(timespec="seconds"),
                        "style": self.style, "seed": self.seed,
                        "rounds": [{"n": 0, "params": dict(self.params),
                                    "audio_path": str(result["audio_path"])}]}
        self._audio = str(result["audio_path"])
        self._history_warned = False
        self._playback_broken = False            # permanent fallback after first PlaybackError

    # ------------------------------------------------------------- rendering
    def _default_generate(self, new_params: Dict) -> Dict:
        from core.generator import TranceGenerator     # local: keeps module light
        gen = TranceGenerator(
            style=self.style, seed=self.seed,
            bpm=new_params["bpm"], length_minutes=new_params["length"],
            key=new_params["key"], scale=new_params["scale"],
            intensity=new_params["intensity"],
            output_dir=self.generator.output_dir,
            sample_rate=self.generator.sample_rate,
            bit_depth=self.generator.bit_depth,
            audio_format="wav",                      # session plays WAV (spec §6)
            renderer=self.generator.renderer,
            soundfont=self.generator.soundfont,
            verbose=self.generator.verbose)
        result = gen.generate(render_audio=True, master=self.master)
        self.generator = gen                         # only after a completed attempt
        return result

    # ------------------------------------------------------------- helpers
    def _read(self, prompt: str) -> str:
        try:
            return self._input(prompt).strip()
        except EOFError:
            return "q"

    def _flush(self) -> None:
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.history_path.write_text(json.dumps(self.history, indent=2),
                                         encoding="utf-8")
        except OSError as e:
            if not self._history_warned:
                self._history_warned = True
                self.out(f"Warning: could not save history: {e}")

    def _failed(self, entry: Dict, error: str) -> None:
        entry["error"] = error
        self.history["rounds"].append(entry)
        self._flush()
        self.out(f"Render failed: {error} — staying on previous version")

    def _finish(self) -> Dict:
        final = self._audio
        if self.final_format == "mp3" and str(final).lower().endswith(".wav"):
            try:
                from synthesis.audio_render import wav_to_mp3
                final = str(wav_to_mp3(final))
            except Exception as e:
                self.out(f"MP3 conversion failed: {e} — keeping WAV")
        self._flush()
        applied = max(sum(1 for r in self.history["rounds"] if "audio_path" in r) - 1, 0)
        summary = {"history": str(self.history_path), "final_audio": str(final),
                   "applied_rounds": applied, "rounds": len(self.history["rounds"])}
        self.out(f"Review finished: {applied} change(s) applied.")
        self.out(f"Final file: {final}")
        self.out(f"History  : {self.history_path}")
        return summary

    # ------------------------------------------------------------- main loop
    def run(self) -> Dict:
        player = None
        try:
            while True:
                # -- listen ------------------------------------------------
                if player is None and not self._playback_broken:
                    try:
                        player = self.player_factory(self._audio)
                    except PlaybackError as e:
                        self._playback_broken = True   # permanent: no per-round retry
                        self.out(f"No audio device ({e}) — listen manually.")
                if player is not None:
                    self.out("(Space=play/pause  J/L=seek  Enter=done)")
                    player.listen()
                else:
                    self.out(f"Listen externally: {self._audio}")
                    self._read("Press Enter when ready to take notes: ")

                # -- notes -------------------------------------------------
                note = self._read("\nNotes (Enter = replay, q = quit): ")
                if note.lower() in ("q", "quit"):
                    break
                if not note:                       # replay from the top
                    if player is not None:
                        player.rewind()
                    else:
                        self.out(f"Replay: {self._audio}")
                    continue

                # -- proposal (retry keeps the note) -----------------------
                while True:
                    try:
                        proposal = self.reviewer(note, dict(self.params),
                                                 self.history["rounds"])
                        break
                    except ReviewerError as e:
                        choice = self._read(
                            f"LLM unavailable: {e}\n[r]etry / [q]uit: ").lower()
                        if choice == "r":
                            continue
                        return self._finish()

                # -- display -----------------------------------------------
                if proposal.reply:
                    self.out(f"LLM: {proposal.reply}")
                for c in proposal.changes:
                    reason = f"   ({c.reason})" if c.reason else ""
                    self.out(f"  {c.param:<10} {self.params.get(c.param)} -> {c.new}{reason}")
                for r in proposal.rejected:
                    self.out(f"  rejected: {r}")
                entry: Dict = {"n": len(self.history["rounds"]), "note": note,
                               "reply": proposal.reply,
                               "changes": [{"param": c.param, "new": c.new,
                                            "reason": c.reason} for c in proposal.changes],
                               "rejected": list(proposal.rejected)}
                if not proposal.changes:           # zero accepted == no confirm
                    self.history["rounds"].append(entry)
                    self._flush()
                    continue
                if self._read("Apply? [y/N] ").lower() != "y":
                    self.history["rounds"].append(entry)
                    self._flush()
                    continue

                # -- apply --------------------------------------------------
                new_params = dict(self.params)
                for c in proposal.changes:
                    new_params[c.param] = c.new
                self.out("Re-rendering the same song with the new parameters...")
                try:
                    new_result = self.generate_fn(new_params)
                except Exception as e:
                    self._failed(entry, str(e))
                    continue
                if not new_result.get("audio_path"):
                    self._failed(entry, "; ".join(new_result.get("errors", []))
                                 or "no audio produced")
                    continue
                if player is not None:
                    player.stop()
                    player = None
                self._audio = str(new_result["audio_path"])
                self.params = new_params
                self.result = new_result
                entry["params"] = dict(new_params)
                entry["audio_path"] = self._audio
                self.history["rounds"].append(entry)
                self._flush()
                self.out(f"Applied. Next round — listen again.\n")
        except KeyboardInterrupt:
            self.out("\nReview interrupted — session saved.")
        finally:
            if player is not None:
                try:
                    player.stop()
                except Exception:
                    pass
        return self._finish()
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_review_loop.py -v`
Expected: PASS (all 12).

- [ ] **Step 5: Run the full suite + commit**

Run: `python -m pytest -q`
Expected: PASS.

```bash
git add ui/review.py tests/test_review_loop.py
git commit -m "Add review session loop with confirm gate and history"
```

---

### Task 5: CLI wiring (`--review`) + README

**Files:**
- Modify: `main.py` (import, `--length` help already done in Task 1; add `--review`, gui-conflict check, review block in `main()`)
- Modify: `ui/cli.py` (add `--review`, gui-conflict check, review block in `main()`)
- Modify: `README.md` (new "Review mode" section)
- Test: `tests/test_review_cli.py` (new — parser-level checks only; the full flow is Task 6)

**Interfaces:**
- Consumes: `ReviewSession` (Task 4), `LENGTH_LIMITS` (Task 1).
- Produces: `--review` flag on both entry points; behavior: implies `--render-audio`, forces WAV for the session, `final_format` = `"wav"` (`main.py`) or `args.format` (`ui.cli`), rejects `--review --gui` with exit code 2.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_cli.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_review_cli.py -v`
Expected: FAIL — `--review` unrecognized (exit 2 from argparse, but no `--review cannot be combined` message; help lacks `--review`).

- [ ] **Step 3: Wire `main.py`**

1. Add the argument after `--gui` (line ~87):

```python
    parser.add_argument(
        "--review",
        action="store_true",
        help="Interactive review loop after rendering (implies --render-audio; in-app playback)"
    )
```

2. At the end of `parse_arguments()`, change `return parser.parse_args()` to:

```python
    args = parser.parse_args()
    if args.review and args.gui:
        parser.error("--review cannot be combined with --gui")
    return args
```

3. In `main()`, replace the generate block (lines 126-128) with:

```python
    # Generate the track
    print("\nGenerating track...")
    result = generator.generate(render_audio=args.render_audio or args.review,
                                audio_format="wav" if args.review else None,
                                master=False if args.no_master else None)

    # Show summary
    print_summary(result)

    # Interactive review loop (spec: docs/superpowers/specs/2026-10-08-human-review-design.md)
    if args.review:
        if not result.get("audio_path"):
            print("Review mode needs rendered audio, but no audio was produced.",
                  file=sys.stderr)
            sys.exit(1)
        from ui.review import ReviewSession
        session = ReviewSession(generator, result,
                                master=False if args.no_master else None,
                                final_format="wav")
        session.run()
```

- [ ] **Step 4: Wire `ui/cli.py`**

1. Add the argument after `--render-audio` (line ~94):

```python
    p.add_argument("--review", action="store_true",
                   help="Interactive review loop after rendering (implies --render-audio; in-app playback)")
```

2. In `main()`, replace lines 106-107 with:

```python
def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.review and args.gui:
        parser.error("--review cannot be combined with --gui")
    if args.gui:
```

3. Replace the generate call (lines 120-121) with:

```python
        result = gen.generate(render_audio=args.render_audio or args.review,
                              audio_format="wav" if args.review else None,
                              master=False if args.no_master else None)
```

4. After `print_summary(result)` (line 125), insert:

```python
    if args.review:
        if not result.get("audio_path"):
            print("Review mode needs rendered audio, but no audio was produced.",
                  file=sys.stderr)
            return 1
        from ui.review import ReviewSession
        session = ReviewSession(gen, result,
                                master=False if args.no_master else None,
                                final_format=args.format)
        session.run()
```

- [ ] **Step 5: README "Review mode" section**

Append after the existing CLI/options section (after the `python -m ui.cli` examples, before the Python-API section):

```markdown
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
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_review_cli.py -v` → PASS (all 4).
Run: `python -m pytest -q` → PASS (full suite).

- [ ] **Step 7: Commit**

```bash
git add main.py ui/cli.py README.md tests/test_review_cli.py
git commit -m "Add --review flag to both entry points; document review mode"
```

---

### Task 6: Integration test + full-suite gate

**Files:**
- Test: `tests/test_review_integration.py` (new)

**Interfaces:**
- Consumes: everything from Tasks 1–4 for real: `TranceGenerator.generate()`, `ReviewSession` with its default `_default_generate` (real re-render), fake reviewer/player/inputs only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_integration.py
"""End-to-end review round: real render at 8 kHz, fake LLM, fake player."""
import json
from pathlib import Path

from ai.reviewer import Change, ReviewProposal
from core.generator import TranceGenerator
from ui.review import ReviewSession


def test_review_round_renders_new_bpm_with_same_seed(tmp_path):
    gen = TranceGenerator(style="goa", seed=8, length_minutes=3, output_dir=tmp_path,
                          sample_rate=8000, verbose=False)
    result = gen.generate(render_audio=True, master=False)
    assert result["audio_path"] and not result["errors"], result["errors"]

    def reviewer(note, params, history):
        return ReviewProposal("slower", [Change("bpm", 138, "integration")], [])

    class FakePlayer:
        def listen(self): pass
        def seek(self, s): pass
        def rewind(self): pass
        def stop(self): pass

    inputs = iter(["slower", "y", "q"])
    lines = []
    session = ReviewSession(gen, result, master=False, reviewer=reviewer,
                            player_factory=lambda p: FakePlayer(),
                            input_fn=lambda prompt: next(inputs),
                            out=lines.append)
    summary = session.run()

    history = json.loads(Path(session.history_path).read_text(encoding="utf-8"))
    round0, round1 = history["rounds"]
    assert round0["params"]["bpm"] == 142
    assert round1["params"]["bpm"] == 138
    assert round1["params"]["scale"] == round0["params"]["scale"]
    assert round1["params"]["key"] == round0["params"]["key"]
    assert Path(round1["audio_path"]).exists()
    assert Path(round1["audio_path"]) != Path(round0["audio_path"])
    assert summary["applied_rounds"] == 1
    assert summary["final_audio"] == round1["audio_path"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_review_integration.py -v`
Expected: PASS already if Tasks 1–4 are correct (this is a gate, not a driver — if it fails, a Task 1–4 assumption broke; fix before proceeding).

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS — old 45 tests + ~45 new (length, reviewer, player, loop, cli, integration). Note: several tests now render 3-minute tracks and are noticeably slower; that is expected (spec §8).

Manual check (no tkinter harness, spec §8): `python main.py --gui` — the Length dropdown must list 3.0–6.0 in 0.5 steps (plus `auto`), and typing `7` must show the generator's "Length must be between 3 and 6 minutes" error dialog.

- [ ] **Step 4: Commit**

```bash
git add tests/test_review_integration.py
git commit -m "Add end-to-end review-round integration test"
```

---

### Task 7: Push branch + open PR

**Files:**
- None (remote only). Token file: `Github Token- 30 days- from 14.9.26.txt` in the repo root — gitignored, never committed.

- [ ] **Step 1: Final verification**

Run: `python -m pytest -q` and `git status --short`
Expected: all tests green; working tree clean except the ignored token file.

- [ ] **Step 2: Push the feature branch**

```powershell
$token = (Get-Content -Raw "Github Token- 30 days- from 14.9.26.txt").Trim()
git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push "https://StepenkoAnatoli:${token}@github.com/StepenkoAnatoli/HighTrance.git" feature/human-review
```

(Plain pushes intermittently fail with `curl 52` on this network — the HTTP/1.1 + buffer flags are the known-working recipe.)

- [ ] **Step 3: Verify the push**

```powershell
git ls-remote origin refs/heads/feature/human-review
```
Expected: hash matches local `git rev-parse HEAD`.

- [ ] **Step 4: Open the PR**

```powershell
$headers = @{ Authorization = "token $token"; Accept = "application/vnd.github+json" }
$body = @{
  title = "Add terminal human-review loop (listen → note → LLM proposal → confirm → re-render)"
  head  = "feature/human-review"
  base  = "main"
  body  = @"
## What

* Interactive ``--review`` mode: in-app WAV player (Space/J/L/Enter), free-form notes interpreted by a configurable OpenAI-compatible LLM, printed diff with explicit ``y/N`` confirmation, same-seed re-render.
* Local validator is the single source of truth: only bpm/intensity/key/length can change; invalid proposals are rejected and shown, never applied.
* Hard app-wide length limit 3-6 minutes (defaults, auto range, CLI/GUI/README fallout fixed).
* ``history.json`` per review session (crash-safe, per-round flush), rollback on failed renders.
* New deps: ``sounddevice``, ``openai``. Spec: ``docs/superpowers/specs/2026-10-08-human-review-design.md``.

## Tests

``python -m pytest -q`` — full suite green (length/reviewer/player/loop/CLI/integration coverage added).
"@
}
Invoke-RestMethod -Uri "https://api.github.com/repos/StepenkoAnatoli/HighTrance/pulls" -Method Post -Headers $headers -Body ($body | ConvertTo-Json -Depth 3)
```

- [ ] **Step 5: Report**

Post the PR URL and the test count in the final summary.
