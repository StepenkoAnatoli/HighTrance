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
                    try:
                        player.listen()
                    except PlaybackError as e:
                        # Player opens its stream lazily on first listen, so the
                        # failure can surface here instead of at construction.
                        self._playback_broken = True   # permanent: no per-round retry
                        player = None
                        self.out(f"No audio device ({e}) — listen manually.")
                if player is None:
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
