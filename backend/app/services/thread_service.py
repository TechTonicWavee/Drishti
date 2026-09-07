"""Conversation threads: the transcripts themselves.

NOT to be confused with app/services/memory_service.py. The two are separate
on purpose and a future editor should keep them that way:

    thread_service  stores the actual conversation — every message, verbatim,
                    so a user can reopen a thread and read or continue it.
                    Grows with use. Never injected into a prompt wholesale.

    memory_service  stores a handful of small extracted facts about the person
                    — role, team, projects, preferences. Bounded, structured,
                    and injected into every system prompt.

Merging them would break both. Injecting whole transcripts into prompts would
blow the context window and drown retrieved procedures; storing only extracted
facts would mean there is nothing to reopen. They share one SQLite file and
nothing else.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from app.core.logs import get_file_logger
from app.services.model_client import ModelServingClient, ModelServingError

log = get_file_logger("drishti.threads", "threads.log")

# The same file memory_service uses. Declared here rather than imported so
# threads do not depend on the memory module; they share storage, not code.
DB_PATH: Final = Path(__file__).resolve().parents[2] / "data" / "memory.db"

TITLE_WORDS: Final = 6
TITLE_MAX_CHARS: Final = 60
PREVIEW_CHARS: Final = 90

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id  TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id          TEXT PRIMARY KEY,
    thread_id           TEXT NOT NULL REFERENCES threads (thread_id)
                            ON DELETE CASCADE,
    role                TEXT NOT NULL,
    content             TEXT NOT NULL,
    agent_trace_summary TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_threads_user ON threads (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages (thread_id, created_at);
"""


def _connect() -> sqlite3.Connection:
    """A fresh connection per operation; see memory_service for the reasoning."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_SCHEMA)
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _truncated_title(first_message: str) -> str:
    """A title from the opening words. Always available, never fails."""
    words = re.findall(r"\S+", first_message.strip())
    if not words:
        return "New conversation"
    title = " ".join(words[:TITLE_WORDS])
    if len(title) > TITLE_MAX_CHARS:
        title = title[:TITLE_MAX_CHARS].rstrip()
    if len(words) > TITLE_WORDS or len(title) < len(first_message.strip()):
        title += "…"
    return title


async def _model_title(first_message: str, client: ModelServingClient) -> str | None:
    """Ask the model for a short title. None if it cannot supply a usable one."""
    from app.core.config import settings

    try:
        reply = await client.chat_message(
            settings.reasoning_model,
            [
                {
                    "role": "system",
                    "content": (
                        "Write a title of four to six words for a conversation "
                        "that opens with the message below.\n"
                        "- Use ordinary words separated by spaces, as a person "
                        "would write a heading.\n"
                        "- Never use underscores, camelCase, or a filename or "
                        "variable style.\n"
                        "- Reply with the title only: no quotes, no trailing "
                        "punctuation, no explanation."
                    ),
                },
                {"role": "user", "content": first_message[:500]},
            ],
        )
    except ModelServingError:
        return None

    title = " ".join((reply.get("content") or "").split()).strip(" \"'.")

    # Reject anything that is not prose. A model that ignored the instruction
    # is worse than the truncation fallback, so these fall through to it
    # rather than being cleaned up into something half-right.
    if not title or len(title) > TITLE_MAX_CHARS:
        return None
    if "_" in title or len(title.split()) < 2:
        # Observed in practice: "acceptable_oxygen_range" — an identifier, not
        # a heading. It passed the length check and looked like a title to the
        # code while looking like nothing anyone would write to a reader.
        return None
    return title


async def create_thread(
    user_id: str,
    first_message: str,
    *,
    client: ModelServingClient | None = None,
) -> str:
    """Create a thread titled from its opening message, returning its id."""
    from app.core.config import settings

    title = None
    if settings.thread_titles_from_model and client is not None:
        title = await _model_title(first_message, client)
    if not title:
        title = _truncated_title(first_message)

    thread_id = str(uuid.uuid4())
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO threads (thread_id, user_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (thread_id, user_id, title, now, now),
        )

    # Titles are derived from user text, so the log records the id and length
    # only — enough to trace a thread without duplicating its content here.
    log.info(
        "user=%s | thread=%s | CREATED | title_chars=%d | opening_chars=%d",
        user_id, thread_id, len(title), len(first_message),
    )
    return thread_id


def add_message(
    thread_id: str,
    role: str,
    content: str,
    agent_trace_summary: str | None = None,
) -> None:
    """Append a message and bump the thread's updated_at."""
    if not content.strip():
        return
    with _connect() as connection:
        connection.execute(
            "INSERT INTO messages "
            "(message_id, thread_id, role, content, agent_trace_summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), thread_id, role, content, agent_trace_summary, _now()),
        )
        connection.execute(
            "UPDATE threads SET updated_at = ? WHERE thread_id = ?",
            (_now(), thread_id),
        )


def thread_exists(thread_id: str) -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
    return row is not None


def list_threads(user_id: str) -> list[dict[str, Any]]:
    """Threads newest first, with a preview — the shape a sidebar needs."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT t.thread_id, t.title, t.created_at, t.updated_at,
                   (SELECT m.content FROM messages m
                     WHERE m.thread_id = t.thread_id
                     ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1) AS last_message,
                   (SELECT COUNT(*) FROM messages m
                     WHERE m.thread_id = t.thread_id) AS message_count
            FROM threads t
            WHERE t.user_id = ?
            ORDER BY t.updated_at DESC, t.rowid DESC
            """,
            (user_id,),
        ).fetchall()

    threads = []
    for row in rows:
        preview = " ".join((row["last_message"] or "").split())
        if len(preview) > PREVIEW_CHARS:
            preview = preview[:PREVIEW_CHARS].rstrip() + "…"
        threads.append(
            {
                "thread_id": row["thread_id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "preview": preview,
                "message_count": row["message_count"],
            }
        )
    return threads


def get_thread_messages(thread_id: str) -> list[dict[str, Any]]:
    """Every message in a thread, oldest first."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT message_id, role, content, agent_trace_summary, created_at "
            "FROM messages WHERE thread_id = ? ORDER BY created_at, rowid",
            (thread_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def history_for_model(thread_id: str, limit: int) -> list[dict[str, str]]:
    """The tail of a thread, shaped for replay into a prompt.

    Bounded like the client-supplied history it replaces: the whole transcript
    is re-sent on every turn, so an unbounded one would crowd retrieved
    context out of the model's window.
    """
    messages = get_thread_messages(thread_id)
    return [
        {"role": m["role"], "content": m["content"]}
        for m in messages[-limit:]
        if m["role"] in {"user", "assistant"} and m["content"].strip()
    ]


def note_resumed(thread_id: str, user_id: str, message_count: int) -> None:
    log.info(
        "user=%s | thread=%s | RESUMED | prior_messages=%d",
        user_id, thread_id, message_count,
    )
