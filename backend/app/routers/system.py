"""System introspection.

Reports what the process has actually done, so the air-gap claim can be
checked at a glance instead of taken on trust.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import outbound

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
