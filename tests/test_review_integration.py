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
