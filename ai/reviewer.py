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
