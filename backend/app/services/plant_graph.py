"""Plant Knowledge Graph and Compliance Service.

Defines the curated deterministic equipment-and-revision knowledge layer:
    Equipment -> Governing Procedure -> Revision Chain -> Standards Reference.

Provides:
1. Deterministic graph structure for UI node-and-edge visualizer.
2. Proactive compliance sweep that scans statutory deadlines, overdue reviews,
   and revision status without requiring user prompting.
3. Cryptographic audit trail recording of compliance evaluations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Final, Literal

from app.core.logs import get_file_logger

log = get_file_logger("drishti.plant_graph", "plant_graph.log")

# Operational evaluation date (SIH 2026 benchmark date)
CURRENT_EVALUATION_DATE: Final[date] = date(2026, 9, 13)


@dataclass(frozen=True)
class RevisionRecord:
    rev: str
    date: str
    status: Literal["Archived", "Active", "Active (Review Overdue)", "Pending Sign-off"]
    notes: str


@dataclass(frozen=True)
class StandardReference:
    code: str
    title: str
    governing_body: str
    mandatory: bool
    clause_ref: str


@dataclass(frozen=True)
class ProcedureNode:
    id: str
    title: str
    unit: str
    current_revision: str
    last_reviewed: str
    next_review_due: str
    review_cycle_years: int
    standard_code: str
    revisions: list[RevisionRecord]
    doc_path: str


@dataclass(frozen=True)
class EquipmentNode:
    tag: str
    name: str
    unit: str
    criticality: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    last_inspection: str
    next_inspection_due: str
    governing_procedure_id: str
    design_spec: str
    operating_limits: dict[str, str]


@dataclass
class ComplianceFinding:
    id: str
    severity: Literal["CRITICAL", "WARNING", "INFO"]
    equipment_tag: str
    procedure_id: str
    standard_code: str
    title: str
    description: str
    remediation: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


# --- Curated Deterministic Plant Model ---------------------------------------

STANDARDS: Final[dict[str, StandardReference]] = {
    "API-510": StandardReference(
        code="API 510",
        title="Pressure Vessel Inspection Code: In-service Inspection, Rating, Repair, and Alteration",
        governing_body="American Petroleum Institute",
        mandatory=True,
        clause_ref="Section 6.4 (Periodic Statutory Inspection & Review Cycles)",
    ),
    "ASME-VIII": StandardReference(
        code="ASME Section VIII",
        title="Rules for Construction of Pressure Vessels (Div 1 & 2)",
        governing_body="American Society of Mechanical Engineers",
        mandatory=True,
        clause_ref="Division 1, Appendix M",
    ),
    "OSHA-1910": StandardReference(
        code="OSHA 1910.146",
        title="Permit-Required Confined Spaces Standard",
        governing_body="Occupational Safety and Health Administration",
        mandatory=True,
        clause_ref="1910.146(c)(5) (Atmospheric Testing & Retesting Requirements)",
    ),
    "ISO-10816": StandardReference(
        code="ISO 10816-3",
        title="Mechanical Vibration — Evaluation of Machine Vibration on Non-Rotating Parts",
        governing_body="International Organization for Standardization",
        mandatory=False,
        clause_ref="Part 3: Industrial Machines with Nominal Power above 15 kW",
    ),
    "API-521": StandardReference(
        code="API 521",
        title="Pressure-relieving and Depressuring Systems",
        governing_body="American Petroleum Institute",
        mandatory=True,
        clause_ref="Section 5.4 (Flare Header Purge Velocities & Operational Readiness)",
    ),
}

PROCEDURES: Final[dict[str, ProcedureNode]] = {
    "SAMPLE-SOP-INSP-004": ProcedureNode(
        id="SAMPLE-SOP-INSP-004",
        title="Pressure Vessel Inspection Guidelines",
        unit="Inspection & Integrity",
        current_revision="Rev 3",
        last_reviewed="2023-08-10",
        next_review_due="2026-08-10",  # Overdue relative to 2026-09-13
        review_cycle_years=3,
        standard_code="API 510",
        doc_path="pressure_vessel_inspection_guidelines.txt",
        revisions=[
            RevisionRecord("Rev 1", "2017-06-01", "Archived", "Initial plant commissioning issue"),
            RevisionRecord("Rev 2", "2020-07-15", "Archived", "Triennial review; added NDT grid inspection protocol"),
            RevisionRecord("Rev 3", "2023-08-10", "Active (Review Overdue)", "Statutory 3-year cycle expired on 2026-08-10 under API 510 6.4"),
            RevisionRecord("Rev 4", "2026-09-01", "Pending Sign-off", "Drafted update: includes automated ultrasonic thickness thresholds and escalation sign-off"),
        ],
    ),
    "SAMPLE-SOP-OPS-001": ProcedureNode(
        id="SAMPLE-SOP-OPS-001",
        title="FCC Unit Shutdown Procedure",
        unit="FCC Unit",
        current_revision="Rev 4",
        last_reviewed="2025-01-10",
        next_review_due="2027-01-10",
        review_cycle_years=2,
        standard_code="ASME Section VIII",
        doc_path="fcc_unit_shutdown_procedure.txt",
        revisions=[
            RevisionRecord("Rev 1", "2019-02-12", "Archived", "Baseline commissioning revision"),
            RevisionRecord("Rev 2", "2021-04-18", "Archived", "Updated catalyst withdrawal staging"),
            RevisionRecord("Rev 3", "2023-03-22", "Archived", "Emergency quench rate revision"),
            RevisionRecord("Rev 4", "2025-01-10", "Active", "Current standard operational revision"),
        ],
    ),
    "SAMPLE-SOP-HSE-021": ProcedureNode(
        id="SAMPLE-SOP-HSE-021",
        title="Confined Space Entry Procedure",
        unit="HSE & Safety",
        current_revision="Rev 5",
        last_reviewed="2024-11-20",
        next_review_due="2026-11-20",
        review_cycle_years=2,
        standard_code="OSHA 1910.146",
        doc_path="confined_space_entry_procedure.txt",
        revisions=[
            RevisionRecord("Rev 3", "2020-09-14", "Archived", "Initial multi-gas detector guidelines"),
            RevisionRecord("Rev 4", "2022-10-05", "Archived", "Rescue team standby requirements"),
            RevisionRecord("Rev 5", "2024-11-20", "Active", "Strict H2S limit (<5 ppm) & continuous atmospheric verification"),
        ],
    ),
    "SAMPLE-SOP-PMP-007": ProcedureNode(
        id="SAMPLE-SOP-PMP-007",
        title="Pump Vibration Limits & Monitoring",
        unit="Rotating Equipment",
        current_revision="Rev 2",
        last_reviewed="2025-03-05",
        next_review_due="2027-03-05",
        review_cycle_years=2,
        standard_code="ISO 10816-3",
        doc_path="pump_vibration_limits.txt",
        revisions=[
            RevisionRecord("Rev 1", "2022-04-01", "Archived", "Base RMS velocity thresholds"),
            RevisionRecord("Rev 2", "2025-03-05", "Active", "Zone A/B/C/D limits aligned with ISO 10816-3 Group 1"),
        ],
    ),
    "SAMPLE-SOP-FLR-009": ProcedureNode(
        id="SAMPLE-SOP-FLR-009",
        title="Flare System Operation & Purge Protocol",
        unit="Flare & Relief",
        current_revision="Rev 3",
        last_reviewed="2024-05-18",
        next_review_due="2026-05-18",  # Overdue by 118 days
        review_cycle_years=2,
        standard_code="API 521",
        doc_path="flare_system_operation.txt",
        revisions=[
            RevisionRecord("Rev 1", "2018-08-01", "Archived", "Original flare commissioning"),
            RevisionRecord("Rev 2", "2021-09-15", "Archived", "Seal drum water-level controls"),
            RevisionRecord("Rev 3", "2024-05-18", "Active (Review Overdue)", "Nitrogen purge velocity rules; review due on 2026-05-18"),
        ],
    ),
}

EQUIPMENT: Final[dict[str, EquipmentNode]] = {
    "V-204": EquipmentNode(
        tag="V-204",
        name="Overhead Flash Drum V-204",
        unit="FCC Unit",
        criticality="CRITICAL",
        last_inspection="2023-08-15",
        next_inspection_due="2026-10-15",
        governing_procedure_id="SAMPLE-SOP-INSP-004",
        design_spec="ASME Sec VIII Div 1, 3.5 MPa design pressure, SA-516 Gr 70 carbon steel",
        operating_limits={
            "Design Pressure": "3.5 MPa",
            "Operating Temp": "240 °C",
            "Minimum Corrosion Allowance": "3.2 mm",
            "Nominal Shell Thickness": "22.5 mm",
        },
    ),
    "P-101A": EquipmentNode(
        tag="P-101A",
        name="Crude Charge Centrifugal Pump A",
        unit="Crude Distillation Unit",
        criticality="HIGH",
        last_inspection="2026-02-10",
        next_inspection_due="2026-08-10",
        governing_procedure_id="SAMPLE-SOP-PMP-007",
        design_spec="API 610 BB2 Type, 450 m3/h flow, 120m differential head",
        operating_limits={
            "Max Vibration (RMS)": "4.5 mm/s (Alarm at 7.1 mm/s)",
            "Bearing Temperature": "< 85 °C",
            "Motor Rating": "350 kW",
        },
    ),
    "C-101": EquipmentNode(
        tag="C-101",
        name="FCC Main Fractionator Column",
        unit="FCC Unit",
        criticality="CRITICAL",
        last_inspection="2024-01-20",
        next_inspection_due="2028-01-20",
        governing_procedure_id="SAMPLE-SOP-OPS-001",
        design_spec="Clad steel fractionator column, 48 sieve trays, height 42m",
        operating_limits={
            "Top Temperature": "115 °C",
            "Bottom Temperature": "360 °C",
            "Overhead Pressure": "0.18 MPa",
        },
    ),
    "E-102": EquipmentNode(
        tag="E-102",
        name="Crude Preheat Exchanger Train E-102",
        unit="Crude Distillation Unit",
        criticality="HIGH",
        last_inspection="2023-09-02",
        next_inspection_due="2026-09-02",
        governing_procedure_id="SAMPLE-SOP-INSP-004",
        design_spec="TEMA AES Shell & Tube, Carbon Steel shell / Titanium tubes",
        operating_limits={
            "Shell Design Pressure": "2.2 MPa",
            "Tube Design Pressure": "3.8 MPa",
            "Max Clean Delta-P": "0.15 MPa",
        },
    ),
    "FL-01": EquipmentNode(
        tag="FL-01",
        name="High-Pressure Main Flare Stack",
        unit="Flare & Relief",
        criticality="CRITICAL",
        last_inspection="2024-06-10",
        next_inspection_due="2027-06-10",
        governing_procedure_id="SAMPLE-SOP-FLR-009",
        design_spec="120m Guyed Derrick, Smokeless sonic velocity tip with continuous pilots",
        operating_limits={
            "Continuous N2 Purge": "0.015 m/s",
            "Min Pilot Temp": "650 °C",
            "Max Relief Rate": "850 t/h",
        },
    ),
    "CS-01": EquipmentNode(
        tag="CS-01",
        name="FCC Regenerator Catalyst Standpipe Chamber",
        unit="FCC Unit",
        criticality="CRITICAL",
        last_inspection="2025-05-12",
        next_inspection_due="2027-05-12",
        governing_procedure_id="SAMPLE-SOP-HSE-021",
        design_spec="Permit-Required Confined Space (Ref SA-387-11 Cl. 2 refractory lined)",
        operating_limits={
            "Max H2S Concentration": "5 ppm (Immediate Evacuation at >= 5 ppm)",
            "Oxygen Levels": "19.5% - 23.5%",
            "Max LEL": "0% for entry (hot work <= 1%)",
        },
    ),
}


# --- Graph Elements for Visualization ---------------------------------------


def get_standard_key(standard_code: str) -> str | None:
    """Resolve a procedure's free-text `standard_code` (e.g. "ASME Section VIII")
    to its `STANDARDS` dict key (e.g. "ASME-VIII").

    Matches on the `StandardReference.code` field rather than a naive string
    transform of `standard_code` — a transform like replacing spaces with
    dashes only happens to work for "API 510" / "API 521" and silently fails
    for "ASME Section VIII", "OSHA 1910.146", and "ISO 10816-3", which do not
    become their real keys ("ASME-VIII", "OSHA-1910", "ISO-10816") that way.
    """
    return next((k for k, s in STANDARDS.items() if s.code == standard_code), None)


def get_graph_elements() -> dict[str, Any]:
    """Return nodes and edges formatted for visual rendering."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # 1. Standards Nodes
    for key, std in STANDARDS.items():
        nodes.append(
            {
                "id": f"std:{key}",
                "type": "standard",
                "label": std.code,
                "title": std.title,
                "subtitle": std.governing_body,
                "badge": "Standard",
                "color": "#10b981",  # Emerald
                "details": {
                    "Governing Body": std.governing_body,
                    "Mandatory Compliance": "Yes" if std.mandatory else "Recommended",
                    "Governing Clause": std.clause_ref,
                },
            }
        )

    # 2. Procedures Nodes & Edges to Standards
    for proc_id, proc in PROCEDURES.items():
        is_overdue = "Overdue" in proc.current_revision or (
            date.fromisoformat(proc.next_review_due) < CURRENT_EVALUATION_DATE
        )
        status_color = "#f59e0b" if not is_overdue else "#ef4444"  # Amber vs Red
        nodes.append(
            {
                "id": f"proc:{proc_id}",
                "type": "procedure",
                "label": proc_id,
                "title": proc.title,
                "subtitle": f"{proc.unit} · {proc.current_revision}",
                "badge": "SOP" if not is_overdue else "Review Overdue",
                "color": status_color,
                "is_overdue": is_overdue,
                "details": {
                    "Current Revision": proc.current_revision,
                    "Last Reviewed": proc.last_reviewed,
                    "Next Review Due": proc.next_review_due,
                    "Review Cycle": f"{proc.review_cycle_years} Years",
                    "Standard Reference": proc.standard_code,
                    "Revisions": [asdict(r) for r in proc.revisions],
                },
            }
        )

        # Edge from Procedure to Standard
        std_key = get_standard_key(proc.standard_code)
        if std_key:
            edges.append(
                {
                    "source": f"proc:{proc_id}",
                    "target": f"std:{std_key}",
                    "label": "governed by",
                    "animated": False,
                }
            )

        # Revision chain subnodes
        for rev in proc.revisions:
            rev_node_id = f"rev:{proc_id}:{rev.rev.replace(' ', '_')}"
            nodes.append(
                {
                    "id": rev_node_id,
                    "type": "revision",
                    "label": f"{proc_id} {rev.rev}",
                    "title": rev.status,
                    "subtitle": rev.date,
                    "badge": rev.rev,
                    "color": "#8b5cf6" if "Active" not in rev.status else ("#ef4444" if "Overdue" in rev.status else "#3b82f6"),
                    "details": {
                        "Revision": rev.rev,
                        "Release Date": rev.date,
                        "Status": rev.status,
                        "Notes": rev.notes,
                    },
                }
            )
            edges.append(
                {
                    "source": rev_node_id,
                    "target": f"proc:{proc_id}",
                    "label": "revision of",
                    "style": "dashed",
                }
            )

    # 3. Equipment Nodes & Edges to Procedures
    for tag, eq in EQUIPMENT.items():
        nodes.append(
            {
                "id": f"eq:{tag}",
                "type": "equipment",
                "label": tag,
                "title": eq.name,
                "subtitle": f"{eq.unit} · {eq.criticality}",
                "badge": eq.criticality,
                "color": "#06b6d4",  # Cyan
                "details": {
                    "Asset Tag": eq.tag,
                    "Unit": eq.unit,
                    "Criticality": eq.criticality,
                    "Design Specification": eq.design_spec,
                    "Last Inspection": eq.last_inspection,
                    "Next Inspection Due": eq.next_inspection_due,
                    "Governing Procedure": eq.governing_procedure_id,
                    "Operating Limits": eq.operating_limits,
                },
            }
        )

        edges.append(
            {
                "source": f"eq:{tag}",
                "target": f"proc:{eq.governing_procedure_id}",
                "label": "governed by",
                "animated": True,
            }
        )

    return {"nodes": nodes, "edges": edges, "evaluation_date": CURRENT_EVALUATION_DATE.isoformat()}


# --- Proactive Compliance Sweep ---------------------------------------------


def compliance_sweep(*, record_audit: bool = True) -> list[ComplianceFinding]:
    """Inspect all equipment, revision chains, and statutory intervals.

    Evaluates whether governing procedures have exceeded their mandatory review cycle
    under their governing standard. Operates proactively without user prompting.
    """
    findings: list[ComplianceFinding] = []

    for proc_id, proc in PROCEDURES.items():
        due_date = date.fromisoformat(proc.next_review_due)
        if due_date < CURRENT_EVALUATION_DATE:
            days_overdue = (CURRENT_EVALUATION_DATE - due_date).days
            affected_eq = [tag for tag, eq in EQUIPMENT.items() if eq.governing_procedure_id == proc_id]
            affected_str = ", ".join(affected_eq) or "All assigned assets"

            findings.append(
                ComplianceFinding(
                    id=f"FIND-OVERDUE-{proc_id}",
                    severity="CRITICAL",
                    equipment_tag=affected_eq[0] if affected_eq else "PLANT-WIDE",
                    procedure_id=proc_id,
                    standard_code=proc.standard_code,
                    title=f"Statutory Procedure Review Overdue: {proc_id} ({proc.title})",
                    description=(
                        f"Governing procedure {proc_id} ({proc.current_revision}) passed its mandatory "
                        f"{proc.review_cycle_years}-year review deadline on {proc.next_review_due} "
                        f"({days_overdue} days overdue under {proc.standard_code}). "
                        f"Governs operational safety of {affected_str}."
                    ),
                    remediation=(
                        f"Perform technical review against {proc.standard_code}. Draft revision Rev 4 exists "
                        f"in pending state. Generate management escalation approval note to expedite sign-off."
                    ),
                )
            )

    # Equipment inspection horizon checks (within 45 days)
    for tag, eq in EQUIPMENT.items():
        due_date = date.fromisoformat(eq.next_inspection_due)
        delta_days = (due_date - CURRENT_EVALUATION_DATE).days
        if delta_days < 45:
            findings.append(
                ComplianceFinding(
                    id=f"FIND-INSP-{tag}",
                    severity="WARNING" if delta_days > 0 else "CRITICAL",
                    equipment_tag=tag,
                    procedure_id=eq.governing_procedure_id,
                    standard_code=PROCEDURES[eq.governing_procedure_id].standard_code,
                    title=f"Statutory NDT Inspection Window: Asset {tag} ({eq.name})",
                    description=(
                        f"Asset {tag} has inspection due on {eq.next_inspection_due} ({delta_days} days remaining). "
                        f"Requires ultrasonic thickness grid survey per {eq.governing_procedure_id}."
                    ),
                    remediation="Verify NDT team mobilization and confirm thickness inspection schedule.",
                )
            )

    log.info(
        "compliance_sweep_completed | findings_count=%d | critical=%d",
        len(findings),
        sum(1 for f in findings if f.severity == "CRITICAL"),
    )

    if record_audit:
        try:
            from app.services.audit_service import record_event

            record_event(
                "compliance_sweep",
                "system_proactive_agent",
                f"Compliance sweep evaluated 6 assets, 5 SOPs; identified {len(findings)} findings ({sum(1 for f in findings if f.severity == 'CRITICAL')} critical)",
                source_component="plant_graph.py",
            )
        except Exception as exc:
            log.warning("audit recording for compliance sweep failed: %s", exc)

    return findings
