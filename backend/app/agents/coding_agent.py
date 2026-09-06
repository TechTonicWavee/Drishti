"""The coding specialist."""

from __future__ import annotations

from typing import ClassVar

from app.agents.base_agent import Agent
from app.core.config import settings
from app.services.model_client import ModelServingClient


class CoderAgent(Agent):
    """Writes code and verifies it by running it in the sandbox.

    It cannot search documents — an SOP corpus is noise in a request to write
    a script — and it cannot delegate, which also means a delegated
    sub-question cannot bounce back and start a loop.
    """

    name: ClassVar[str] = "Coder Agent"
    allowed_tools: ClassVar[list[str]] = ["execute_code"]

    # Two rounds: the first run, and one correction. This is what actually
    # enforces "exactly one self-correction" — a prompt asking a model to stop
    # retrying is a request, whereas exhausting the rounds is a guarantee.
    # After the cap the base class does one final toolless generation, which
    # is where the honest report of the remaining failure gets written.
    max_tool_rounds: ClassVar[int] = 2

    instructions: ClassVar[str] = (
        "You are the coding specialist for a refinery engineering team. "
        "Write correct, readable code and keep explanations short. Prefer the "
        "Python standard library unless a dependency is clearly warranted.\n"
        "- Whenever you write Python, call execute_code to verify it actually "
        "runs before you present it. Do not claim code works without having "
        "run it.\n"
        "- The sandbox has no network access and a read-only filesystem apart "
        "from /tmp, so do not write code that fetches from the internet or "
        "writes outside /tmp.\n"
        "- If execution fails, read the error, fix the code, and run it once "
        "more. Exactly one retry — do not keep trying.\n"
        "- Report the outcome honestly. If it worked, show the code and its "
        "real output. If it still fails after your one retry, say so plainly "
        "and explain what went wrong. Never present failing code as working.\n"
        "- When a request is ambiguous, state the assumption you made and "
        "answer anyway rather than asking a question back — you are often "
        "answering on behalf of another agent that cannot reply."
    )

    def __init__(self, client: ModelServingClient, model: str | None = None) -> None:
        super().__init__(client, model or settings.coding_model)
