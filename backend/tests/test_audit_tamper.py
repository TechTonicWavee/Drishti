"""Deterministic tests for the audit trail's tamper-evidence.

Writes a real chain through record_event(), then attacks it directly with
raw SQL — the same way a hex editor or a `sqlite3 audit.db` session would —
and checks that verify_chain_integrity() catches every attack and names the
exact row where the chain breaks. No model involved, so this is runnable
every time with no variance.

Run:  .venv/bin/python tests/test_audit_tamper.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import audit_service as A  # noqa: E402

FAILURES = 0


def check(label: str, condition: bool) -> None:
    global FAILURES
    print(f"  {'✅' if condition else '❌'} {label}")
    FAILURES += not condition


def seed(n: int) -> None:
    for i in range(n):
        A.record_event(
            "route_decision", "demo_user", f"turn {i} routed to Reasoning Agent",
            thread_id="t-tamper-test", source_component="test",
        )


def raw_update(sql: str, params: tuple = ()) -> None:
    """Bypass record_event entirely — a raw SQL edit, like a hex editor would do."""
    connection = sqlite3.connect(A.DB_PATH)
    connection.execute(sql, params)
    connection.commit()
    connection.close()


def with_fresh_db(fn) -> None:
    """Run one scenario against its own empty database and watermark file."""
    with tempfile.TemporaryDirectory() as tmp:
        original_db, original_wm = A.DB_PATH, A.WATERMARK_PATH
        A.DB_PATH = Path(tmp) / "audit.db"
        A.WATERMARK_PATH = Path(tmp) / ".audit_watermark"
        try:
            fn()
        finally:
            A.DB_PATH, A.WATERMARK_PATH = original_db, original_wm


def test_untampered_chain_is_intact() -> None:
    print("\n── a normal chain of 5 events")
    seed(5)
    result = A.verify_chain_integrity()
    check("reports intact", result["intact"] is True)
    check("counts all 5 rows", result["total_rows"] == 5)
    check("no break reported", result["first_break_at"] is None)


def test_content_edit_detected_at_exact_row() -> None:
    print("\n── editing row 3's summary directly via SQL (bypassing record_event)")
    seed(5)
    raw_update("UPDATE audit_log SET summary = 'TAMPERED' WHERE id = 3")
    result = A.verify_chain_integrity()
    check("reports NOT intact", result["intact"] is False)
    check("names exactly row 3", result["first_break_at"] == 3)
    check("gives a reason", bool(result["reason"]))
    # Everything before the tampered row is still exactly as recorded — the
    # break is reported at the row that changed, not swallowed into a vague
    # "somewhere in here" answer.
    check("rows 1-2 remain unaffected by the check itself",
          result["total_rows"] == 5)


def test_row_hash_edit_detected() -> None:
    print("\n── overwriting row 3's own row_hash with garbage")
    seed(5)
    raw_update("UPDATE audit_log SET row_hash = 'not-a-real-hash' WHERE id = 3")
    result = A.verify_chain_integrity()
    check("reports NOT intact", result["intact"] is False)
    check("names exactly row 3", result["first_break_at"] == 3)


def test_deleted_row_detected_as_id_gap() -> None:
    print("\n── deleting row 3 outright")
    seed(5)
    raw_update("DELETE FROM audit_log WHERE id = 3")
    result = A.verify_chain_integrity()
    check("reports NOT intact", result["intact"] is False)
    # The row immediately after the gap (id 4) is where the discontinuity
    # first becomes visible: its own prev_hash was computed against row 3,
    # which no longer precedes it.
    check("names row 4 — the first row after the gap", result["first_break_at"] == 4)
    check("total_rows reflects what actually remains (4, not 5)",
          result["total_rows"] == 4)


def test_prev_hash_edit_detected() -> None:
    print("\n── rewriting row 4's prev_hash to point somewhere else")
    seed(5)
    raw_update(
        "UPDATE audit_log SET prev_hash = '1111111111111111111111111111111111111111111111111111111111111111' WHERE id = 4"
    )
    result = A.verify_chain_integrity()
    check("reports NOT intact", result["intact"] is False)
    check("names exactly row 4", result["first_break_at"] == 4)


def test_first_row_edit_detected() -> None:
    print("\n── tampering the very first row (edge case: no predecessor)")
    seed(3)
    raw_update("UPDATE audit_log SET user_id = 'attacker' WHERE id = 1")
    result = A.verify_chain_integrity()
    check("reports NOT intact", result["intact"] is False)
    check("names row 1", result["first_break_at"] == 1)


def main() -> int:
    for test in (
        test_untampered_chain_is_intact,
        test_content_edit_detected_at_exact_row,
        test_row_hash_edit_detected,
        test_deleted_row_detected_as_id_gap,
        test_prev_hash_edit_detected,
        test_first_row_edit_detected,
    ):
        with_fresh_db(test)

    print(f"\n{'ALL PASSED' if not FAILURES else f'{FAILURES} FAILED'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
