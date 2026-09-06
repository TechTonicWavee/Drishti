"""The coding specialist."""

from __future__ import annotations

from typing import ClassVar

from app.agents.base_agent import Agent
from app.core.config import settings
from app.services.model_client import ModelServingClient


class CoderAgent(Agent):
    """Writes and explains code, bound to the code-tuned model.

    No tools yet. It cannot search documents — an SOP corpus is noise in a
    request to write a script — and it cannot delegate, which also means a
    delegated sub-question cannot bounce back and start a loop. Sandboxed
    execution is the next capability to land here.
    """

    name: ClassVar[str] = "Coder Agent"
    allowed_tools: ClassVar[list[str]] = []
    instructions: ClassVar[str] = (
        "You are the coding specialist for a refinery engineering team. "
        "Write correct, readable code and keep explanations short. "
        "Prefer the Python standard library unless a dependency is clearly "
        "warranted. When a request is ambiguous, state the assumption you "
        "made and answer anyway rather than asking a question back — you are "
        "often answering on behalf of another agent that cannot reply."
    )

    def __init__(self, client: ModelServingClient) -> None:
        super().__init__(client, settings.coding_model)
