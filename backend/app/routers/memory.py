"""Session lifecycle and stored user memory.

Extraction runs on an explicit end-of-session signal rather than a guess at
where a conversation stopped. Guessing would either fire mid-thought or never
fire at all, and a memory written from half a conversation is worse than none.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from app.services import memory_service
from app.services.dependencies import get_model_client
from app.services.memory_service import DEMO_USER
from app.services.model_client import ModelServingClient

router = APIRouter(tags=["memory"])


class Turn(BaseModel):
    role: str
    content: str


class SessionStart(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class SessionEnd(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    # The whole conversation may be sent. Only the user's own turns survive
    # user_utterances(), so passing more than necessary cannot leak document
    # content into memory — the filter is on this side of the wire.
    messages: list[Turn] = Field(default_factory=list)


class MemoryFact(BaseModel):
    id: int
    fact: str
    category: str
    extracted_at: str
    source_session_id: str | None = None


async def _extract_and_save(
    session_id: str,
    messages: list[dict[str, Any]],
    client: ModelServingClient,
) -> None:
    """Background work: read the user's own turns, store what is durable."""
    utterances = memory_service.user_utterances(messages)
    facts = await memory_service.extract_memory(
        utterances, DEMO_USER, client=client, session_id=session_id
    )
    memory_service.save_memory(DEMO_USER, facts, session_id)


@router.post("/session/start")
async def session_start(body: SessionStart) -> dict[str, str]:
    """Record that a session began."""
    memory_service.start_session(body.session_id, DEMO_USER)
    return {"session_id": body.session_id, "status": "started"}


@router.post("/session/end")
async def session_end(
    body: SessionEnd,
    background: BackgroundTasks,
    client: ModelServingClient = Depends(get_model_client),
) -> dict[str, str]:
    """Close a session and extract durable facts from it in the background.

    Returns immediately: extraction is a model call, and the user is usually
    closing the tab. Making them wait for it would mean it rarely completed.
    """
    memory_service.end_session(body.session_id)
    background.add_task(
        _extract_and_save,
        body.session_id,
        [turn.model_dump() for turn in body.messages],
        client,
    )
    return {"session_id": body.session_id, "status": "ended"}


@router.get("/memory/{user_id}", response_model=list[MemoryFact])
async def read_memory(user_id: str) -> list[MemoryFact]:
    """Stored facts for a user. Debug and inspection use."""
    return [MemoryFact(**row) for row in memory_service.list_memory(user_id)]


@router.delete("/memory/{user_id}")
async def clear_memory(user_id: str) -> dict[str, int | str]:
    """Forget everything stored for a user."""
    return {"user_id": user_id, "removed": memory_service.forget(user_id)}
