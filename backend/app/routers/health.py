"""Liveness endpoint.

Answers a question the frontend asks on load: is the backend up, and is it
still running in the offline posture the deployment promises?
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    offline: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    # `offline` is a hard-coded property of this build, not a probe result.
    # Drishti has no cloud client to disable, so there is nothing that could
    # flip it to false at runtime.
    return HealthResponse(status="ok", offline=True)
