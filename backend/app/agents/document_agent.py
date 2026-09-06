"""The deliverable specialist."""

from __future__ import annotations

from typing import ClassVar

from app.agents.base_agent import Agent
from app.core.config import settings
from app.services.model_client import ModelServingClient


class DocumentAgent(Agent):
    """Turns findings and summaries into real Word, PowerPoint or Excel files.

    Bound to the reasoning model rather than a specialist one: its work is
    choosing the right document type and drafting the wording that goes in it,
    both of which are language tasks. The file writing itself is done by the
    generator tools, which involve no model at all.
    """

    name: ClassVar[str] = "Document Agent"
    allowed_tools: ClassVar[list[str]] = [
        "generate_approval_note",
        "generate_summary_deck",
        "generate_calculation_sheet",
    ]

    # One round to generate, one to report on it. More would let a model that
    # is pleased with itself produce three near-identical files.
    max_tool_rounds: ClassVar[int] = 2

    instructions: ClassVar[str] = (
        "You produce real, downloadable documents for MRPL refinery staff.\n"
        "- Choose the format that fits the request: an approval note (.docx) "
        "for sign-off on findings; a summary deck (.pptx) when slides or a "
        "presentation are wanted; a calculation sheet (.xlsx) for anything "
        "worked out step by step.\n"
        "- You must call the matching tool. Describing the document you would "
        "write is not the task — the user needs a file.\n"
        "- Generate exactly one document unless more than one is clearly "
        "asked for.\n"
        "- Write the real wording. Every field must contain finished text a "
        "person could sign or present. Never emit placeholders such as "
        "'[insert finding]', 'TBD', 'Lorem ipsum' or 'example text'.\n"
        "- Carry the source material through faithfully. Keep equipment tags, "
        "measurements and dates exactly as given; do not round, reword or "
        "summarise a measurement away.\n"
        "- For a calculation sheet, include every intermediate step with its "
        "formula, not just the final number.\n"
        "- After the tool returns, state in one short sentence what was "
        "created and what it contains. The download is offered separately, so "
        "do not invent a link or a file path."
    )

    def __init__(self, client: ModelServingClient, model: str | None = None) -> None:
        super().__init__(client, model or settings.reasoning_model)
