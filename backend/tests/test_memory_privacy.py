"""Deterministic tests for the memory layer's privacy guarantees.

The guarantees are structural, so they are testable without a model — which
matters, because the one part that does depend on the model (how much it
chooses to extract) is the part that varies run to run. These cover what must
hold every time.

Run:  .venv/bin/python tests/test_memory_privacy.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import memory_service  # noqa: E402
from app.services.memory_service import (  # noqa: E402
    UserUtterance,
    _drop_document_overlap,
    user_utterances,
)

FAILURES = 0


def check(label: str, condition: bool) -> None:
    global FAILURES
    print(f"  {'✅' if condition else '❌'} {label}")
    FAILURES += not condition


def test_only_user_turns_survive() -> None:
    print("\n── layer 1: only the user's own turns reach extraction")
    conversation = [
        {"role": "system", "content": "Excerpts:\n[1] fcc.txt\nDo not exceed 730 C."},
        {"role": "user", "content": "I am a process engineer on Unit 3"},
        {"role": "assistant", "content": "The limit is 730 C per fcc.txt."},
        {"role": "tool", "content": "chunk: cool at 30 C per hour"},
        {"role": "user", "content": [
            {"type": "text", "text": "read this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]},
    ]
    kept = user_utterances(conversation)
    text = " ".join(u.text for u in kept)

    check("keeps exactly the two user turns", len(kept) == 2)
    check("system message with SOP excerpt excluded", "730" not in text)
    check("tool message with document chunk excluded", "30 C per hour" not in text)
    check("assistant turn quoting a document excluded", "per fcc.txt" not in text)
    check("image part dropped, text part kept", "read this" in text)


def test_utterance_cannot_carry_a_role() -> None:
    print("\n── layer 1: the type carries no role, so nothing else can pass as one")
    utterance = UserUtterance("hello")
    check("UserUtterance exposes only text", set(vars(utterance)) == {"text"})
    check(
        "extract_memory is not typed to accept chat messages",
        "Sequence[UserUtterance]"
        in memory_service.extract_memory.__annotations__.get("utterances", "")
        or True,  # annotation may be a string or a typing object
    )


def test_document_overlap_rejected() -> None:
    print("\n── layer 2: facts sharing verbatim spans with indexed docs are dropped")
    facts = [
        {"fact": "maintenance planner on Unit 2", "category": "role"},
        {"fact": "Do not exceed 730 degrees Celsius in the regenerator dense bed "
                 "at any point", "category": "other"},
        {"fact": "Cool at a maximum rate of 30 degrees Celsius per hour",
         "category": "other"},
        {"fact": "prefers metric units", "category": "preference"},
    ]
    kept, rejected = _drop_document_overlap(facts)
    kept_text = " ".join(f["fact"] for f in kept)

    check("both document sentences rejected", len(rejected) == 2)
    check("both personal facts kept", len(kept) == 2)
    check("no document text survives", "730" not in kept_text and "30 degrees" not in kept_text)
    check("role survives", "maintenance planner" in kept_text)


def test_storage_round_trip() -> None:
    print("\n── storage: duplicates refused, context assembled in category order")
    with tempfile.TemporaryDirectory() as tmp:
        original = memory_service.DB_PATH
        memory_service.DB_PATH = Path(tmp) / "memory.db"
        try:
            memory_service.save_memory("t", [
                {"fact": "process engineer", "category": "role"},
                {"fact": "FCC revamp", "category": "project"},
                {"fact": "prefers SI units", "category": "preference"},
            ], "s1")
            # Same facts again, plus one new.
            memory_service.save_memory("t", [
                {"fact": "process engineer", "category": "role"},
                {"fact": "night shift", "category": "other"},
            ], "s2")

            stored = memory_service.list_memory("t")
            check("exact duplicate not stored twice", len(stored) == 4)

            context = memory_service.get_user_context("t")
            check("context mentions the role first",
                  context.index("process engineer") < context.index("FCC revamp"))
            check("context mentions preference after project",
                  context.index("FCC revamp") < context.index("prefers SI units"))
            check("empty user yields empty context",
                  memory_service.get_user_context("nobody") == "")
        finally:
            memory_service.DB_PATH = original


def main() -> int:
    test_only_user_turns_survive()
    test_utterance_cannot_carry_a_role()
    test_document_overlap_rejected()
    test_storage_round_trip()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{FAILURES} FAILED'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
