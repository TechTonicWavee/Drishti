"""Agent trace, reconstructed from the audit logs.

Every step an agent takes is already written to one of the log files under
backend/logs/. This reads those files back rather than keeping a second,
parallel record in memory.

That choice matters for the claim being made. A trace maintained separately
would be a second narrative that could drift from what actually happened, and
would prove nothing about the logs. Reading the logs means the trace shown in
the UI and the audit trail on disk cannot disagree — if the trace shows a
delegation, delegation.log contains it.

Correlation is by time window. The logs carry no request id, so a turn asks
for everything written since it began. With one user that is exact; with
several at once it would over-collect, which is noted in the endpoint.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from app.core.logs import LOG_DIR

# Every line begins "YYYY-MM-DD HH:MM:SS | LEVEL | rest".
_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \| (\w+) \| (.*)$")

# Only the tail of each file is ever needed: a trace covers one turn.
_TAIL_LINES: Final = 400

_SOURCES: Final = (
    "router.log",
    "tools.log",
    "delegation.log",
    "vision.log",
    "sandbox.log",
    "documents.log",
)


@dataclass
class Step:
    at: str
    log: str
    kind: str
    label: str
    detail: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "log": self.log,
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "fields": self.fields,
        }


def _tail(path: Path, limit: int = _TAIL_LINES) -> list[str]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=limit))


def _pairs(rest: str) -> dict[str, str]:
    """Split a 'a=1 | b=2' body into fields, keeping unlabelled parts aside."""
    fields: dict[str, str] = {}
    for index, part in enumerate(rest.split(" | ")):
        key, sep, value = part.partition("=")
        if sep and " " not in key:
            fields[key.strip()] = value.strip()
        else:
            fields[f"_{index}"] = part.strip()
    return fields


def _describe(log_name: str, fields: dict[str, str]) -> Step | None:
    """Turn one parsed line into a display step, or None to skip it."""
    if log_name == "router.log":
        task = fields.get("task", "?")
        agent = {"reasoning": "Reasoning Agent", "coding": "Coder Agent",
                 "vision": "Vision Agent"}.get(task, task)
        return Step("", log_name, "route", f"Router → {agent}",
                    fields.get("reason", ""), fields)

    if log_name == "delegation.log":
        # Both ASKED and ANSWERED are logged; only the ask is a routing step.
        stage = next((v for k, v in fields.items() if k.startswith("_")), "")
        if "ASKED" not in stage:
            return None
        return Step("", log_name, "delegate",
                    f"{fields.get('from', '?')} → {fields.get('to', '?')}",
                    "delegated", fields)

    if log_name == "tools.log":
        tool = fields.get("tool", "?")
        # The delegation itself is already shown as its own step.
        if tool.startswith("ask_"):
            return None
        return Step("", log_name, "tool",
                    f"{fields.get('agent', '?')} used {tool}",
                    fields.get("result", ""), fields)

    if log_name == "vision.log":
        return Step("", log_name, "vision",
                    f"Read {fields.get('source', 'a page')}",
                    f"{fields.get('findings', '?')} findings, "
                    f"deskew {fields.get('deskew', '?')}", fields)

    if log_name == "sandbox.log":
        outcome = ("timed out" if fields.get("timed_out") == "True"
                   else f"exit {fields.get('exit_code', '?')}")
        return Step("", log_name, "sandbox", "Sandboxed run",
                    f"{outcome} in {fields.get('duration', '?')}", fields)

    if log_name == "documents.log":
        return Step("", log_name, "artifact",
                    f"Generated {fields.get('file', 'a document')}",
                    f"{fields.get('kind', '')}, {fields.get('bytes', '?')} bytes",
                    fields)

    return None


def collect(since: datetime, limit: int = 60) -> list[dict[str, Any]]:
    """Every logged step at or after `since`, oldest first."""
    steps: list[tuple[datetime, Step]] = []

    for name in _SOURCES:
        for line in _tail(LOG_DIR / name):
            match = _LINE.match(line.rstrip("\n"))
            if not match:
                continue
            stamp_text, _level, rest = match.groups()
            try:
                # Log timestamps are naive local time, matching the writer.
                stamp = datetime.strptime(stamp_text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if stamp < since:
                continue
            step = _describe(name, _pairs(rest))
            if step is None:
                continue
            step.at = stamp_text
            steps.append((stamp, step))

    # Second-resolution timestamps tie often, so the sort is stabilised by a
    # rough causal order: routing precedes the work it routed to.
    order = {"route": 0, "vision": 1, "delegate": 2, "tool": 3,
             "sandbox": 4, "artifact": 5}
    steps.sort(key=lambda pair: (pair[0], order.get(pair[1].kind, 9)))
    return [step.as_dict() for _stamp, step in steps[-limit:]]
