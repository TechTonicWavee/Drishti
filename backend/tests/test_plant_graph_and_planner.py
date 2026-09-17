"""Tests for Plant Knowledge Graph and Multi-Step Task Planner."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plant_graph import compliance_sweep, get_graph_elements
from app.services.planner import decompose_request


def test_compliance_sweep_detects_overdue_sop():
    """Verify that proactive compliance sweep detects overdue API 510 statutory review."""
    findings = compliance_sweep(record_audit=False)
    assert len(findings) >= 2

    # Verify critical overdue SOP finding for pressure vessel inspection
    v204_finding = next((f for f in findings if "SAMPLE-SOP-INSP-004" in f.procedure_id), None)
    assert v204_finding is not None
    assert v204_finding.severity == "CRITICAL"
    assert v204_finding.equipment_tag == "V-204"
    assert v204_finding.standard_code == "API 510"
    assert "overdue" in v204_finding.description.lower()
    assert "approval note" in v204_finding.remediation.lower()


def test_graph_elements_structure():
    """Verify graph nodes, edges, and relationship links for the visual explorer."""
    graph = get_graph_elements()
    nodes = graph["nodes"]
    edges = graph["edges"]

    node_types = {n["type"] for n in nodes}
    assert "equipment" in node_types
    assert "procedure" in node_types
    assert "revision" in node_types
    assert "standard" in node_types

    # Verify edge connecting V-204 to SAMPLE-SOP-INSP-004
    v204_edge = next(
        (e for e in edges if e["source"] == "eq:V-204" and e["target"] == "proc:SAMPLE-SOP-INSP-004"),
        None,
    )
    assert v204_edge is not None

    # Verify edge connecting SAMPLE-SOP-INSP-004 to API-510
    sop_edge = next(
        (e for e in edges if e["source"] == "proc:SAMPLE-SOP-INSP-004" and e["target"] == "std:API-510"),
        None,
    )
    assert sop_edge is not None


def test_planner_decomposition_compliance_investigation():
    """Verify multi-step plan decomposition for compliance and statutory escalation."""
    msg = "Investigate compliance finding for V-204, review governing SOP, and draft management approval note."
    plan = decompose_request(msg)
    assert plan.total_steps == 4
    step_types = [s.step_type for s in plan.steps]
    assert step_types == ["inspect", "retrieve", "verify", "deliverable"]
    assert plan.steps[3].agent == "Document Agent"


def test_planner_decomposition_computation():
    """Verify plan decomposition for mixed computation and procedure synthesis."""
    msg = "Analyze CSV data and verify against FCC shutdown limits in python."
    plan = decompose_request(msg)
    assert plan.total_steps == 3
    step_types = [s.step_type for s in plan.steps]
    assert step_types == ["retrieve", "compute", "synthesize"]
    assert plan.steps[1].agent == "Coder Agent"


def test_planner_decomposition_single_hop():
    """Verify plan decomposition for standard technical inquiry."""
    msg = "What is the maximum allowed H2S concentration for confined space entry?"
    plan = decompose_request(msg)
    assert plan.total_steps == 2
    step_types = [s.step_type for s in plan.steps]
    assert step_types == ["retrieve", "synthesize"]
