"""Chat route.

Streams model output to the browser over Server-Sent Events.

Two entry points expose the *same* stream, because the browser's native
EventSource can only issue GET requests and therefore cannot consume a
streaming POST:

    POST /chat          — the canonical API; body is {"message", "model"}.
                          Used by curl and by any client that can read a
                          streaming response body.
    GET  /chat/stream   — the same stream with the fields as query parameters,
                          so `new EventSource(...)` works unmodified.

Both delegate to `_sse_events`, so there is one implementation of the
streaming behaviour and no chance of the two drifting apart.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.model_client import ModelServingClient, ModelServingError
from app.services.dependencies import get_model_client

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str = Field(default=settings.default_model, min_length=1)


def _sse(data: dict[str, object], event: str | None = None) -> str:
    """Frame one SSE message.

    The payload is JSON-encoded rather than sent raw because SSE treats a bare
    newline as a field separator, and model output is full of newlines.
    """
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data)}\n\n"


async def _sse_events(
    message: str,
    model: str,
    client: ModelServingClient,
) -> AsyncIterator[str]:
    try:
        deltas = await client.chat_completion(
            model=model,
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


def _stream(message: str, model: str, client: ModelServingClient) -> StreamingResponse:
    return StreamingResponse(
        _sse_events(message, model, client),
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
    """Stream a reply to a single message."""
    return _stream(request.message, request.model, client)


@router.get("/chat/stream")
async def chat_stream(
    message: str = Query(min_length=1),
    model: str = Query(default=settings.default_model, min_length=1),
    client: ModelServingClient = Depends(get_model_client),
) -> StreamingResponse:
    """EventSource-compatible mirror of POST /chat."""
    return _stream(message, model, client)
