"""Thread listing and transcript retrieval.

Read-only. Threads are created and appended to as a side effect of chatting;
see app/routers/chat.py.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import thread_service
from app.services.memory_service import DEMO_USER

router = APIRouter(prefix="/threads", tags=["threads"])


class ThreadSummary(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    preview: str
    message_count: int


class ThreadMessage(BaseModel):
    message_id: str
    role: str
    content: str
    agent_trace_summary: str | None = None
    created_at: str


@router.get("", response_model=list[ThreadSummary])
async def list_threads(
    user_id: str = Query(default=DEMO_USER),
) -> list[ThreadSummary]:
    """Threads for a user, newest first — the sidebar's data."""
    return [ThreadSummary(**t) for t in thread_service.list_threads(user_id)]


@router.get("/{thread_id}/messages", response_model=list[ThreadMessage])
async def thread_messages(thread_id: str) -> list[ThreadMessage]:
    """The full transcript of one thread, oldest first."""
    if not thread_service.thread_exists(thread_id):
        raise HTTPException(status_code=404, detail="No such thread.")
    return [ThreadMessage(**m) for m in thread_service.get_thread_messages(thread_id)]
