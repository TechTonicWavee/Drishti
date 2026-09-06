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
    event: execution      code was run in the sandbox; carries its real output
    event: artifact       a real file was generated and can be downloaded
    data:  {"delta": ...} one per token
    event: stream-error   the turn failed
    event: done           terminal; the client must close the EventSource
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.base_agent import (
    Agent,
    Artifact,
    Delta,
    Execution,
    Sources,
    ToolUse,
)
from app.agents.coding_agent import CoderAgent
from app.agents.reasoning_agent import ReasoningAgent
from app.agents.vision_agent import (
    IMAGE_SUFFIXES,
    PDF_SUFFIXES,
    VisionAgent,
)
from app.services.dependencies import get_model_client
from app.services.model_client import ModelServingClient, ModelServingError
from app.core.config import settings
from app.services.router import Task, classify

router = APIRouter(tags=["chat"])

# The router's output maps to exactly one agent class.
_AGENTS: dict[Task, type[Agent]] = {
    "reasoning": ReasoningAgent,
    "coding": CoderAgent,
    "vision": VisionAgent,
}

# backend/app/routers/chat.py -> backend/
_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"
_ACCEPTED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES


class HistoryTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    # Prior turns, replayed so follow-ups like "and what about step 3?"
    # resolve. Bounded again server-side; see base_agent.history_messages.
    history: list[HistoryTurn] = Field(default_factory=list)
    # Optional. Omit it and the router picks the agent and its bound model;
    # supply it to override the model the chosen agent runs on.
    model: str | None = Field(default=None, min_length=1)
    has_attachment: bool = False
    attachment_name: str | None = None


@dataclass(frozen=True)
class Route:
    task: Task
    agent: Agent
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
    agent = _AGENTS[decision.task](client, override)
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
    attachment_path: Path | None = None,
    history: list[dict[str, str]] | None = None,
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

    agent_context: dict[str, object] = {"history": history or []}
    if attachment_path is not None:
        agent_context["attachment_path"] = str(attachment_path)
        agent_context["attachment_name"] = attachment_name

    try:
        async for event in route.agent.run_stream(message, agent_context):
            if isinstance(event, Delta):
                yield _sse({"delta": event.text})
            elif isinstance(event, ToolUse):
                yield _sse(
                    {"tool": event.tool, "summary": event.summary, "ok": event.ok},
                    event="tool",
                )
            elif isinstance(event, Sources):
                yield _sse({"sources": event.sources}, event="sources")
            elif isinstance(event, Artifact):
                yield _sse(
                    {
                        "filename": event.filename,
                        "kind": event.kind,
                        "url": event.url,
                        "size_bytes": event.size_bytes,
                    },
                    event="artifact",
                )
            elif isinstance(event, Execution):
                yield _sse(
                    {
                        "code": event.code,
                        "stdout": event.stdout,
                        "stderr": event.stderr,
                        "exit_code": event.exit_code,
                        "timed_out": event.timed_out,
                    },
                    event="execution",
                )
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
    attachment_path: Path | None = None,
    history: list[dict[str, str]] | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        _sse_events(
            message, override, has_attachment, attachment_name, client,
            attachment_path, history,
        ),
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
        history=[turn.model_dump() for turn in request.history],
    )


@router.get("/chat/stream")
async def chat_stream(
    message: str = Query(min_length=1),
    model: str | None = Query(default=None),
    has_attachment: bool = Query(default=False),
    attachment_name: str | None = Query(default=None),
    history: str | None = Query(
        default=None,
        description="JSON array of prior {role, content} turns.",
    ),
    client: ModelServingClient = Depends(get_model_client),
) -> StreamingResponse:
    """EventSource-compatible mirror of POST /chat.

    History rides in the query string because EventSource can only issue a
    GET. The client keeps it short for that reason; it is bounded again on
    this side, and a malformed value is dropped rather than failing the turn —
    losing context is a worse answer, not a broken one.
    """
    turns: list[dict[str, str]] = []
    if history:
        try:
            parsed = json.loads(history)
            if isinstance(parsed, list):
                turns = [t for t in parsed if isinstance(t, dict)]
        except json.JSONDecodeError:
            turns = []
    return _stream(
        message, model, has_attachment, attachment_name, client, history=turns
    )


# Uploads are working files, not a document store. Anything older than this is
# removed on the next upload: scanned inspection paperwork is plant data, and
# leaving every page ever uploaded on disk indefinitely is a retention problem
# nobody asked for.
_UPLOAD_RETENTION_SECONDS = 60 * 60


def _prune_old_uploads() -> None:
    cutoff = time.time() - _UPLOAD_RETENTION_SECONDS
    for stale in _UPLOAD_DIR.iterdir():
        try:
            if stale.is_file() and stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            # Housekeeping must never fail the upload it runs alongside.
            continue


async def _save_upload(file: UploadFile) -> Path:
    """Write an upload to disk under a generated name.

    The client's filename is never used as a path. It is attacker-controlled
    and could contain traversal segments; only its suffix is kept, and only
    after checking it against the accepted set.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ACCEPTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix or 'unknown'}'. "
                f"Accepted: {', '.join(sorted(_ACCEPTED_SUFFIXES))}"
            ),
        )

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _prune_old_uploads()
    destination = _UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"

    written = 0
    with destination.open("wb") as handle:
        # Streamed in chunks so an oversized upload is refused partway through
        # rather than after the whole thing is in memory.
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > settings.max_upload_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File exceeds the {settings.max_upload_bytes // (1024*1024)}MB limit."
                    ),
                )
            handle.write(chunk)

    if written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file was empty.")

    return destination


@router.post("/chat/upload")
async def chat_upload(
    file: UploadFile = File(...),
    message: str = Form(default=""),
    history: str = Form(default=""),
    client: ModelServingClient = Depends(get_model_client),
) -> StreamingResponse:
    """Accept an image or PDF and stream the vision agent's reading of it.

    Streams the same SSE frames as /chat, so a client already able to render a
    chat turn needs no second response format.
    """
    saved = await _save_upload(file)
    turns: list[dict[str, str]] = []
    if history:
        try:
            parsed = json.loads(history)
            if isinstance(parsed, list):
                turns = [t for t in parsed if isinstance(t, dict)]
        except json.JSONDecodeError:
            turns = []
    return _stream(
        message,
        None,
        True,
        file.filename or saved.name,
        client,
        attachment_path=saved,
        history=turns,
    )
