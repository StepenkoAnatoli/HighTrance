# Human Review Loop — Design Spec

**Date:** 2026-10-08
**Status:** Approved (sections 1–5 approved by user, 2026-10-08; spec review issues fixed 2026-10-08)
**Scope:** New terminal review mode: listen in-app → type free-form notes → LLM proposes global-param changes → confirm → same-seed re-render.

## 1. Problem & Goal

Today a render is a one-shot: generate, listen in an external player, tweak CLI flags, run again. The goal is a review loop *inside* the program where a human listens to the current track, describes what should change in plain language ("slower but keep the energy"), and the program re-renders the same song with adjusted global parameters — preserving the seed so the song stays recognizably identical.

## 2. Decisions (with rejected alternatives)

| # | Decision | Rejected alternative & why |
|---|----------|----------------------------|
| D1 | **Scope: global params only** — `bpm`, `intensity`, `key`, `length` | Mix tweaks, module re-rolls (`regenerate_module`), mastering tweaks, arrangement/structure changes — all deferred; user scoped v1 to global params |
| D2 | **Hard app-wide length limit 3.0–6.0 min** — `LENGTH_LIMITS`, defaults and auto-range all inside it; violations raise `ValueError` everywhere | Review-loop-only clamp (too weak), soft clamp (silent surprises) — user chose hard rejection |
| D3 | **Terminal chat, free-form notes** | Guided form, review file |
| D4 | **LLM interpreter**, OpenAI-compatible, configurable `base_url` + `api_key` + `model` (default: local Ollama) | Keyword rules (too rigid for subjective notes), Anthropic-only (vendor lock), hand-rolled HTTP (SDK chosen) |
| D5 | **Propose → confirm → render** loop: printed diff, explicit `y/N` | Auto-apply (a misread note costs a full render), conversational clarifications (extra turns), editable proposals (extra keystrokes) |
| D6 | **In-app playback** with terminal keys (play/pause/seek) via `sounddevice` | External player (chosen as *fallback* only), `winsound` (no seek) |
| D7 | **Structure: three focused units** — reviewer / player / session loop, validator as single source of truth | Formal state machine + Interpreter protocol (over-engineered for v1), inline `main.py` (untestable) |
| D8 | **Same seed every round** — only the four params change; `seed` is not in `PARAM_SPEC`, so the LLM can never re-roll the song | Seed re-roll as a review action (different song, out of scope) |
| D9 | **Never trust the LLM** — local validator range-checks every proposal; invalid changes are rejected *and shown*, never silently clamped | Clamping (hides LLM mistakes), trusting LLM output (unbounded failure) |

## 3. Configuration changes (`config/settings.py`)

```python
DEFAULTS["length"] = 4.5                 # was 7.0 — must live inside the new limits
DEFAULT_LENGTH_RANGE = (3.0, 6.0)        # was (6.0, 9.0)
LENGTH_LIMITS = (3.0, 6.0)               # was (1.0, 20.0) — enforced in TranceGenerator

REVIEW = {
    "llm": {
        "base_url": "http://localhost:11434/v1",   # any OpenAI-compatible endpoint
        "api_key": "not-needed-for-ollama",
        "model": "llama3.1:8b",
        "temperature": 0.2,
        "timeout": 60.0,
    },
    "history_rounds": 6,      # how many past rounds the LLM sees
}
```

Fallout fixes from D2 (found in design review and spec review — all verified against the code):

- `tests/test_generation.py` and `tests/test_mastering.py`: `length_minutes=1` → `3` (5 occurrences); CLI test `--length 1` → `--length 3`.
- Rejection tests: `--length 8` must raise; `length_minutes=0.1` already raises (`test_generation.py:113`) and must keep raising under the new limits.
- `ui/cli.py:87` `--length` help hardcodes `"auto' (6-9)"` → derive from `DEFAULT_LENGTH_RANGE`.
- `main.py:46` help hardcodes `"(6-9 recommended)"` → derive from `LENGTH_LIMITS`.
- `ui/gui.py:59` Length Combobox offers `["auto", 6, 6.5, 7, 7.5, 8, 8.5, 9]` — nearly all invalid after D2 → regenerate the list from `LENGTH_LIMITS` (0.5 steps) plus `"auto"`. The field stays editable; the `DEFAULTS`-driven default (4.5) remains valid.
- `README.md` contradicts D2 in four places, all must be rewritten to 3–6: line 14 ("usually 6–9 minutes"), line 52 (`--length 7` example → would raise), line 77 (`length_minutes=7` API example → would raise), line 99 ("7–9 minute render").

## 4. Component: `ai/reviewer.py`

Public API:

```python
class ReviewerError(Exception): ...          # endpoint down, timeout, unparseable output

@dataclass
class Change:
    param: str       # one of PARAM_SPEC keys
    new: float | int | str
    reason: str      # LLM's justification ("" if absent)

@dataclass
class ReviewProposal:
    reply: str                 # plain-English response to the human
    changes: list[Change]      # accepted, validated
    rejected: list[str]        # human-readable rejection reasons

def propose_changes(note: str, params: dict, history: list[dict]) -> ReviewProposal
```

- **`PARAM_SPEC`** is the single source of truth — feeds prompt *and* validator:

| param | type | range / rule |
|-------|------|--------------|
| `bpm` | numeric | `BPM_MIN..BPM_MAX` (138..148), normalized to `int` if integral |
| `intensity` | numeric | `0.0..1.0` |
| `length` | numeric | `LENGTH_LIMITS` (3.0..6.0), minutes |
| `key` | string | must parse via `core.theory.parse_key` |

- **Prompt:** system message = role, the JSON-only output contract
  `{"reply": str, "changes": [{"param": str, "new": num|str, "reason": str}]}`,
  and the rule that only `PARAM_SPEC` params may be changed. User message = current
  params (including the read-only `scale` as context) + `PARAM_SPEC` + last
  `history_rounds` history entries + the human's note. `temperature` and `timeout`
  from `REVIEW["llm"]`.
- **Client:** `openai.OpenAI(base_url=..., api_key=...)` → `chat.completions.create`.
  Parse the first balanced JSON object from the response text.
- **Validation (always local):** any param not in `PARAM_SPEC` (`seed`, `scale`,
  `style`, …) → rejected with reason; non-numeric/non-string value → rejected;
  out-of-range → rejected with the valid range in the message; bad key → rejected.
  All-rejected == zero changes. `reply` may be empty (UI then shows the proposal only).
- **Failures:** connection/timeout/API error/broken JSON after one parse attempt →
  `ReviewerError` (the loop handles retry/quit; the reviewer never exits or retries forever).

## 5. Component: `synthesis/playback.py`

```python
class Player:
    def __init__(self, path, stream_factory=None, interactive=True)  # both injectable
    def play(self); def pause(self); def seek(self, seconds: float); def stop(self)
    def listen(self)   # blocks until Enter; drives keyboard thread while interactive
```

- **Decode:** `synthesis.audio_processor.read_wav` → float32; **mono → stereo promotion
  happens here** (`read_wav` does not promote).
- **Output:** `sounddevice.OutputStream(samplerate, channels=2, callback=...)`; the
  callback copies frames starting at `position`, writes silence while paused, and
  marks EOF at end-of-buffer (`play` after EOF restarts at 0).
- **Keyboard** (no-echo thread; `msvcrt.getch()` on Windows, `termios`/`tty` on POSIX):
  `Space` = play/pause · `J`/`L` = seek −/+10 s clamped to `0..duration` ·
  `Enter` = return from `listen()` · `Ctrl+C` = `KeyboardInterrupt` (handled by the loop).
- **Degradation:** device open failure → distinct `PlaybackError`; the loop falls back
  to print-path listening **for the rest of the session** (no per-round retry): each
  round prints the WAV path and waits for Enter. Never fatal to the review session.
- **Tests:** `interactive=False` skips the keyboard thread; `stream_factory` returns a
  fake stream — no real device or keyboard is touched.

## 6. Component: `ui/review.py` + CLI wiring

Entry points: `main.py --review` and `ui/cli.py --review` (both delegate to the one
implementation). `--review` **implies** `--render-audio`, **forces WAV during the
session** (playback needs it), and is **rejected together with `--gui`**.

`--format` asymmetry: only `ui/cli.py` has `--format`. `ReviewSession` receives
`final_format` (default `"wav"`); the exit-time MP3 conversion runs only when
`final_format == "mp3"`, so `main.py --review` sessions are always WAV (no-op).

```python
class ReviewSession:
    def __init__(self, generator, result, *, master, final_format="wav",
                 reviewer=None, player_factory=None, generate_fn=None,
                 input_fn=input, out=print)     # reviewer/player/input/output injectable
    def run(self) -> dict                       # returns session summary
```

- `master`: the exact `master` value the initial run used (`None` when not specified,
  `False` with `--no-master`) — passed to every re-render so mastering choice carries through.
- `generate_fn(new_params) -> result_dict`: rebuilds and re-renders. Default
  implementation constructs a fresh `TranceGenerator` copying the round-0 generator's
  `style`, `seed`, `output_dir`, `sample_rate`, `bit_depth`, `renderer`, `soundfont`,
  `verbose`, plus `scale=<resolved scale>`, `audio_format="wav"` and the four explicit
  new params, then calls `generate(render_audio=True, master=self.master)`.
  Tests inject a fake.
- **Session dir:** `<output_dir>/reviews/review-<timestamp>/` — holds `history.json`
  only. Each round's MIDI and WAV are written through the normal `generate()` flow
  (`<output_dir>/midi/`, `<output_dir>/audio/`), exactly like round 0.
- **`scale` carry-through (identity-critical):** round 0 resolves `scale`
  (`result["scale"]`, possibly from an auto draw). It is recorded in history and passed
  **explicitly** to every re-render. It is *not* review-editable (`scale` ∉
  `PARAM_SPEC` → proposals are rejected). Rationale: `SeedManager.rng("parameters")`
  returns a fresh stream per call and auto-draws consume it positionally — round 0 with
  auto params draws scale at positions 2–4, while a round-1 call with all four params
  explicit would draw at position 1 and silently pick a different mode.

Flow:

1. **Round 0:** normal generation from CLI params (already done when `run()` starts).
   Session dir created; `history.json` written with `{style, seed, created}` and round 0:
   resolved params `{bpm, intensity, key, length, scale}` + `audio_path`.
2. **Listen:** `player.listen()` — Enter returns when the human has heard enough.
   On `PlaybackError` (first failure only) → print-path fallback for the rest of the session.
3. **Notes:** prompt `Notes (Enter = replay, q = quit):` — empty note replays from the
   top; `q` quits the session; anything else is sent to `propose_changes`.
4. **Proposal:** print the LLM reply, then the diff — accepted changes as
   `param  old → new   (reason)`, rejected ones as `rejected: <reason>`:
   ```
   LLM: "Slowing the tempo and pushing the energy a touch."
     bpm       142 → 138   (slower for the dancefloor)
     intensity 0.85 → 0.90
     rejected: length 7.2 — outside 3–6
   Apply? [y/N]
   ```
   Every note is recorded to history (see schema); zero accepted changes → no confirm
   prompt, back to step 2.
5. **Apply (`y`):** stop player → `generate_fn(params_with_changes)` →
   - Success: new WAV path, append round to `history.json` (flush every round,
     crash-safe), continue at step 2 with updated params.
   - Failure: **rollback** — params stay at the last successful values, previous WAV
     remains the active one, error recorded in history, message
     `Render failed: … — staying on previous version`, continue at step 2.
6. **Quit (`q`):** MP3 conversion of the final WAV when `final_format == "mp3"`
   (failure keeps WAV + warning) → print session summary (rounds + final path) →
   `history.json` already durable.

**Identity guarantee:** same seed → same `derive_seed(seed, "module", …)` streams →
identical note patterns for drums/bass/leads (intensity and bpm still affect velocities
and absolute timing, exactly as they do in any normal run); key changes transpose
harmony; bpm/length re-scale the arrangement over the same random streams. The session
reviews one evolving song.

**`history.json` schema** (one file per session, flushed each round; every note is
kept — including notes whose changes were rejected or not applied — so later LLM
rounds see what was already tried):

```json
{
  "created": "ISO-8601", "style": "hybrid", "seed": 123,
  "rounds": [
    {"n": 0, "params": {"bpm": 142, "intensity": 0.85, "key": "Am", "length": 4.5, "scale": "minor"},
     "audio_path": "..."},
    {"n": 1, "note": "slower", "reply": "...",
     "changes": [{"param": "bpm", "old": 142, "new": 138, "reason": "..."}],
     "rejected": ["..."], "params": {"...": "same shape as round 0"}, "audio_path": "..."},
    {"n": 2, "note": "even slower", "reply": "...", "changes": [], "rejected": ["bpm 130 — outside 138–148"]}
  ]
}
```

Rounds with zero accepted changes carry `changes: []` and no `params`/`audio_path`
(they don't change the song). Failed renders append `{"error": "..."}` and no param change.

## 7. Error handling

| Failure | Behavior |
|---|---|
| LLM down / timeout / unparseable JSON | `ReviewerError` → `[r]etry / [q]uit` prompt; note preserved on retry |
| Render failure after confirm | Rollback to last successful params/WAV; error logged to history; loop continues |
| No audio device | `PlaybackError` → print file path; print-path fallback **for the rest of the session** |
| Ctrl+C anywhere | Stop player → flush history → summary → clean exit |
| All changes rejected | Treated as zero changes (reply only, no confirm); note still recorded |
| Prompt trick ("change the seed/scale") | Not in `PARAM_SPEC` → rejected, shown to user |
| Initial generation fails / no WAV | Exit non-zero before the loop starts |
| `history.json` write failure | Warn once, keep rounds in memory, retry next round |
| MP3 conversion on exit fails | Keep WAV + warning (only reachable via `ui/cli.py --format mp3`) |
| `--review --gui` | Argparse-level error, rejected |

Carry-through every round, exactly as in the initial run: `master` flag, `scale`,
`output_dir`, sample rate, bit depth, renderer, soundfont.

## 8. Testing plan

- `tests/test_reviewer.py` (LLM client mocked, no network): prompt contains params,
  spec and history; valid proposal parses; out-of-range bpm/intensity/length rejected
  *with reasons*; unknown param, `seed` and `scale` proposals rejected; invalid key
  rejected; garbage JSON and endpoint errors → `ReviewerError`.
- `tests/test_playback.py` (fake stream, `interactive=False`): decode → float32
  stereo; mono promotion; seek clamping (before 0, past end); paused callback emits
  silence; EOF auto-stop; `play` after EOF restarts at 0.
- `tests/test_review_loop.py` (fake reviewer/player/renderer): happy path — `y` calls
  the generator with same seed + new bpm **and explicit `scale=result["scale"]`**
  (auto-scale regression guard); `n` renders nothing; render failure → rollback keeps
  old params + logs error; `q` → summary, MP3 only when `final_format="mp3"`;
  LLM error → retry keeps the note; replay on empty note; zero-change note recorded
  to history without `params`/`audio_path`.
- `tests/test_length_limits.py`: 3.0/6.0 accepted; 2.9/6.1/8/0.1 rejected with clear
  message; auto length inside 3–6; CLI `--length 3` works, `--length 8` fails.
- Legacy tests updated per §3 (note: the `1 → 3` edits triple the render-heavy tests;
  acceptable — they run at `sr=8000`, but expect a slower suite).
- GUI: no automated harness (tkinter) — manual check that the Length dropdown lists
  3.0–6.0 values and rejects typed out-of-range input with the error dialog.
- One integration test in the existing style (`sr=8000`, 3 min): real render →
  fake-LLM review round → assert bpm/duration actually changed.
- Gate: full `pytest -q` green; manual smoke run against the user's real endpoint.

## 9. Dependencies & docs

- `requirements.txt`: add `sounddevice>=0.4` and `openai>=1.0`.
- `README.md`: new "Review mode" section (usage, key bindings, LLM config) **plus the
  four D2 length fixes from §3**.
- Files touched: `config/settings.py`, `ai/reviewer.py` (new), `synthesis/playback.py`
  (new), `ui/review.py` (new), `main.py`, `ui/cli.py`, `ui/gui.py`, `requirements.txt`,
  `README.md`, `tests/*`.

## 10. Out of scope (v1)

Seed re-roll, mix/mastering/module tweaks, arrangement changes, conversational
clarifications by the LLM, editable proposals, GUI review, in-repo audio-analysis
feedback (loudness meters etc.).

## 11. Risks & mitigations

- **JSON reliability of small local models** → temperature 0.2, strict local
  validator, single parse attempt then `ReviewerError` with retry — bad output can
  never change a parameter silently.
- **Render latency per round** (full 3–6 min render) → confirm gate means renders
  only happen on explicit `y`; history shows round timing after the fact.
- **Windows keyboard handling** (`msvcrt`) is the primary target; POSIX path is a
  best-effort branch covered by the same key-map code.
- **`sounddevice` needs PortAudio** → bundled in Windows/macOS wheels; Linux users
  may need the system package (README note), and playback failure degrades to
  print-path rather than aborting.
