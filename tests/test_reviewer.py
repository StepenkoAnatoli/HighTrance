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
