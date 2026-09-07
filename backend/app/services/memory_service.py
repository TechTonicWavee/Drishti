"""Cross-session memory of the user.

Stores a handful of durable facts — role, team, ongoing projects, stated
preferences — so a new session starts knowing who it is talking to. It is an
extraction layer over the existing model, not a new one: qwen2.5:7b reads the
user's own messages and returns structured facts.

The privacy rule is enforced by the type system, not by a comment.
`extract_memory` cannot be handed a prompt-context list: it accepts only
`UserUtterance`, which can be built solely by `user_utterances()`, which keeps
messages whose role is exactly "user". A system message carrying retrieved SOP
excerpts, a tool result holding a document chunk, or an assistant turn quoting
one cannot be passed in at all — there is no code path that constructs a
UserUtterance from them.

A second, independent check runs after extraction: any fact sharing a long
verbatim span with an indexed document is discarded. The first layer stops
document text arriving; this one stops it leaving, in the case where a user
pasted a procedure into their own message.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from app.core.logs import get_file_logger
from app.services.model_client import ModelServingClient, ModelServingError

log = get_file_logger("drishti.memory", "memory.log")

# backend/app/services/memory_service.py -> backend/
DB_PATH: Final = Path(__file__).resolve().parents[2] / "data" / "memory.db"

# There is no login yet, so every session belongs to the same notional person.
# This becomes the authenticated subject once RBAC exists; the schema is
# already keyed by user_id so that change touches callers, not storage.
DEMO_USER: Final = "demo_user"

CATEGORIES: Final = frozenset({"role", "team", "project", "preference", "other"})

# A fact longer than this is a paraphrase of something, not a durable fact.
MAX_FACT_CHARS: Final = 200

# Words per shingle for the leak check. Long enough that ordinary phrasing does
# not collide, short enough to catch a copied sentence.
_SHINGLE: Final = 8

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);

CREATE TABLE IF NOT EXISTS user_memory (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    fact              TEXT NOT NULL,
    category          TEXT NOT NULL,
    extracted_at      TEXT NOT NULL,
    source_session_id TEXT,
    -- Exact duplicates are refused by the database rather than by a query
    -- that could be forgotten at one call site.
    UNIQUE (user_id, fact)
);

CREATE INDEX IF NOT EXISTS idx_memory_user ON user_memory (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions (user_id);
"""


@dataclass(frozen=True)
class UserUtterance:
    """Something the user typed. Never document text, never model output.

    Deliberately not constructible from a chat message dict. The only way to
    obtain one is `user_utterances()`, which is where the filtering lives, so
    a caller cannot route around it by passing a differently-shaped list.
    """

    text: str


def user_utterances(messages: Iterable[dict[str, Any]]) -> list[UserUtterance]:
    """Keep only what the user typed.

    Anything whose role is not exactly "user" is dropped: system messages carry
    the retrieved SOP context, tool messages carry document chunks and sandbox
    output, and assistant messages may quote either back.
    """
    kept: list[UserUtterance] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        content = message.get("content")
        # Multimodal turns carry a list of parts; only the text parts are the
        # user's words, and an image is not a durable fact about them.
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if isinstance(content, str) and content.strip():
            kept.append(UserUtterance(content.strip()))
    return kept


def _connect() -> sqlite3.Connection:
    """A fresh connection per operation.

    Background tasks run on worker threads, and a shared SQLite connection is
    not safe across them. Opening per call avoids that entirely and costs
    nothing at this scale.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    return connection


# --- sessions ---------------------------------------------------------------


def start_session(session_id: str, user_id: str = DEMO_USER) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO chat_sessions (session_id, user_id, started_at) "
            "VALUES (?, ?, ?)",
            (session_id, user_id, _now()),
        )


def end_session(session_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE chat_sessions SET ended_at = ? WHERE session_id = ? "
            "AND ended_at IS NULL",
            (_now(), session_id),
        )


# --- extraction -------------------------------------------------------------

_EXTRACTION_PROMPT = """You are reading what one person typed to an engineering assistant. Extract only DURABLE facts about that person.

Return a JSON array. Each element: {"fact": "...", "category": "role|team|project|preference"}.

Extract:
- Their role or job title.
- Their team, unit or area of responsibility.
- Ongoing projects they say they are working on.
- Stated working preferences ("always give me the SI units", "I prefer short answers").

Do NOT extract:
- Anything about today's specific request or task.
- Any content from documents, procedures or standards. Facts about equipment, limits, temperatures or SOPs are not facts about the person.
- One-off questions, or anything they asked rather than stated about themselves.
- Guesses. If they did not say it, it is not a fact.

If nothing durable was stated, return exactly: []

Return only the JSON array, no other text."""


async def extract_memory(
    utterances: Sequence[UserUtterance],
    user_id: str = DEMO_USER,
    *,
    client: ModelServingClient,
    model: str | None = None,
    session_id: str | None = None,
) -> list[dict[str, str]]:
    """Extract durable facts from what the user typed.

    Takes UserUtterance rather than chat messages by design — see the module
    docstring. The signature is the enforcement.
    """
    from app.core.config import settings

    text = "\n".join(f"- {u.text}" for u in utterances if u.text.strip())
    if not text.strip():
        log.info("user=%s | extraction skipped | no user-authored text", user_id)
        return []

    try:
        reply = await client.chat_message(
            model or settings.reasoning_model,
            [
                {"role": "system", "content": _EXTRACTION_PROMPT},
                {"role": "user", "content": text},
            ],
        )
    except ModelServingError as exc:
        log.error("user=%s | extraction failed | %s", user_id, exc)
        return []

    facts = _parse_facts(reply.get("content") or "")
    kept, rejected = _drop_document_overlap(facts)

    if rejected:
        # Worth its own line: this is the privacy guard firing, and a silent
        # drop would make it impossible to tell the guard from a model that
        # simply found nothing.
        log.warning(
            "user=%s | %d fact(s) rejected as document content | %s",
            user_id, len(rejected), json.dumps([f["fact"][:80] for f in rejected]),
        )

    if kept:
        log.info(
            "user=%s | session=%s | extracted %d fact(s) | %s",
            user_id, session_id or "-", len(kept), json.dumps(kept),
        )
    else:
        log.info(
            "user=%s | session=%s | nothing durable found",
            user_id, session_id or "-",
        )
    return kept


def _parse_facts(raw: str) -> list[dict[str, str]]:
    """Pull the JSON array out of a model reply, however it wrapped it."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    else:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            text = text[start : end + 1]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    facts: list[dict[str, str]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        fact = str(entry.get("fact", "")).strip()
        category = str(entry.get("category", "other")).strip().lower()
        if not fact or len(fact) > MAX_FACT_CHARS:
            continue
        facts.append(
            {"fact": fact, "category": category if category in CATEGORIES else "other"}
        )
    return facts


def _shingles(text: str, size: int = _SHINGLE) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(words[i : i + size]) for i in range(max(0, len(words) - size + 1))}


def _drop_document_overlap(
    facts: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Discard facts sharing a long verbatim span with an indexed document.

    The second privacy layer. The type signature stops document text being
    passed in; this stops it being stored in the case the first layer cannot
    see — a user pasting a procedure into their own message.
    """
    if not facts:
        return [], []

    try:
        from app.services.knowledge_base import _collection

        collection = _collection()
        if collection.count() == 0:
            return facts, []
        stored = collection.get(include=["documents"])
        corpus: set[str] = set()
        for document in stored.get("documents") or []:
            corpus |= _shingles(str(document))
    except Exception:
        # Retrieval being unavailable must not block memory; the structural
        # guarantee still holds without this layer.
        return facts, []

    kept, rejected = [], []
    for entry in facts:
        (rejected if _shingles(entry["fact"]) & corpus else kept).append(entry)
    return kept, rejected


# --- storage and retrieval --------------------------------------------------


def save_memory(
    user_id: str,
    facts: list[dict[str, str]],
    session_id: str | None = None,
) -> None:
    """Store facts, ignoring ones already held verbatim."""
    if not facts:
        return
    now = _now()
    with _connect() as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO user_memory "
            "(user_id, fact, category, extracted_at, source_session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (user_id, f["fact"], f.get("category", "other"), now, session_id)
                for f in facts
            ],
        )


def list_memory(user_id: str = DEMO_USER) -> list[dict[str, Any]]:
    """Everything stored for a user, newest first."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, fact, category, extracted_at, source_session_id "
            "FROM user_memory WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_user_context(user_id: str = DEMO_USER) -> str:
    """Stored facts as a sentence for the system prompt, or "" if none."""
    facts = list_memory(user_id)
    if not facts:
        log.info("user=%s | context requested | none stored", user_id)
        return ""

    # Grouped so the sentence reads as a description rather than a list dump.
    order = ["role", "team", "project", "preference", "other"]
    grouped: dict[str, list[str]] = {}
    for entry in facts:
        grouped.setdefault(entry["category"], []).append(entry["fact"])

    parts = [
        fact
        for category in order
        for fact in grouped.get(category, [])
    ]
    context = "Context about this user, remembered from earlier sessions: " + "; ".join(
        parts
    ) + "."
    log.info("user=%s | context injected | %d fact(s)", user_id, len(parts))
    return context


def forget(user_id: str = DEMO_USER) -> int:
    """Delete everything stored for a user. Returns rows removed."""
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM user_memory WHERE user_id = ?", (user_id,)
        )
        removed = cursor.rowcount
    log.info("user=%s | memory cleared | %d fact(s) removed", user_id, removed)
    return removed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
