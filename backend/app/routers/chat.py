"""Chat route.

Streams an agent's turn to the browser over Server-Sent Events.

The division of labour: `app.services.router` decides *which* agent handles a
message, and the agent decides everything after that — whether to use a tool,
whether to delegate, and what to say. This module only translates agent events
onto the wire.

Two entry points expose the same stream, because the browser's native
EventSource can only issue GET requests and therefore cannot consume a
streaming POST:

    POST /chat          — the canonical API; body is {"message", ...}.
    GET  /chat/stream   — the same stream as query parameters, so
                          `new EventSource(...)` works unmodified.

Frames on the wire:

    event: routing        one per turn, always first — which agent was picked
    event: tool           a tool ran; carries its short summary
    event: sources        documents the answer is grounded in
    data:  {"delta": ...} one per token
    event: stream-error   the turn failed
    event: done           terminal; the client must close the EventSource
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.base_agent import Agent, Delta, Sources, ToolUse
from app.agents.coding_agent import CoderAgent
from app.agents.reasoning_agent import ReasoningAgent
from app.services.dependencies import get_model_client
from app.services.model_client import ModelServingClient, ModelServingError
from app.services.router import Task, classify

router = APIRouter(tags=["chat"])

# The router's output maps to exactly one agent class. Vision is recognised by
# the classifier but has no agent yet.
_AGENTS: dict[Task, type[Agent] | None] = {
    "reasoning": ReasoningAgent,
    "coding": CoderAgent,
    "vision": None,
}

_VISION_NOT_IMPLEMENTED = (
    "Image understanding is not wired up yet. This turn was routed to the "
    "vision agent because an image was attached, but no vision agent exists. "
    "Ask a text question, or send the message without the attachment."
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    # Optional. Omit it and the router picks the agent and its bound model;
    # supply it to override the model the chosen agent runs on.
    model: str | None = Field(default=None, min_length=1)
    has_attachment: bool = False
    attachment_name: str | None = None


@dataclass(frozen=True)
class Route:
    task: Task
    agent: Agent | None
    agent_name: str
    model: str | None
    reason: str


def _choose(
    message: str,
    override: str | None,
    has_attachment: bool,
    attachment_name: str | None,
    client: ModelServingClient,
) -> Route:
    """Classify the turn and build the agent that will handle it."""
    decision = classify(message, has_attachment, attachment_name)
    agent_class = _AGENTS[decision.task]

    if agent_class is None:
        return Route(decision.task, None, "Vision Agent", None, decision.reason)

    agent = agent_class(client, override)
    reason = (
        f"caller override (router suggested: {decision.reason})"
        if override
        else decision.reason
    )
    return Route(decision.task, agent, agent.name, agent.model, reason)


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
    route = _choose(message, override, has_attachment, attachment_name, client)

    # Always first, so the UI can label the answer before any token arrives.
    yield _sse(
        {
            "task": route.task,
            "agent": route.agent_name,
            "model": route.model,
            "reason": route.reason,
            "implemented": route.agent is not None,
        },
        event="routing",
    )

    if route.agent is None:
        # A known gap, not a failure: deliver it as ordinary assistant text so
        # it reads as an answer rather than an error.
        yield _sse({"delta": _VISION_NOT_IMPLEMENTED})
        yield _sse({}, event="done")
        return

    try:
        async for event in route.agent.run_stream(message, {}):
            if isinstance(event, Delta):
                yield _sse({"delta": event.text})
            elif isinstance(event, ToolUse):
                yield _sse(
                    {"tool": event.tool, "summary": event.summary, "ok": event.ok},
                    event="tool",
                )
            elif isinstance(event, Sources):
                yield _sse({"sources": event.sources}, event="sources")
    except ModelServingError as exc:
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
    """Stream a reply, routing to an agent automatically."""
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
