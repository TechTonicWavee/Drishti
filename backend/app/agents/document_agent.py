"""The deliverable specialist."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from app.agents import tool_registry
from app.agents.base_agent import Agent, AgentEvent, Artifact, Delta, ToolUse
from app.agents.tool_registry import ToolError
from app.core.config import settings
from app.services.model_client import ModelServingClient

# Used only by the fallback, to pick a format from the wording of the request.
_DECK_WORDS = re.compile(r"\b(deck|slide|slides|presentation|powerpoint|ppt)\b", re.I)
_SHEET_WORDS = re.compile(
    r"\b(calculation|calculate|spreadsheet|workbook|excel|xlsx|sheet)\b", re.I
)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")


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

    # Sent when the first attempt produced only prose.
    _NUDGE: ClassVar[str] = (
        "You described a document but did not create one. Call the matching "
        "tool now — generate_approval_note, generate_summary_deck or "
        "generate_calculation_sheet — with the real content. Do not reply "
        "with text again."
    )

    def __init__(self, client: ModelServingClient, model: str | None = None) -> None:
        super().__init__(client, model or settings.reasoning_model)

    async def run_stream(
        self, message: str, context: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        """Produce a deliverable, and make sure one actually gets produced.

        The model does not reliably call a generator tool. Asked to draft an
        approval note it will sometimes reply with the text of one, which
        reads like success and leaves the user with no file. So this checks
        whether a file appeared, nudges once, and finally builds one directly.

        The user asked for a deliverable; prose about a deliverable is not it.
        """
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": message},
        ]
        shared = {**context}
        shared.setdefault("artifacts", [])

        produced = 0
        async for event in self.tool_loop(conversation, shared):
            produced += isinstance(event, Artifact)
            yield event
        if produced:
            return

        conversation.append({"role": "user", "content": self._NUDGE})
        async for event in self.tool_loop(conversation, shared):
            produced += isinstance(event, Artifact)
            yield event
        if produced:
            return

        async for event in self._build_directly(message, shared):
            yield event

    async def _build_directly(
        self, message: str, shared: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        """Last resort: generate the document without the model's cooperation.

        Format is chosen from the wording of the request, and the content from
        the findings already in context — which is where the reliable material
        is anyway, since it was extracted rather than composed.
        """
        findings = [str(f) for f in (shared.get("findings") or []) if str(f).strip()]
        if not findings:
            findings = [
                m.group(1).strip()
                for line in message.splitlines()
                if (m := _BULLET.match(line)) and m.group(1).strip()
            ]
        if not findings:
            yield Delta(
                "\n\n_No document was generated: there were no findings to put "
                "in one._"
            )
            return

        source = str(shared.get("source_document") or "the conversation")
        title = f"Approval Note — {source}"

        if _DECK_WORDS.search(message):
            name, args = "generate_summary_deck", {
                "title": f"Summary — {source}",
                "sections": [{"heading": "Findings", "bullets": findings}],
            }
        elif _SHEET_WORDS.search(message):
            name, args = "generate_calculation_sheet", {
                "title": f"Calculation — {source}",
                "steps": [
                    {"step": str(i), "description": f, "formula": "", "result": ""}
                    for i, f in enumerate(findings, start=1)
                ],
            }
        else:
            name, args = "generate_approval_note", {
                "title": title,
                "findings": findings,
                "source_document": source,
            }

        try:
            await tool_registry.call(
                name, args, agent=self.name, context=shared,
                allowed=self.allowed_tools,
            )
        except ToolError as exc:
            yield ToolUse(name, str(exc), ok=False)
            yield Delta(f"\n\n_The document could not be generated: {exc}_")
            return

        # Emit, but never clear: the list is shared with the caller, which
        # tracks its own position in it. Clearing here would hide the file
        # from a delegating agent entirely.
        from app.agents.base_agent import _as_artifact

        for record in shared.get("artifacts", []):
            artifact = _as_artifact(record)
            if artifact is not None:
                yield ToolUse(name, f"generated {artifact.filename}")
                yield artifact

        yield Delta(
            "\n\n_The document was generated directly from the extracted "
            "findings._"
        )
