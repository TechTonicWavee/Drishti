"""Chat route.

Streams model output to the browser over Server-Sent Events, choosing the
model automatically via `app.services.router`.

Two entry points expose the *same* stream, because the browser's native
EventSource can only issue GET requests and therefore cannot consume a
streaming POST:

    POST /chat          — the canonical API; body is {"message", ...}.
                          Used by curl and by any client that can read a
                          streaming response body.
    GET  /chat/stream   — the same stream with the fields as query parameters,
                          so `new EventSource(...)` works unmodified.

Both delegate to `_sse_events`, so there is one implementation of the
streaming behaviour and no chance of the two drifting apart.

Frames on the wire:

    event: routing        one per turn, always first — which agent was picked
    data:  {"delta": ...} one per token
    event: stream-error   the model failed mid-stream
    event: done           terminal; the client must close the EventSource
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.dependencies import get_model_client
from app.services.model_client import ModelServingClient, ModelServingError
from app.services.router import Task, classify

router = APIRouter(tags=["chat"])

# Human-readable name per task, shown in the UI next to each answer.
_AGENT_NAMES: dict[Task, str] = {
    "reasoning": "Reasoning Agent",
    "coding": "Coding Agent",
    "vision": "Vision Agent",
}

_VISION_NOT_IMPLEMENTED = (
    "Image understanding is not wired up yet. This turn was routed to the "
    "vision agent because an image was attached, but no vision model is "
    "configured. Ask a text question, or send the message without the "
    "attachment."
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    # Optional. Omit it and the router picks the model; supply it to override.
    model: str | None = Field(default=None, min_length=1)
    has_attachment: bool = False
    attachment_name: str | None = None


@dataclass(frozen=True)
class Route:
    task: Task
    model: str
    agent: str
    reason: str
    implemented: bool


def _choose(
    message: str,
    override: str | None,
    has_attachment: bool,
    attachment_name: str | None,
) -> Route:
    """Classify the turn and resolve it to a concrete model."""
    decision = classify(message, has_attachment, attachment_name)

    if override:
        # Still classified above, so the override is recorded in router.log
        # alongside what the router would have picked on its own.
        return Route(
            task=decision.task,
            model=override,
            agent=_AGENT_NAMES[decision.task],
            reason=f"caller override (router suggested: {decision.reason})",
            implemented=True,
        )

    models: dict[Task, str | None] = {
        "reasoning": settings.reasoning_model,
        "coding": settings.coding_model,
        "vision": None,  # no vision model configured yet
    }
    model = models[decision.task]

    return Route(
        task=decision.task,
        model=model or settings.default_model,
        agent=_AGENT_NAMES[decision.task],
        reason=decision.reason,
        implemented=model is not None,
    )


def _sse(data: dict[str, object], event: str | None = None) -> str:
    """Frame one SSE message.

    The payload is JSON-encoded rather than sent raw because SSE treats a bare
    newline as a field separator, and model output is full of newlines.
    """
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data)}\n\n"


async def _sse_events(
    message: str,
    override: str | None,
    has_attachment: bool,
    attachment_name: str | None,
    client: ModelServingClient,
) -> AsyncIterator[str]:
    route = _choose(message, override, has_attachment, attachment_name)

    # Always first, so the UI can label the answer before any token arrives.
    yield _sse(
        {
            "task": route.task,
            "agent": route.agent,
            # None when nothing was actually invoked, so the UI cannot imply a
            # model produced text that it did not.
            "model": route.model if route.implemented else None,
            "reason": route.reason,
            "implemented": route.implemented,
        },
        event="routing",
    )

    if not route.implemented:
        # A known gap, not a failure: deliver it as ordinary assistant text so
        # it reads as an answer rather than an error.
        yield _sse({"delta": _VISION_NOT_IMPLEMENTED})
        yield _sse({}, event="done")
        return

    try:
        deltas = await client.chat_completion(
            model=route.model,
            messages=[{"role": "user", "content": message}],
        )
        async for delta in deltas:
            yield _sse({"delta": delta})
    except ModelServingError as exc:
        # Reported as a named event rather than an HTTP status: by the time the
        # model fails, response headers have usually already been sent.
        #
        # Named "stream-error", not "error", because EventSource dispatches its
        # own connection failures under "error" and the client must be able to
        # tell a model failure from a dropped socket.
        yield _sse({"message": str(exc)}, event="stream-error")
    finally:
        # EventSource reconnects automatically when a stream ends, so the
        # client needs an explicit signal telling it to close the connection.
        yield _sse({}, event="done")


def _stream(
    message: str,
    override: str | None,
    has_attachment: bool,
    attachment_name: str | None,
    client: ModelServingClient,
) -> StreamingResponse:
    return StreamingResponse(
        _sse_events(message, override, has_attachment, attachment_name, client),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells any reverse proxy in front of us not to buffer the stream,
            # which would defeat token-by-token delivery.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat")
async def chat(
    request: ChatRequest,
    client: ModelServingClient = Depends(get_model_client),
) -> StreamingResponse:
    """Stream a reply, routing to a model automatically."""
    return _stream(
        request.message,
        request.model,
        request.has_attachment,
        request.attachment_name,
        client,
    )


@router.get("/chat/stream")
async def chat_stream(
    message: str = Query(min_length=1),
    model: str | None = Query(default=None),
    has_attachment: bool = Query(default=False),
    attachment_name: str | None = Query(default=None),
    client: ModelServingClient = Depends(get_model_client),
) -> StreamingResponse:
    """EventSource-compatible mirror of POST /chat."""
    return _stream(message, model, has_attachment, attachment_name, client)
