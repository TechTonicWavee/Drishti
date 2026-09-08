"""Cross-cutting audit trail: who did what, when, with a tamper-evident chain.

Every feature already writes its own detailed log — router.log, tools.log,
delegation.log, vision.log, sandbox.log, documents.log, memory.log,
threads.log. Those stay exactly as they are; they are for debugging one
feature at a time. This module is different in kind, not degree: one table,
one timeline, spanning every feature, built for the question a compliance
reviewer or a judge actually asks — "show me everything that happened, and
prove nobody edited the record afterwards."

The integrity mechanism is a hash chain: each row's row_hash is
SHA-256(this row's own fields + the previous row's row_hash). Change one
field in one old row and every row after it fails to recompute, because each
one depends on the one before. This is the same "verify, don't trust"
discipline used throughout the build — the air-gap counter is checked against
real traffic rather than assumed to read zero; this checks the log against
itself rather than assuming nobody touched it.

VERIFIED EXPERIMENTALLY, not assumed: deleting the underlying .db file while
the backend is running raises no exception anywhere. A connection already
open when the file is removed writes into the now-unlinked inode and reports
success — those writes are real but unreachable by path, and vanish the
moment the process exits. The next *fresh* connection (which is what this
module and every other service in this codebase uses — a new connection per
call) finds no file, silently creates an empty one, and reports zero rows.
No error. No warning. `rm audit.db` is a stronger attack against a supposedly
tamper-evident log than editing any row in it, and it leaves no evidence
inside the file itself.

That is why integrity checking cannot live only in verify_chain_integrity(),
which only ever sees what is currently in the file — after a silent reset it
would see a short, internally-consistent chain and correctly report "intact",
which is true and also completely misses the point. The defence is a
watermark kept OUTSIDE the database: a small sidecar file recording the row
count and hash this process last wrote. Every write compares the database's
actual last row against that watermark first. A mismatch — fewer rows than
expected, or a different hash where the same one should be — means the file
was replaced since the last write, and gets recorded as its own loud event
rather than silently accepted as a fresh start.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from app.core.logs import get_file_logger

# A plain-text, append-only note of watermark breaches, independent of the
# database the breach concerns. If audit.db itself is the thing being
# attacked, the evidence of that attack should not live nowhere else.
_breach_log = get_file_logger("drishti.audit_integrity", "audit_integrity.log")

# backend/app/services/audit_service.py -> backend/
DB_PATH: Final = Path(__file__).resolve().parents[2] / "data" / "audit.db"
WATERMARK_PATH: Final = Path(__file__).resolve().parents[2] / "data" / ".audit_watermark"

# Fixed anchor the first row in any chain links back to. Sixty-four zero
# characters — deliberately not itself the hash of anything, so it can never
# collide with a real row's hash.
GENESIS_HASH: Final = "0" * 64

MAX_SUMMARY_CHARS: Final = 300

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS audit_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    thread_id        TEXT,
    summary          TEXT NOT NULL,
    source_component TEXT NOT NULL,
    prev_hash        TEXT NOT NULL,
    row_hash         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_thread ON audit_log (thread_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log (timestamp);
"""

# Serialises the read-last-row / compute / insert / update-watermark sequence.
# Without this, two concurrent requests could both read the same "last row"
# and each compute a prev_hash pointing to it, producing two rows that both
# claim to follow the same predecessor — a fork, not a chain.
_write_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    """A fresh connection per operation, WAL mode, schema ensured.

    Per-call connections are this codebase's established pattern (see
    memory_service, thread_service) and, per the module docstring, are also
    exactly what makes an externally-deleted file invisible from inside a
    single connection's error handling — which is precisely why the watermark
    check below does not rely on catching an exception; there isn't one.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(_SCHEMA)
    return connection


def _row_hash(
    timestamp: str,
    event_type: str,
    user_id: str,
    thread_id: str | None,
    summary: str,
    source_component: str,
    prev_hash: str,
) -> str:
    """The one hash function used both to write rows and to verify them.

    A single shared function, rather than one formula at write time and a
    hoped-to-match one at verify time, is what guarantees the two can never
    silently drift apart.
    """
    canonical = "|".join(
        [timestamp, event_type, user_id, thread_id or "", summary, source_component, prev_hash]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_watermark() -> dict[str, Any] | None:
    try:
        return json.loads(WATERMARK_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_watermark(row_count: int, last_hash: str) -> None:
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATERMARK_PATH.write_text(json.dumps({"row_count": row_count, "row_hash": last_hash}))


def _last_row(connection: sqlite3.Connection) -> tuple[int, str]:
    """(row count, hash of the last row) actually in the database right now."""
    row = connection.execute(
        "SELECT COUNT(*) AS n, "
        "(SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1) AS h "
        "FROM audit_log"
    ).fetchone()
    return row["n"], row["h"] or GENESIS_HASH


def _insert(
    connection: sqlite3.Connection,
    event_type: str,
    user_id: str,
    thread_id: str | None,
    summary: str,
    source_component: str,
    prev_hash: str,
) -> None:
    timestamp = _now()
    row_hash = _row_hash(
        timestamp, event_type, user_id, thread_id, summary, source_component, prev_hash
    )
    connection.execute(
        "INSERT INTO audit_log "
        "(timestamp, event_type, user_id, thread_id, summary, source_component, "
        " prev_hash, row_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (timestamp, event_type, user_id, thread_id, summary, source_component,
         prev_hash, row_hash),
    )


def record_event(
    event_type: str,
    user_id: str,
    summary: str,
    *,
    thread_id: str | None = None,
    source_component: str,
) -> None:
    """Append one event to the chain.

    Metadata only, by the same discipline as every other log in this build:
    no full code, no full document text, no full retrieved chunk. summary is
    truncated defensively at this boundary rather than trusted to already be
    short, because this is the one function every feature calls into.
    """
    summary = " ".join(summary.split())
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS] + "…"

    with _write_lock:
        connection = _connect()
        try:
            db_count, db_last_hash = _last_row(connection)
            watermark = _read_watermark()

            if watermark is not None and (
                db_count < watermark["row_count"] or db_last_hash != watermark["row_hash"]
            ):
                # The file on disk no longer matches what this process last
                # wrote to it. Either it was deleted and silently recreated
                # (db_count will have dropped, usually to 0), or a row was
                # removed, or a row was edited such that the chain no longer
                # ends where we expect. Whichever it is, do not proceed as if
                # nothing happened: record the discontinuity itself, as the
                # new first row of whatever chain now exists, before
                # recording the event that was actually requested.
                breach_summary = (
                    f"audit.db no longer matches this process's last known "
                    f"state: expected {watermark['row_count']} row(s) ending "
                    f"in {watermark['row_hash'][:12]}…, found {db_count} "
                    f"row(s) ending in {db_last_hash[:12]}…. The file was "
                    f"likely deleted or replaced while the backend was running."
                )
                _breach_log.warning(breach_summary)
                _insert(
                    connection, "audit_integrity_breach", "system", None,
                    breach_summary, "audit_service", GENESIS_HASH,
                )
                db_count, db_last_hash = _last_row(connection)

            _insert(
                connection, event_type, user_id, thread_id, summary,
                source_component, db_last_hash,
            )
            connection.commit()

            new_count, new_hash = _last_row(connection)
            _write_watermark(new_count, new_hash)
        finally:
            connection.close()


def verify_chain_integrity() -> dict[str, Any]:
    """Recompute every row's hash from scratch and compare to what is stored.

    Walks the table exactly once, in id order, maintaining the same running
    prev_hash a fresh write would have used. The first row whose stored hash
    does not match what recomputation produces is where the chain breaks —
    from an edited field, a deleted row (the next surviving row's stored
    prev_hash no longer matches anything actually preceding it), or an id gap
    (AUTOINCREMENT never reuses an id, so a gap is deletion, full stop).
    """
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT id, timestamp, event_type, user_id, thread_id, summary, "
            "source_component, prev_hash, row_hash FROM audit_log ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    running_prev = GENESIS_HASH
    expected_next_id: int | None = None

    for row in rows:
        if expected_next_id is not None and row["id"] != expected_next_id:
            return {
                "intact": False,
                "total_rows": len(rows),
                "first_break_at": row["id"],
                "reason": f"row id gap: expected id {expected_next_id}, found {row['id']}",
            }

        # The row's own claim about what preceded it must match what the walk
        # actually found preceding it. Without this check, corrupting only
        # the stored prev_hash column — leaving row_hash untouched — passes
        # silently: row_hash was computed at insert time from the *correct*
        # prev_hash, so recomputing with running_prev (which is also correct,
        # since nothing upstream was touched) reproduces the same row_hash
        # regardless of what the prev_hash column now says. Caught by this
        # module's own test suite, which tampers prev_hash in isolation
        # specifically to exercise this path.
        if row["prev_hash"] != running_prev:
            return {
                "intact": False,
                "total_rows": len(rows),
                "first_break_at": row["id"],
                "reason": "stored prev_hash does not match the hash of the "
                          "row that actually precedes it",
            }

        candidate = _row_hash(
            row["timestamp"], row["event_type"], row["user_id"], row["thread_id"],
            row["summary"], row["source_component"], running_prev,
        )
        if candidate != row["row_hash"]:
            return {
                "intact": False,
                "total_rows": len(rows),
                "first_break_at": row["id"],
                "reason": "stored hash does not match recomputed hash "
                          "(row content was altered)",
            }

        running_prev = row["row_hash"]
        expected_next_id = row["id"] + 1

    return {"intact": True, "total_rows": len(rows), "first_break_at": None, "reason": None}


def query_events(
    event_type: str | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Filtered read of the audit trail, newest first.

    Timestamps are ISO-8601 strings, which sort lexicographically in the same
    order as chronologically — the same convention used by every other
    service in this codebase, so start_time/end_time need no parsing here.
    """
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("event_type", event_type),
        ("user_id", user_id),
        ("thread_id", thread_id),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if start_time:
        clauses.append("timestamp >= ?")
        params.append(start_time)
    if end_time:
        clauses.append("timestamp <= ?")
        params.append(end_time)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    connection = _connect()
    try:
        rows = connection.execute(
            f"SELECT id, timestamp, event_type, user_id, thread_id, summary, "
            f"source_component FROM audit_log {where} "
            f"ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def export_csv() -> str:
    """The full audit log as CSV text, oldest first — a reviewer's export."""
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT id, timestamp, event_type, user_id, thread_id, summary, "
            "source_component, prev_hash, row_hash FROM audit_log ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(rows[0].keys() if rows else
                     ["id", "timestamp", "event_type", "user_id", "thread_id",
                      "summary", "source_component", "prev_hash", "row_hash"])
    for row in rows:
        writer.writerow([row[key] for key in row.keys()])
    return buffer.getvalue()
