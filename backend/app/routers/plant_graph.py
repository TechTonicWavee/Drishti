"""Plant Knowledge Graph and Proactive Compliance API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import plant_graph

router = APIRouter(tags=["plant-graph"])


@router.get("/plant-graph/elements")
def get_graph_elements() -> dict[str, Any]:
    """Return all equipment, procedures, revisions, and standards nodes and links."""
    return plant_graph.get_graph_elements()


@router.get("/plant-graph/equipment/{tag}")
def get_equipment_detail(tag: str) -> dict[str, Any]:
    """Return detailed information and governing procedure for a specific asset tag."""
    tag_clean = tag.strip().upper()
    if tag_clean not in plant_graph.EQUIPMENT:
        raise HTTPException(status_code=404, detail=f"Equipment '{tag}' not found in plant model.")

    eq = plant_graph.EQUIPMENT[tag_clean]
    proc = plant_graph.PROCEDURES.get(eq.governing_procedure_id)
    std = plant_graph.STANDARDS.get(proc.standard_code.replace(" ", "-")) if proc else None

    return {
        "equipment": eq,
        "procedure": proc,
        "standard": std,
    }


@router.get("/compliance/findings")
def get_compliance_findings() -> list[dict[str, Any]]:
    """Return currently active compliance findings without re-running a sweep."""
    # Run in evaluation mode (read-only without duplicate audit recording)
    findings = plant_graph.compliance_sweep(record_audit=False)
    return [
        {
            "id": f.id,
            "severity": f.severity,
            "equipment_tag": f.equipment_tag,
            "procedure_id": f.procedure_id,
            "standard_code": f.standard_code,
            "title": f.title,
            "description": f.description,
            "remediation": f.remediation,
            "created_at": f.created_at,
        }
        for f in findings
    ]


@router.post("/compliance/sweep")
def trigger_compliance_sweep() -> dict[str, Any]:
    """Proactively sweep all plant assets, procedures, and statutory review cycles."""
    findings = plant_graph.compliance_sweep(record_audit=True)
    return {
        "status": "completed",
        "timestamp": plant_graph.CURRENT_EVALUATION_DATE.isoformat(),
        "total_findings": len(findings),
        "critical_count": sum(1 for f in findings if f.severity == "CRITICAL"),
        "warning_count": sum(1 for f in findings if f.severity == "WARNING"),
        "findings": [
            {
                "id": f.id,
                "severity": f.severity,
                "equipment_tag": f.equipment_tag,
                "procedure_id": f.procedure_id,
                "standard_code": f.standard_code,
                "title": f.title,
                "description": f.description,
                "remediation": f.remediation,
                "created_at": f.created_at,
            }
            for f in findings
        ],
    }
