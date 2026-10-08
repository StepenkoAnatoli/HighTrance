# Design: Gradio web UI (step 3 of roadmap)

**Date:** 2026-10-08 (rev. 3 — after two adversarial review rounds: 19 findings + 4 re-review issues closed) · **Status:** ready for implementation · **Branch:** `feature/gradio-web`

Citation labels: **§2 rN** = Context-table row N; **fN** = adversarial-review finding N.

## 1. Goal

A browser UI for the generator, launched with `python main.py --web`: set the
global parameters, press Generate, watch progress, listen in the browser,
download MIDI/WAV — without touching the existing Tkinter GUI or CLI.

Scope source: the "should we add this feature? / Gradio" sections of
`C:\Users\PC\Desktop\next for the  hightrance.txt`. **The snippets there are
stale and are not used verbatim** (see §2, rows 10–12).

## 2. Context (verified facts, this machine — evidence per row)

| # | Fact | Evidence |
|---|---|---|
| 1 | `TranceGenerator.__init__(style, bpm, length_minutes, key, seed, intensity, output_dir='output', scale, sample_rate, bit_depth, audio_format, renderer, soundfont, verbose)` | `inspect.signature` run 2026-10-08 |
| 2 | `generate(render_audio=False, audio_format=None, song=None, progress=None, master=None) -> Dict`; `audio_format=None` falls back to constructor `audio_format` (`generator.py:194`); renderer/soundfont are **constructor** args (`generator.py:239-240`); `master=None` honours `MASTERING["enabled"]`; errors never kill the MIDI (`generator.py:262` keeps `audio_path` + `errors[]`; mp3 failure leaves `audio_path` = WAV, `generator.py:258-262`) | `core/generator.py:183-277` |
| 3 | `progress` callback signature is `progress(message: str, fraction: float)` — called per track during **built-in** render only (`audio_render.py:113-114,122-123`; the fluidsynth path takes no progress, `audio_render.py:301`); the **compose phase has no callback** (`generator.py:207` phase text exists only via `_log`, gated on `self.verbose`, `generator.py:122-124`) | repo grep |
| 4 | Result dict keys: `style, bpm, key, scale, seed, intensity, length_minutes, duration_seconds, arrangement, sections, tracks, midi_path, audio_path, song, errors, generation_time` | `core/generator.py:217-233` |
| 5 | `generate_seed()` returns `1..MAX_SEED` (2³¹−1), **never 0** | `core/seed.py:19,24` |
| 6 | `config.settings` exposes `COMMON_KEYS` (12), `STYLES=['goa','hightech','hybrid']`, `SCALES` (10), `BPM_RANGE=(138,148)`, `LENGTH_LIMITS=(3.0,6.0)`, `DEFAULTS` (hybrid/142/4.5/Am/0.85), `MASTERING`, `OUTPUT["audio_format"]="wav"` | run 2026-10-08 + `settings.py:108` |
| 7 | **Constructor-level validation exists**: length (`generator.py:87-88`), bpm (`:77-78`), scale (`:99-100`), intensity (`:107-108`) raise `ValueError`; pinned by `tests/test_length_limits.py:39-42` | code + tests |
| 8 | `ui/` contains `cli.py`, `gui.py` (Tkinter), `review.py`, `__init__.py` — the web UI becomes `ui/web.py`. Verbose semantics differ per entry point: **Tkinter passes `verbose=False`** (`ui/gui.py:92`) and seeds its own compose-phase progress (`ui/gui.py:93`); **`main.py`/CLI pass no `verbose` → default `True`** (no `verbose` in `main.py`) | dir listing + grep |
| 9 | `main.py --gui` currently = **Tkinter**; `--review` exists; conflict-handling precedent `parser.error("--review cannot be combined with "--gui")` → exit 2 (`main.py:95-96`); the `--gui` early-return **silently ignores generation flags** (established behavior); UTF-8 stdout preamble at `main.py:13-15` / `ui/cli.py:14-16` (cp1252 console crash on `❌`) | code |
| 10 | Brainstorm length slider is **6.0–9.0, default 7.0** — violates hard `LENGTH_LIMITS=(3.0,6.0)` | brainstorm file vs settings |
| 11 | Brainstorm repurposes `--gui` to Gradio and one variant **replaces `ui/gui.py` outright** — would destroy the Tkinter GUI and its flag contract | brainstorm file |
| 12 | Brainstorm's imports (`TranceGenerator(output_dir=…)`, `COMMON_KEYS`, `generate_seed`) are **valid**, but its `gradio>=4.0.0` pin is defective: pip resolves to the **newest** matching release (no tested-major floor *or* ceiling), and the snippet's other defects are rows 10–11 | brainstorm vs run 2026-10-08 |
| 13 | **gradio 6.29.1 installed and imports on Python 3.14.7** (`pip install gradio` completed 2026-10-08, 30+ packages); install = the py3.14 compatibility test, passed | pip output |
| 14 | Existing tests: **120** passing (baseline for D8); suite ~196 s; parser-test precedent `tests/test_review_cli.py:6-34` (subprocess `run()`/`ROOT` helpers, exit-2 + stderr + `--help` assertions) | last full run + file |
| 15 | `ffmpeg` **absent** (owner declined), so README:63-64's mp3 example exits 1 here; `fluidsynth` installed in step 2 at `%LOCALAPPDATA%\Programs\FluidSynth\…\bin` on **user PATH** (fresh terminals see it; already-open shells need a PATH prepend) | step-2 record |
| 16 | Gradio 6 API checked against the installed package: `Blocks.queue(default_concurrency_limit=…)` keyword exists and **defaults to 1** (auto-enabled, `blocks.py:1478`); `launch(server_name, inbrowser, share, prevent_thread_lock, server_port)` exist; `server_port=None` scans up from 7860 (`blocks.py:3111`); `Dropdown` accepts `(label, value)` tuples; `progress(frac, desc=msg)` matches `Progress.__call__`; Progress injection requires a parameter with `gr.Progress()` **default** (`helpers.py:1083-1091`) and a plain lambda adapter works (contextvars, `helpers.py:937-943`); queue position renders in the UI; **`analytics_enabled` defaults to True** (`blocks.py:1358`, `analytics.py:46`) | reviewer inspection of installed gradio |
| 17 | `.gitignore` already covers `output/`, `*.wav`, `*.mp3`, `*.mid` — **no .gitignore change needed this step** | `git check-ignore` in review |

## 3. Decisions

| # | Decision | Alternatives rejected (and why) |
|---|---|---|
| D1 | **New flag `--web` on `main.py` + `python -m ui.web`**, implemented in a new `ui/web.py`. `--web` + `--gui` or `--web` + `--review` → `parser.error` exit 2 (same precedent as §2 r9). **`--web` ignores CLI generation flags** (`--style`…`--no-master`, incl. `--output`) — **documented in README and parse-pinned by tests (f10, D8(d))** — exactly as `--gui` already does (§2 r9); the web page owns its parameters and always writes to `output/`. | Brainstorm's `--gui`-means-Gradio (breaks the established flag contract, README, and tests); replacing `ui/gui.py` (destroys a working interface); a rewritten `main.py` from the brainstorm (drops `--review`, `--no-master`, validation); erroring on generation flags with `--web` (would break the precedent `--gui` set and surprise users; silent-ignore is the house style — but it must be **documented + tested**, which f3 proved it previously wasn't). |
| D2 | **`gradio>=6.0,<7` in `requirements.txt`** under an explicit block comment `# Web UI (spec: docs/superpowers/specs/2026-10-08-gradio-web-ui-design.md)` placed after the review-mode block, before `# Testing`. Floor = tested major, ceiling = next-major drift guard. Installed now (§2 r13). | Unbounded `>=6.0` (repeat of the §2 r12 defect in reverse); `gradio>=4.0.0` from the brainstorm; commented-out-only (a documented feature that ImportError's); Streamlit/nicegui (Gradio chosen by the brainstorm: audio component + downloads built in). |
| D3 | **Single `gr.Blocks(analytics_enabled=False)` page** (telemetry off — §2 r16, f6; see D6), layout following the brainstorm but corrected: style dropdown (`STYLES` display labels), BPM slider `BPM_RANGE` default 142, **length slider `LENGTH_LIMITS` step 0.5 default 4.5** (fixes §2 r10), key dropdown `COMMON_KEYS`, scale dropdown `auto` + `SCALES` (auto → `scale=None`), seed `gr.Number(precision=0, maximum=MAX_SEED)` with **`0` = random** (documented divergence: Tkinter/`main.py --seed 0` mean literal seed 0), intensity slider 0.5–1.0, renderer dropdown `auto/builtin/fluidsynth`, format dropdown `wav/mp3`, checkboxes **render audio** (default on) and **master** (default `MASTERING["enabled"]`), Generate button; outputs: status box, `gr.Progress`, in-browser player (`gr.Audio`), MIDI download (`gr.File`), WAV/MP3 download (`gr.File`). `fluidsynth` choice on a box without the binary degrades to a visible `errors[]` line (f9 — check in D9); per-track live progress applies to the **builtin renderer only** (f9). | Copy-pasting the brainstorm snippet (§2 r10–12); dropping renderer/format (step 2 just shipped them); ZIP/waveform/history (step 4); review loop in the web (step 5+); auto bpm/key/length (CLI/Tk parity — listed in §4 Out rather than half-built here). |
| D4 | **Handler contract (full spec in §6):** re-validate length for a *friendly* status message — the **constructor remains the authoritative boundary** (§2 r7 / f12: `generator.py:87-107`); `seed in (None, 0)` → `generate_seed()`; `TranceGenerator(...)` with **default `verbose=True`** — server stdout is the phase-log channel, matching the **CLI** default (§2 r8: the Tkinter GUI instead uses `verbose=False` + its own progress seeding; the web status box can't stream mid-handler, so the console log matters — f4/f11); handler itself calls `progress(0.0, desc="Generating layers…")` **before** `generate()` (f4: compose has no callback); adapter `lambda msg, frac: progress(frac, desc=msg)`; status text from the result incl. a visible line per `result["errors"]` entry; returns `(status, player, midi, audio)` with `None` for absent `audio_path` (f1 — `gr.Audio`/`gr.File` accept `None`); any exception → `traceback.print_exc()` to server stderr, then status `❌ …` + `None` outputs — never raise into the event loop; UTF-8 stdout preamble copied from `main.py:13-15` (f11). | `verbose=False` (f4/f11: silences the only phase channel and leaves unexpected failures with **zero** server-side record); `gr.Error` raises (kills the event, no file outputs); silent `errors[]` (step-2 smoke proved mastering/mp3 failures are real); trusting client-side bounds only (f12 — friendly pre-check first, constructor authoritative). |
| D5 | **`.queue(default_concurrency_limit=1)` stated explicitly** — one generation at a time. **Observed in E2E (D9.7, verified 2026-10-08):** gradio 6's submit button *ignores* a second click while an event is running — no auto-queue, no position badge — so the practical contract is "click is ignored until the current render finishes"; the explicit concurrency-1 setting still guards parallel submissions from other tabs/clients and is env-proof against `GRADIO_DEFAULT_CONCURRENCY_LIMIT`. README documents the observed behavior. Rejected: *relying on the implicit default of 1* (obscure, env-overridable — corrected per f2; gradio 6 already defaults to 1 and auto-enables the queue). | "Rejecting parallelism against the parallel default" (f2: that default doesn't exist); dropping `.queue()` (loses the explicit env-proof contract); background-thread + polling (reinvents the queue); building a custom re-clickable queue (over-engineering for a single-user tool — the ignored click plus the progress overlay is honest feedback). |
| D6 | **Local-only, telemetry-off launch:** `server_name="127.0.0.1"`, `inbrowser=True`, `share=False`, `analytics_enabled=False` on the Blocks (§2 r16: Gradio telemetry **defaults on** — outbound calls the Tkinter GUI never made, f6), no auth, default port with Gradio's scan-up-from-7860 fallback (§2 r16). Same trust posture as Tkinter **now actually holds**. | `0.0.0.0` (LAN exposure of an unauthenticated queue); leaving telemetry on while claiming Tk parity (f6 — false claim); auth/share links (single-user local tool); custom-port flag (YAGNI; scan fallback documented). |
| D7 | **Progress in scope for this step:** status overlay `desc` from the handler before compose + per-track live bar during built-in render (adapter in D4/§6). Scope honestly per f9: **builtin renderer only** — the fluidsynth path has no progress callback; and the compose phase shows a fixed desc, not a bar. The roadmap's step-4 "progress bar" item is discharged for the web UI and remains for Tkinter/richer stages. | Shipping a 3-minute dead wait (any review blocks it); blocking step 4 (~5 lines with `gr.Progress`); promising a live bar for compose/fluidsynth (f9: no callback exists there). |
| D8 | **Tests:** (a) import + `build_ui()` returns `gr.Blocks` without launching; (b) handler unit tests with `TranceGenerator` monkeypatched: param mapping (**incl. `audio_format` → `generate()`, `renderer` → constructor, `scale="auto"` → `None`, seed 0 → random** — f1), friendly length pre-check → status (constructor remains authoritative — f12), generator raising → `❌` status + `None` outputs + traceback written, `result["errors"]` echoed into status, **`audio_path=None` → player/download `None`** (f1); (c) launch smoke: `launch(inbrowser=False, prevent_thread_lock=True)` → use the **returned `local_url` port**, `GET /` → 200, close (f19: no 7860 assumption); (d) **parser contract tests mirroring `tests/test_review_cli.py`**: `--web --gui` and `--web --review` exit 2 with the message on stderr, `main.py --help` mentions `--web`, **and `parse_arguments(["--web","--style","goa",…])` succeeds with `args.web=True`** (pins the ignore-behavior D1 promises — f3/f10). Test file `tests/test_web_ui.py` with module docstring (f19). Heavy generation stays out of pytest (§2 r14, step-2 precedent). | No tests; full browser E2E in CI; assuming port 7860; leaving the flag contract unpinned (f10). |
| D9 | **Verification protocol:** (0) `import gradio; gradio.__version__` recorded — **6.29.1, installed, py3.14 OK** (§2 r13: done); (1) full suite ≥ 120 + new tests green; (2) browser E2E: server started as a **background process** (`python main.py --web`, teardown = kill process; `inbrowser` opens a real tab — expected; waits must tolerate **multi-minute** generation, f15) → page loads → length 3, fixed seed, render on, **renderer builtin** → Generate → progress desc/bar advances → status ✅ → player has audio → both downloads → **screenshot for the owner**; (3) mp3 format (no ffmpeg) → status shows the ffmpeg note, WAV still downloadable (`errors[]` echo); (4) `renderer=fluidsynth` **with the PATH prepended** (fresh-terminal equivalent, §2 r15) → render succeeds **or** (without PATH) → status shows the FluidSynth `errors[]` line — both acceptable, record which ran; (5) `python main.py --gui` still opens Tkinter (flag regression); (6) README examples **scoped per f8**: examples needing no optional extras run verbatim; README's mp3 example is asserted to exit 1 with WAV kept (documented degraded behavior); fluidsynth README examples run with PATH prepend; (7) queue: second Generate click while busy — **observed:** the click is ignored (button loading state, no position badge, no second job — verified with a 22 s fluidsynth run and a 1.5 s MIDI-only run); README documents this and D5 was updated accordingly. | HTTP-only smoke (proves the server, not the flow); verbatim-running the mp3 example on a box without ffmpeg (guaranteed failure — f8); assuming `which("fluidsynth")` works in this shell host (§2 r15: stale PATH). |
| D10 | **README edits — enumerated (f13):** (i) Usage: new "Web UI" block (`python main.py --web`, `python -m ui.web`, localhost-only note, generation flags ignored); (ii) **`main.py` options line (~58)** gains `--web`; (iii) **Features "Interfaces" bullet (~26)** mentions the browser UI; (iv) **renderer-choice text (~75–84)** no longer claims renderer choice is `python -m ui.cli`-only (the web UI exposes it too); (v) **project structure (~152, ~157)**: `main.py … (CLI / GUI / Web)` and `ui/ … CLI, Tkinter and web UI`. Nothing else moves. | "Nothing else moves" without enumeration (f13: four locations would contradict the feature); a new doc page. |

## 4. Scope

**In:** D1 flag/module, D2 dependency, D3 UI page, D4/§6 handler, D5 queue, D6 launch posture, D7 progress, D8 tests, D9 verification, D10 README, PR.

**Out (explicit):** review loop in the web UI; ZIP bundle button, waveform display, session history (step 4); **auto values for bpm/key/length (CLI/Tkinter parity)** (f14 — half-built here or not at all; the scale dropdown's `auto` is the one deliberate exception, being a single pre-existing enum); `share=` tunnels/auth/multi-user; custom host/port/flags; `--web` on `ui/cli.py`; AI-refiner control; changing the Tkinter GUI; `.gitignore` changes (§2 r17: none needed); pedalboard/sidechain work (step 5).

## 5. Risks

| Risk | Mitigation |
|---|---|
| Gradio 6.x API drift vs remembered snippets | Pin `gradio>=6.0,<7`; every API call verified against the **installed** package during review (§2 r16); D8.(c) catches build-time breakage |
| ~~Python 3.14 install failure~~ **resolved** | gradio 6.29.1 + deps installed cleanly on 3.14.7 (§2 r13) |
| 3–4 min request stalls / browser timeouts during generation | Gradio's queue holds the connection (no proxy on localhost); D9.2 exercises the real path with multi-minute waits |
| Unexpected handler error kills the UI thread | D4/§6 catch-all + `traceback.print_exc()` server-side; D8.(b) pins it |
| Status box can't update mid-handler → user sees nothing for minutes | §6 mandates the pre-call `progress(0.0, desc=…)` overlay (f4); final status on return; server stdout carries the full phase log (`verbose=True`) |
| Telemetry/egress surprises the owner | `analytics_enabled=False` (f6/D6) — no Gradio egress; documented |
| First run opens a browser tab / headless-SSH surprise | `inbrowser=True` only fires where a browser exists; bind stays 127.0.0.1; README notes both |
| Stale-PATH shells in verification misreport fluidsynth | D9.4 preflight with explicit PATH prepend (step-2 precedent), record fresh-terminal equivalent |

## 6. Handler contract (normative)

```python
def generate_track(style, bpm, length, key, scale, seed, intensity,
                   renderer, audio_format, render_audio, master,
                   progress=gr.Progress()):        # positional, Progress default is required
    -> (status: str, player: str|None, midi_file: str|None, audio_file: str|None)
```

| UI control | Mapping | Rule |
|---|---|---|
| `style` | `TranceGenerator(style=…)` | value ∈ `STYLES` (dropdown values, labels display-only) |
| `bpm` | `bpm=` | slider `BPM_RANGE`; constructor is authoritative (f12) |
| `length` | `length_minutes=` | friendly pre-check vs `LENGTH_LIMITS` → status; **constructor authoritative** (§2 r7) |
| `key` | `key=` | ∈ `COMMON_KEYS` |
| `scale` | `scale=` | `"auto"` → `None` |
| `seed` | `seed=` | `None`/`0` → `generate_seed()` (never 0 downstream; §2 r5) |
| `intensity` | `intensity=` | slider 0.5–1.0 |
| `renderer` | constructor `renderer=` | ∈ `RENDERERS` |
| `audio_format` | **`generate(audio_format=…)`** | `"wav"`/`"mp3"`; mp3 failure keeps WAV + `errors[]` (f1, §2 r2) |
| `render_audio` | `generate(render_audio=…)` | |
| `master` | `generate(master=…)` | explicit bool (not `None`) |
| (none) | constructor `output_dir="output"`, `verbose=True` (default) | web always writes `output/` (D1); stdout = phase log (§2 r8) |
| — | **before `generate()`:** `progress(0.0, desc="Generating layers…")` | compose has no callback (f4, §2 r3) |
| — | `progress=lambda msg, frac: progress(frac, desc=msg)` | adapter (f5) |
| result | status ← summary + **one line per `result["errors"]`**; player/midi/audio ← `result["…_path"] or None` | `audio_path is None` → `None` outputs (f1) |
| exception | `traceback.print_exc()` → stderr; status `❌ {e}`; other outputs `None` | never raise into the event loop (f11) |
