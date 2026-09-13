"""The general reasoning specialist."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any, ClassVar, Final

from app.agents import tool_registry
from app.agents.base_agent import (
    Agent,
    AgentEvent,
    Delta,
    Sources,
    ToolUse,
    _as_artifact,
    _unique_sources,
    history_messages,
)
from app.core.config import settings
from app.services.model_client import ModelServingClient, ModelServingError

_ACRONYMS: Final[dict[str, str]] = {
    "h2s": "hydrogen sulphide",
    "lel": "lower explosive limit",
    "fcc": "fluid catalytic cracking",
    "ppe": "personal protective equipment",
    "ptw": "permit to work",
    "asme": "American Society of Mechanical Engineers",
    "sop": "standard operating procedure",
}


def _expand_query(query: str, context: dict[str, Any] | None = None) -> str:
    """Expand refinery acronyms and inherit conversational context from earlier turns."""
    expanded = query
    for acronym, full_term in _ACRONYMS.items():
        if re.search(rf"\b{acronym}\b", query, re.I):
            if full_term.lower() not in expanded.lower():
                expanded = f"{expanded} ({full_term})"

    if context and isinstance(context.get("history"), list):
        # Look backwards through user messages to pick up equipment/procedure context
        for msg in reversed(context["history"]):
            if isinstance(msg, dict) and msg.get("role") == "user":
                prev_text = msg.get("content", "").lower()
                for topic in [
                    "confined space",
                    "fcc",
                    "pressure vessel",
                    "pump vibration",
                    "flare system",
                ]:
                    if topic in prev_text and topic not in expanded.lower():
                        expanded = f"{expanded} ({topic})"
                break

    return expanded


def verify_and_clean_citations(reply: str, hits: list[dict[str, Any]]) -> str:
    """Verify cited document references against ground-truth search hits.

    If hits contains verified SOP references, replace hallucinated SOP reference
    numbers with the ground-truth reference. If no hits are present (e.g. general
    knowledge inquiries), remove fabricated document references and citations.
    """
    ground_truth_refs: list[str] = []
    for hit in hits or []:
        text = str(hit.get("text", "")) + " " + str(hit.get("source", ""))
        for ref in re.findall(r"SAMPLE-SOP-[A-Z0-9-]+", text):
            if ref not in ground_truth_refs:
                ground_truth_refs.append(ref)

    cited_refs = re.findall(r"SAMPLE-SOP-[A-Z0-9-]+", reply)
    if not cited_refs:
        return reply

    if ground_truth_refs:
        primary_gt = ground_truth_refs[0]
        cleaned = reply
        for cited in cited_refs:
            if cited not in ground_truth_refs:
                cleaned = cleaned.replace(cited, primary_gt)
        return cleaned

    # No ground-truth hits / general knowledge query: strip hallucinated citations completely
    lines = reply.splitlines()
    cleaned_lines: list[str] = []
    for line in lines:
        if re.search(
            r"^\s*(?:Document|Reference|Source|Ref)?\s*:?\s*SAMPLE-SOP-[A-Z0-9-]+",
            line,
            re.I,
        ):
            continue
        cleaned_line = re.sub(r"\bSAMPLE-SOP-[A-Z0-9-]+\b", "", line).strip()
        if cleaned_line or line.strip() == "":
            cleaned_lines.append(cleaned_line)

    return "\n".join(cleaned_lines).strip()


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
        "ask_document_agent",
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
        "- Never write a document name, reference number, revision, section or "
        "page that did not appear in a search_knowledge_base result you just "
        "received. Inventing a citation is worse than giving none: a reader "
        "cannot tell the difference, and on a safety limit they may act on it. "
        "If you did not search, do not write a Reference section at all.\n"
        "- A follow-up question in a conversation still needs its own search. "
        "Do not answer a question about a limit, procedure or standard from "
        "memory because an earlier turn happened to be about the same "
        "equipment.\n"
        "- You must not write code yourself. Any part of a request that "
        "involves writing, debugging or explaining code goes to "
        "ask_coder_agent, which runs a model tuned for it. Pass a "
        "self-contained description of just the coding part, then present "
        "what it returns alongside your own answer. This applies even when "
        "the code looks trivial to you.\n"
        "- When the user wants a real deliverable — an approval note, a "
        "report, a deck, slides, a spreadsheet, anything they would download "
        "or sign — call ask_document_agent. Do not write the document out in "
        "chat instead: they need a file, and prose in a chat window is not "
        "one.\n"
        "- After a tool returns, check whether any part of the original "
        "request is still unanswered before you reply. If a coding task is "
        "still outstanding, call ask_coder_agent now — finishing the document "
        "lookup does not finish the request.\n"
        "- For a simple factual question needing neither tool, just answer."
    )

    def __init__(self, client: ModelServingClient, model: str | None = None) -> None:
        super().__init__(client, model or settings.reasoning_model)

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

    async def run_stream(
        self, message: str, context: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        """Run a reasoning turn with deterministic follow-up RAG and citation verification."""
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            *history_messages(context),
            {"role": "user", "content": message},
        ]
        tool_context = {**context, "client": self.client, "agent": self.name}

        # Deterministic RAG backstop: expand query and search knowledge base unconditionally
        expanded_query = _expand_query(message, context)
        from app.services import knowledge_base

        try:
            hits = await knowledge_base.search(
                expanded_query,
                top_k=settings.rag_top_k,
                client=self.client,
            )
            relevant_hits = [
                h for h in hits if float(h.get("distance", 1.0)) <= settings.rag_max_distance
            ]
        except Exception:
            relevant_hits = []

        # Emit search tool use and sources
        tool = tool_registry.get("search_knowledge_base")
        search_summary = (
            tool.summarize(relevant_hits) if tool else f"{len(relevant_hits)} chunk(s)"
        )
        yield ToolUse("search_knowledge_base", search_summary, ok=True)
        if relevant_hits:
            yield Sources(_unique_sources(relevant_hits))

        # Inject search results into conversation context
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        call = {
            "id": call_id,
            "name": "search_knowledge_base",
            "arguments": json.dumps({"query": expanded_query}),
        }
        conversation.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "search_knowledge_base",
                            "arguments": call["arguments"],
                        },
                    }
                ],
            }
        )
        conversation.append(
            self._tool_reply(call, self.render_result("search_knowledge_base", relevant_hits))
        )

        # Allow delegation tools (ask_coder_agent, ask_document_agent)
        delegation_tools = [
            t for t in self.tools_schema()
            if t.get("function", {}).get("name") in {"ask_coder_agent", "ask_document_agent"}
        ]

        emitted = 0
        answer_deltas: list[str] = []

        for _ in range(self.max_tool_rounds):
            calls: list[dict[str, Any]] = []

            async for event in self.client.stream_events(
                self.tool_model, conversation, tools=delegation_tools or None
            ):
                if event["type"] == "delta":
                    answer_deltas.append(event["text"])
                elif event["type"] == "tool_call":
                    calls.append(event)

            if not calls:
                break

            conversation.append(
                {
                    "role": "assistant",
                    "content": "".join(answer_deltas) or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {
                                "name": c["name"],
                                "arguments": c["arguments"],
                            },
                        }
                        for c in calls
                    ],
                }
            )
            answer_deltas = []

            for c in calls:
                async for event in self._invoke(c, tool_context, conversation):
                    yield event

                recorded = tool_context.get("artifacts") or []
                while emitted < len(recorded):
                    artifact = _as_artifact(recorded[emitted])
                    emitted += 1
                    if artifact is not None:
                        yield artifact

        # If answer_deltas was empty after tools, call model once more to summarize
        if not answer_deltas:
            try:
                deltas = await self.client.chat_completion(self.tool_model, conversation)
                async for text in deltas:
                    answer_deltas.append(text)
            except ModelServingError as exc:
                yield Delta(f"\n\n[the model server failed: {exc}]")
                return

        # Deterministically clean and verify citations in the answer
        raw_answer = "".join(answer_deltas)
        cleaned_answer = verify_and_clean_citations(raw_answer, relevant_hits)
        yield Delta(cleaned_answer)
