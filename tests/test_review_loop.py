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
    # NOTE(plan deviation): this assertion originally sat after session2.run(),
    # where `not converted` and `len(converted) == 1` contradict each other;
    # moved here to check the WAV invariant before the MP3 session converts.
    assert wav_summary["final_audio"].endswith(".wav") and not converted
    session2, _, _ = build(tmp_path, final_format="mp3", inputs=["q"],
                           generate_fn=lambda p: pytest.fail("no render"))
    mp3_summary = session2.run()
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
