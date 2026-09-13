from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.reasoning_agent import _expand_query, verify_and_clean_citations
from app.services.router import classify, is_mixed_request


def test_mixed_request_detection():
    """Verify that mixed requests (coding + plant procedure) are detected and routed."""
    msg = "Analyze CSV data [DATA]. Then explain FCC procedure."
    assert is_mixed_request(msg) is True

    route = classify(msg)
    assert route.task == "reasoning"
    assert "mixed signals" in route.reason


def test_pure_coding_routing():
    """Verify pure coding requests still route directly to coding agent."""
    assert is_mixed_request("write two sum in java") is False
    route = classify("write two sum in java")
    assert route.task == "coding"


def test_pure_reasoning_routing():
    """Verify pure plant inquiries route to reasoning agent."""
    assert is_mixed_request("Summarize the FCC shutdown procedure.") is False
    route = classify("Summarize the FCC shutdown procedure.")
    assert route.task == "reasoning"


def test_query_expansion_for_followup():
    """Verify follow-up queries expand acronyms and inherit previous turn context."""
    context = {
        "history": [
            {"role": "user", "content": "What are the rules for confined space entry?"},
            {"role": "assistant", "content": "You must obtain a permit..."},
        ]
    }
    expanded = _expand_query("What is the H2S limit?", context)
    assert "hydrogen sulphide" in expanded
    assert "confined space" in expanded


def test_citation_verification_correction():
    """Verify fabricated SOP reference numbers are corrected to ground truth."""
    hits = [
        {
            "source": "confined_space_entry_procedure.txt",
            "text": "Document reference: SAMPLE-SOP-HSE-021, Revision 5. Hydrogen sulphide below 5 ppm.",
        }
    ]
    # Model hallucinated 022 instead of 021
    hallucinated_reply = (
        "The H2S limit is 5 ppm. Document: SAMPLE-SOP-HSE-022, Revision 5."
    )
    cleaned = verify_and_clean_citations(hallucinated_reply, hits)
    assert "SAMPLE-SOP-HSE-021" in cleaned
    assert "SAMPLE-SOP-HSE-022" not in cleaned


def test_citation_verification_strips_fake_when_no_hits():
    """Verify fake document citations are removed when no internal documents match."""
    general_reply = (
        "Photosynthesis is the process by which green plants convert light into energy.\n"
        "Document: SAMPLE-SOP-HSE-099\n"
        "It produces oxygen and glucose."
    )
    cleaned = verify_and_clean_citations(general_reply, hits=[])
    assert "SAMPLE-SOP-HSE-099" not in cleaned
    assert "Photosynthesis" in cleaned
    assert "oxygen and glucose" in cleaned
