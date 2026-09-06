"""Agent base class.

An agent is a name, a bound model, a system prompt, and a whitelist of tool
names. It owns its own turn: deciding whether to use a tool, running it
through the registry, feeding the result back to the model, and producing an
answer.

Two entry points, because they answer different needs:

  run()        — returns the finished answer as a string, matching the agent
                 contract used by delegation, where a caller wants an answer
                 rather than a stream.
  run_stream() — yields events as they happen, which is what the HTTP routes
                 use so tokens still reach the browser one at a time.

run() is implemented on top of run_stream(), so there is one implementation of
the agent loop and the two cannot drift apart.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.agents import tool_registry
from app.agents.tool_registry import ToolError
from app.core.config import settings
from app.services.model_client import ModelServingClient, ModelServingError


@dataclass(frozen=True)
class Delta:
    """A fragment of the answer text."""

    text: str


@dataclass(frozen=True)
class ToolUse:
    """A tool ran. Carries the short summary, not the full result."""

    tool: str
    summary: str
    ok: bool = True


@dataclass(frozen=True)
class Execution:
    """Code was run in the sandbox. Carries the code and what it produced."""

    code: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


@dataclass(frozen=True)
class Artifact:
    """A real file was generated and can be downloaded."""

    filename: str
    kind: str
    url: str
    size_bytes: int


@dataclass(frozen=True)
class Sources:
    """Documents the answer is grounded in."""

    sources: list[dict[str, Any]] = field(default_factory=list)


AgentEvent = Delta | ToolUse | Sources | Execution | Artifact


class Agent:
    """Base class. Subclasses set the class attributes below."""

    name: ClassVar[str] = "Agent"
    instructions: ClassVar[str] = ""
    allowed_tools: ClassVar[list[str]] = []

    # A tool result can invite another tool call. This caps the loop so a
    # model that keeps reaching for tools cannot spin indefinitely.
    max_tool_rounds: ClassVar[int] = 3

    def __init__(self, client: ModelServingClient, model: str | None = None) -> None:
        self.client = client
        self._model = model

    @property
    def model(self) -> str:
        """The bound model. Subclasses name a settings field; this resolves it."""
        return self._model or settings.default_model

    @property
    def tool_model(self) -> str:
        """The model used for tool-calling turns.

        Usually the agent's own model. It is separate because not every model
        that is good at an agent's core job can call tools at all — the vision
        model cannot, and Ollama rejects such a request outright — so such an
        agent runs its handoff turn on a tool-capable model instead.
        """
        return self.model

    @property
    def system_prompt(self) -> str:
        """The agent's instructions, on top of the workbench-wide prompt.

        settings.system_prompt is included explicitly because
        ModelServingClient only injects it when no system message is present.
        Building one without it would silently drop the English-language rule.
        """
        if not self.instructions:
            return settings.system_prompt
        return f"{settings.system_prompt}\n\n{self.instructions}"

    async def run(self, message: str, context: dict[str, Any]) -> str:
        """Execute a turn and return the finished answer."""
        parts: list[str] = []
        async for event in self.run_stream(message, context):
            if isinstance(event, Delta):
                parts.append(event.text)
        return "".join(parts).strip()

    async def run_stream(
        self, message: str, context: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        """Execute a turn, yielding events as they happen."""
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": message},
        ]
        async for event in self.tool_loop(conversation, context):
            yield event

    async def tool_loop(
        self,
        conversation: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]:
        """Run the tool-calling loop over an already-built conversation.

        Separated from run_stream so a subclass can seed the conversation with
        work it did by other means — the vision agent puts its extracted
        findings in before handing over — and still get the same loop.
        """
        # Tools receive the shared client and the calling agent's name, which
        # is what makes delegation and its logging possible.
        tool_context = {**context, "client": self.client, "agent": self.name}
        # Shared, mutable, and passed by reference into every tool and every
        # delegated sub-agent. A generator tool appends here, so a file
        # produced two levels down — vision hands off to document, which calls
        # a generator — still surfaces as a download on this turn. Returning
        # the path through the tool result alone would lose it, because
        # delegation collects only the sub-agent's text.
        tool_context.setdefault("artifacts", [])
        specs = tool_registry.specs(self.allowed_tools)

        # How many artifacts this loop has already emitted. An index, not a
        # drain: the list is shared by reference with every delegated
        # sub-agent, and a sub-agent that emptied it would leave its caller
        # nothing to report — the file would exist on disk and never be
        # offered. Each level keeps its own count and emits what is new to it.
        emitted = 0

        for _ in range(self.max_tool_rounds):
            calls: list[dict[str, Any]] = []
            try:
                async for event in self.client.stream_events(
                    self.tool_model, conversation, tools=specs or None
                ):
                    if event["type"] == "delta":
                        yield Delta(event["text"])
                    else:
                        calls = event["calls"]
            except ModelServingError as exc:
                yield Delta(f"\n\n[the model server failed: {exc}]")
                return

            if not calls:
                return

            # Record the model's request before the results, so the
            # conversation stays a valid tool-calling exchange.
            conversation.append(
                {
                    "role": "assistant",
                    "content": None,
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

            for call in calls:
                async for event in self._invoke(call, tool_context, conversation):
                    yield event

                recorded = tool_context.get("artifacts") or []
                while emitted < len(recorded):
                    artifact = _as_artifact(recorded[emitted])
                    emitted += 1
                    if artifact is not None:
                        yield artifact

        # Ran out of rounds with tools still being requested. Ask once more
        # without tools so the turn ends with an answer rather than silence.
        try:
            deltas = await self.client.chat_completion(self.tool_model, conversation)
            async for text in deltas:
                yield Delta(text)
        except ModelServingError as exc:
            yield Delta(f"\n\n[the model server failed: {exc}]")

    async def _invoke(
        self,
        call: dict[str, Any],
        tool_context: dict[str, Any],
        conversation: list[dict[str, Any]],
    ) -> AsyncIterator[AgentEvent]:
        """Run one tool call and append its result to the conversation."""
        name = call["name"]
        try:
            arguments = json.loads(call["arguments"] or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments were not a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            # The model produced malformed arguments. Tell it so, rather than
            # failing the turn — it can usually correct itself.
            yield ToolUse(name, f"invalid arguments: {exc}", ok=False)
            conversation.append(
                self._tool_reply(call, f"Error: could not parse arguments ({exc}).")
            )
            return

        try:
            result = await tool_registry.call(
                name,
                arguments,
                agent=self.name,
                context=tool_context,
                allowed=self.allowed_tools,
            )
        except ToolError as exc:
            yield ToolUse(name, str(exc), ok=False)
            conversation.append(self._tool_reply(call, f"Error: {exc}"))
            return

        tool = tool_registry.get(name)
        yield ToolUse(name, tool.summarize(result) if tool else "ok")

        # Retrieval results also drive the Sources line in the UI.
        if name == "search_knowledge_base" and isinstance(result, list):
            yield Sources(_unique_sources(result))

        # Execution results are rendered as their own block, so the user sees
        # the real output rather than only the model's account of it. Both
        # attempts of a self-correction surface, which is the point: a silent
        # first failure would make a retry look like a first success.
        if name == "execute_code" and isinstance(result, dict):
            yield Execution(
                code=arguments.get("code", ""),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                exit_code=int(result.get("exit_code", -1)),
                timed_out=bool(result.get("timed_out", False)),
            )

        conversation.append(self._tool_reply(call, self.render_result(name, result)))

    @staticmethod
    def _tool_reply(call: dict[str, Any], content: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call["id"], "content": content}

    def render_result(self, name: str, result: Any) -> str:
        """Turn a tool result into text the model can read.

        Subclasses override for tool-specific formatting; the default is a
        readable JSON dump.
        """
        if isinstance(result, str):
            return result
        return json.dumps(result, default=str, indent=2)


def _as_artifact(record: dict[str, str]) -> Artifact | None:
    """Describe a generated file for the UI, or None if it is not on disk."""
    path = Path(record.get("path", ""))
    if not path.is_file():
        return None
    return Artifact(
        filename=path.name,
        kind=record.get("kind", "document"),
        # Relative so the browser stays same-origin; the dev server proxies it.
        url=f"/api/files/{path.name}",
        size_bytes=path.stat().st_size,
    )


# Enough of the chunk to show which part of a document was used, without
# reproducing the whole thing in the chat transcript.
_EXCERPT_CHARS = 320


def _unique_sources(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per document, carrying its closest-matching chunk.

    The excerpt and chunk index are included so a citation can be opened and
    checked. "This came from the FCC SOP" is an assertion; showing the passage
    it came from lets the reader verify it.
    """
    best: dict[str, dict[str, Any]] = {}
    for hit in hits:
        if not isinstance(hit, dict) or "source" not in hit:
            continue
        source = hit["source"]
        distance = float(hit.get("distance", 1.0))
        if source in best and best[source]["distance"] <= distance:
            continue

        text = " ".join(str(hit.get("text", "")).split())
        excerpt = (
            text if len(text) <= _EXCERPT_CHARS else text[:_EXCERPT_CHARS] + "…"
        )
        best[source] = {
            "source": source,
            "distance": round(distance, 4),
            "chunk_index": hit.get("chunk_index", -1),
            "excerpt": excerpt,
        }
    return sorted(best.values(), key=lambda entry: entry["distance"])
