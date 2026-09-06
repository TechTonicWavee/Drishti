"""Task router.

Decides which specialist model should answer a message. The decision is made
by regular expressions, not by an LLM: routing sits in front of every request,
so it has to be fast, and an operator asking "why did it pick that model?"
deserves an answer more concrete than "the classifier felt like it".

Every decision is written to backend/logs/router.log with the rule that fired,
so the routing behaviour can be audited after the fact.

A note on the keyword list. This assistant is read by refinery staff, and
refinery English collides with programming English more than you would expect:

    "the ASME code requires..."        -> not coding
    "the function of the reflux drum"  -> not coding
    "shell-and-tube heat exchanger"    -> not coding
    "rust on the overhead line"        -> not coding
    "pump malfunction"                 -> not coding

So the bare words "code", "function", "shell" and "rust" deliberately do NOT
trigger the coding route on their own. They only count when they appear with
programming context, which is what the ordered rules below encode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from app.core.logs import get_file_logger

Task = Literal["reasoning", "coding", "vision"]

# backend/app/services/router.py -> backend/
_BACKEND_ROOT: Final = Path(__file__).resolve().parents[2]
_LOG_PATH: Final = _BACKEND_ROOT / "logs" / "router.log"


log = get_file_logger("drishti.router", "router.log")


@dataclass(frozen=True)
class Classification:
    """A routing decision and the reason it was made."""

    task: Task
    reason: str


# Ordered rules: the first match wins, so the reason always names exactly the
# rule that decided. Strongest and least ambiguous signals come first.
_CODING_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("fenced code block", re.compile(r"```")),
    (
        "file extension",
        re.compile(
            r"\.(?:py|js|ts|tsx|jsx|java|cpp|cs|go|rb|php|sh|bash|sql|html|css"
            r"|json|ya?ml|xml|ipynb)\b",
            re.I,
        ),
    ),
    (
        "programming language or library",
        re.compile(
            r"\b(?:python|javascript|typescript|node\.js|nodejs|java|golang"
            r"|c\+\+|c#|bash|powershell|sql|regex|fastapi|django|flask"
            r"|pandas|numpy|matplotlib|docker|kubernetes)\b",
            re.I,
        ),
    ),
    (
        "debugging vocabulary",
        re.compile(
            r"\b(?:debug|traceback|stack ?trace|syntax error|segfault"
            r"|null pointer|compile error|runtime error|unit test)\b",
            re.I,
        ),
    ),
    (
        "code action phrase",
        # An action verb close to a programming noun. The bounded gap keeps
        # "write up the function of the column" from matching across clauses.
        re.compile(
            r"\b(?:write|create|generate|implement|refactor|debug|fix"
            r"|optimi[sz]e|convert|port|parse)\b[^.?!\n]{0,50}?"
            r"\b(?:script|function|program|code|class|method|query|api"
            r"|endpoint|regex|algorithm|loop|module|package|parser)\b",
            re.I,
        ),
    ),
    (
        "explicit code request",
        re.compile(r"\b(?:code|script|snippet|pseudocode)\s+(?:for|to|that)\b", re.I),
    ),
    ("script mention", re.compile(r"\bscripts?\b", re.I)),
)

# Everything the vision agent can actually read. Kept as a literal here rather
# than imported from the agent so this module stays dependency-light and
# deterministic — but it must not drift from vision_agent's own set.
_VISION_SUFFIXES: Final = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
        ".heic",
        # PDFs are rendered page by page and read like any other scan. They
        # were excluded here once, on the theory that a separate document
        # route would claim them. It never did, so a PDF dropped on the chat
        # was routed to the reasoning agent, which receives only the filename
        # and no content — it answered every question with "please specify
        # your question", because from where it sat there was nothing there.
        ".pdf",
    }
)


def _vision_can_read(attachment_name: str | None) -> bool:
    """Whether an attachment should go to the vision route.

    An unnamed attachment is treated as readable: vision is the only
    attachment route that exists, so an unknown file has nowhere else to go,
    and the agent reports a clear error if it turns out not to be readable.
    """
    if attachment_name is None:
        return True
    return Path(attachment_name).suffix.lower() in _VISION_SUFFIXES


def classify(
    message: str,
    has_attachment: bool = False,
    attachment_name: str | None = None,
) -> Classification:
    """Classify a message and record the decision.

    `attachment_name` is optional: `has_attachment` alone cannot distinguish a
    photograph from a PDF, so callers pass the filename when they have it.
    """
    if has_attachment and _vision_can_read(attachment_name):
        described = attachment_name or "unnamed attachment"
        result = Classification("vision", f"readable attachment: '{described}'")
        _record(result, message)
        return result

    for rule_name, pattern in _CODING_RULES:
        match = pattern.search(message)
        if match:
            result = Classification(
                "coding", f"matched {rule_name}: '{match.group(0).strip()}'"
            )
            _record(result, message)
            return result

    result = Classification("reasoning", "no coding or vision signals matched")
    _record(result, message)
    return result


def classify_task(
    message: str,
    has_attachment: bool = False,
    attachment_name: str | None = None,
) -> Task:
    """Return just the task name. See `classify` for the reason as well."""
    return classify(message, has_attachment, attachment_name).task


def _record(result: Classification, message: str) -> None:
    # The message preview makes the log auditable — a decision you cannot tie
    # back to an input is not much of an audit trail. It is truncated, and this
    # file stays on the plant's own disk like everything else here.
    preview = " ".join(message.split())[:80]
    log.info('task=%s | reason=%s | message="%s"', result.task, result.reason, preview)
