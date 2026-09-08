"""Cross-cutting audit trail: query, verify, export.

Read-only from the API's point of view — every write happens as a side
effect of the feature that generated the event, via
app.services.audit_service.record_event. Nothing here writes.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEvent(BaseModel):
    id: int
    timestamp: str
    event_type: str
    user_id: str
    thread_id: str | None = None
    summary: str
    source_component: str


class VerifyResult(BaseModel):
    intact: bool
    total_rows: int
    first_break_at: int | None = None
    reason: str | None = None


@router.get("/events", response_model=list[AuditEvent])
async def list_events(
    event_type: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[AuditEvent]:
    """Filtered audit events, newest first."""
    rows = audit_service.query_events(
        event_type=event_type, user_id=user_id, thread_id=thread_id,
        start_time=start_time, end_time=end_time, limit=limit,
    )
    return [AuditEvent(**row) for row in rows]


@router.get("/verify", response_model=VerifyResult)
async def verify() -> VerifyResult:
    """Recompute the hash chain and report whether it matches what is stored.

    Answers what the log currently contains is internally consistent. It
    cannot see a chain that was replaced wholesale — see the watermark
    mechanism in audit_service for that half of the guarantee, surfaced as
    its own "audit_integrity_breach" event type rather than through this flag.
    """
    return VerifyResult(**audit_service.verify_chain_integrity())


@router.get("/export")
async def export(format: str = Query(default="csv")) -> StreamingResponse:
    """The full audit log as a downloadable file, oldest first."""
    if format != "csv":
        format = "csv"  # the only format built; silently normalise rather
                         # than error over a query param a demo might mistype
    csv_text = audit_service.export_csv()
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=drishti_audit_log.csv"},
    )
