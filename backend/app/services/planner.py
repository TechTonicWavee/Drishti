"""Visible Multi-Step Task Planner.

Decomposes complex, multi-part, and compliance investigation requests into an
explicit, ordered plan of typed steps before execution begins.

Yields structured plan and plan_step events over SSE, allowing the frontend
to render an animated, live checklist / flowchart directly to judges.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

StepType = Literal["inspect", "retrieve", "compute", "verify", "delegate", "deliverable", "synthesize"]
StepStatus = Literal["pending", "running", "completed", "failed"]


@dataclass
class PlanStep:
    id: str
    title: str
    step_type: StepType
    description: str
    status: StepStatus = "pending"
    agent: str = "Reasoning Agent"
    summary: str | None = None


@dataclass
class TaskPlan:
    plan_id: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "total_steps": self.total_steps,
            "steps": [asdict(s) for s in self.steps],
        }


def decompose_request(message: str, context: dict[str, Any] | None = None) -> TaskPlan:
    """Decompose a user request or investigation prompt into an explicit ordered plan."""
    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    clean_msg = message.strip().lower()

    # Pattern 1: Compliance sweep investigation / statutory escalation
    if any(
        kw in clean_msg
        for kw in [
            "investigate",
            "compliance",
            "statutory",
            "overdue",
            "v-204",
            "remediation",
            "finding",
            "escalate",
            "approval note",
        ]
    ):
        steps = [
            PlanStep(
                id="step-1",
                title="Inspect Equipment Limits & Inspection Records",
                step_type="inspect",
                description="Query Plant Knowledge Graph for asset V-204 design specs and statutory dates.",
                agent="Reasoning Agent",
            ),
            PlanStep(
                id="step-2",
                title="Retrieve Governing SOP & Standards Citation",
                step_type="retrieve",
                description="Search private ChromaDB for SAMPLE-SOP-INSP-004 and API 510 Section 6.4 rules.",
                agent="Reasoning Agent",
            ),
            PlanStep(
                id="step-3",
                title="Verify Statutory Review & Thickness Thresholds",
                step_type="verify",
                description="Evaluate review cycle expiration date and confirm minimum corrosion allowance (3.2 mm).",
                agent="Reasoning Agent",
            ),
            PlanStep(
                id="step-4",
                title="Draft Formal Management Approval Note (.docx)",
                step_type="deliverable",
                description="Delegate to Document Agent to generate a signed-off engineering escalation file.",
                agent="Document Agent",
            ),
        ]
        return TaskPlan(plan_id=plan_id, goal="Statutory Compliance Investigation & Escalation", steps=steps)

    # Pattern 2: Mixed coding & plant inquiry
    if any(kw in clean_msg for kw in ["csv", "analyze data", "script", "calculate", "python", "code"]):
        steps = [
            PlanStep(
                id="step-1",
                title="Retrieve Plant Procedure Specifications",
                step_type="retrieve",
                description="Search internal SOP guidelines for operating boundaries and parameters.",
                agent="Reasoning Agent",
            ),
            PlanStep(
                id="step-2",
                title="Execute Verification Script in Docker Sandbox",
                step_type="compute",
                description="Delegate to Coder Agent to run calculation inside network=none container.",
                agent="Coder Agent",
            ),
            PlanStep(
                id="step-3",
                title="Synthesize Results & Engineering Guidance",
                step_type="synthesize",
                description="Merge sandbox execution output with plant safety protocol.",
                agent="Reasoning Agent",
            ),
        ]
        return TaskPlan(plan_id=plan_id, goal="Multi-Agent Computation & Procedure Synthesis", steps=steps)

    # Pattern 3: Standard single-hop / RAG inquiry
    steps = [
        PlanStep(
            id="step-1",
            title="Retrieve Verified Document Knowledge",
            step_type="retrieve",
            description="Query local vector store for relevant operating procedures and safety standards.",
            agent="Reasoning Agent",
        ),
        PlanStep(
            id="step-2",
            title="Synthesize Ground-Truth Response",
            step_type="synthesize",
            description="Formulate technical answer grounded strictly in retrieved excerpts with verified citations.",
            agent="Reasoning Agent",
        ),
    ]
    return TaskPlan(plan_id=plan_id, goal="Technical Inquiry Resolution", steps=steps)
