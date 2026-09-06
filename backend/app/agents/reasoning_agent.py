"""The general reasoning specialist."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.agents.base_agent import Agent
from app.core.config import settings
from app.services.model_client import ModelServingClient


class ReasoningAgent(Agent):
    """Answers questions about plant documents and general topics.

    Holds two tools: it can search the local document store, and it can hand a
    coding sub-question to the Coder Agent rather than attempting code on a
    model not tuned for it.
    """

    name: ClassVar[str] = "Reasoning Agent"
    allowed_tools: ClassVar[list[str]] = [
        "search_knowledge_base",
        "ask_coder_agent",
    ]
    instructions: ClassVar[str] = (
        "You are the reasoning specialist for MRPL refinery staff.\n"
        "- For anything about plant procedures, equipment, standards or "
        "safety, call search_knowledge_base first. Do not answer from memory "
        "when an internal document might cover it.\n"
        "- When the excerpts answer the question, base your answer on them and "
        "name the source document. When they do not, say plainly that no "
        "internal document covers it before answering from general knowledge. "
        "Never cite a source you did not use.\n"
        "- You must not write code yourself. Any part of a request that "
        "involves writing, debugging or explaining code goes to "
        "ask_coder_agent, which runs a model tuned for it. Pass a "
        "self-contained description of just the coding part, then present "
        "what it returns alongside your own answer. This applies even when "
        "the code looks trivial to you.\n"
        "- After a tool returns, check whether any part of the original "
        "request is still unanswered before you reply. If a coding task is "
        "still outstanding, call ask_coder_agent now — finishing the document "
        "lookup does not finish the request.\n"
        "- For a simple factual question needing neither tool, just answer."
    )

    def __init__(self, client: ModelServingClient) -> None:
        super().__init__(client, settings.reasoning_model)

    def render_result(self, name: str, result: Any) -> str:
        """Format retrieved chunks so the model can cite them by name."""
        if name != "search_knowledge_base":
            return super().render_result(name, result)

        if not result:
            return (
                "No internal document matched closely enough to be relevant. "
                "Say so, and do not cite any source."
            )
        return "\n\n".join(
            f"[{i}] source: {hit['source']} (chunk {hit['chunk_index']})\n{hit['text']}"
            for i, hit in enumerate(result, start=1)
        )
