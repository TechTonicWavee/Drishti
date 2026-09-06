"""System introspection.

Reports what the process has actually done, so the air-gap claim can be
checked at a glance instead of taken on trust.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core import outbound
from app.services import trace

router = APIRouter(prefix="/system", tags=["system"])


class LastExternalAttempt(BaseModel):
    url: str | None = None
    at: str | None = None


class NetworkStatus(BaseModel):
    # Requests attempted to anything outside loopback and the private network.
    # Expected to stay at zero for the life of the process.
    external_call_attempts: int

    # Requests to the local model server. Reported alongside the external
    # count on purpose: a badge that only ever shows "0 external" cannot be
    # told apart from a counter that is broken, whereas a rising internal
    # count demonstrates the instrument is live.
    internal_call_count: int

    # Populated only if something external was ever attempted, so a breach is
    # attributable rather than just visible.
    last_external_attempt: LastExternalAttempt | None = None

    started_at: str
    uptime_seconds: float
    timestamp: str


@router.get("/network-status", response_model=NetworkStatus)
async def network_status() -> NetworkStatus:
    return NetworkStatus(**outbound.snapshot())


class TraceStep(BaseModel):
    at: str
    log: str
    kind: str
    label: str
    detail: str = ""
    fields: dict[str, str] = {}


class TraceResponse(BaseModel):
    steps: list[TraceStep]
    since: str


@router.get("/trace", response_model=TraceResponse)
async def agent_trace(
    since_epoch: float = Query(
        ..., description="Unix seconds; the turn's start time."
    ),
    limit: int = Query(default=60, ge=1, le=200),
) -> TraceResponse:
    """Steps recorded in the audit logs since a given moment.

    Reconstructed from the log files rather than a separate in-memory record,
    so what the UI shows and what is on disk cannot disagree.

    Correlation is by time window because the logs carry no request id. With a
    single operator — the demo case, and the normal case on a plant terminal —
    that is exact. Under concurrent use a turn would also collect its
    neighbours' steps; threading a request id through every log line is the
    fix, and is not built.
    """
    since = datetime.fromtimestamp(since_epoch)
    steps: list[dict[str, Any]] = trace.collect(since, limit)
    return TraceResponse(
        steps=[TraceStep(**step) for step in steps],
        since=since.strftime("%Y-%m-%d %H:%M:%S"),
    )
