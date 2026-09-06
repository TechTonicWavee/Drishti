"""The coding specialist."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from app.agents import tool_registry
from app.agents.base_agent import Agent, AgentEvent, Delta, Execution, ToolUse
from app.agents.tool_registry import ToolError
from app.core.config import settings
from app.services.model_client import ModelServingClient, ModelServingError

# Fenced Python blocks. The language tag is optional because models are
# inconsistent about it, but a tagged block wins when both are present.
_PY_FENCE = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.S | re.I)
_ANY_FENCE = re.compile(r"```[a-z]*\s*\n(.*?)```", re.S | re.I)


class CoderAgent(Agent):
    """Writes code and verifies it by actually running it in the sandbox.

    It cannot search documents — an SOP corpus is noise in a request to write
    a script — and it cannot delegate, which also means a delegated
    sub-question cannot bounce back and start a loop.

    Why this overrides run_stream instead of using the base tool loop:
    qwen2.5-coder:7b does not emit real tool calls. Ollama advertises the
    `tools` capability for it, but in practice it writes the tool-call JSON
    into its reply as text and never populates tool_calls — measured at 0 out
    of 3 attempts on a plain "write a fibonacci script" prompt.

    Relying on the model to choose to verify would therefore mean never
    verifying. Instead the code it writes is extracted and run
    unconditionally, which also matches the requirement more closely: the code
    is *always* checked, not checked whenever the model remembers to ask.

    Execution still goes through tool_registry.call, so the whitelist check
    and the central tools.log entry apply exactly as they would for a
    model-initiated call.
    """

    name: ClassVar[str] = "Coder Agent"
    allowed_tools: ClassVar[list[str]] = ["execute_code"]

    # One retry, enforced structurally rather than requested in the prompt.
    max_corrections: ClassVar[int] = 1

    instructions: ClassVar[str] = (
        "You are the coding specialist for a refinery engineering team. "
        "Write correct, readable code and keep explanations short. Prefer the "
        "Python standard library unless a dependency is clearly warranted.\n"
        "- Put the complete, runnable program in a single ```python fenced "
        "block. It will be executed automatically and its real output shown "
        "to the user, so it must run as written.\n"
        "- The sandbox has no network access and a read-only filesystem apart "
        "from /tmp. Do not fetch from the internet or write outside /tmp.\n"
        "- Do not claim what the output will be. It will be run and the real "
        "output displayed.\n"
        "- When a request is ambiguous, state the assumption you made and "
        "answer anyway rather than asking a question back — you are often "
        "answering on behalf of another agent that cannot reply."
    )

    def __init__(self, client: ModelServingClient, model: str | None = None) -> None:
        super().__init__(client, model or settings.coding_model)

    async def run_stream(
        self, message: str, context: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": message},
        ]
        tool_context = {**context, "client": self.client, "agent": self.name}

        for attempt in range(self.max_corrections + 1):
            answer = ""
            try:
                async for event in self.client.stream_events(
                    self.model, conversation
                ):
                    if event["type"] == "delta":
                        answer += event["text"]
                        yield Delta(event["text"])
            except ModelServingError as exc:
                yield Delta(f"\n\n[the model server failed: {exc}]")
                return

            code = _extract_python(answer)
            if not code:
                # Nothing runnable was written — an explanation, or a question.
                return

            try:
                result = await tool_registry.call(
                    "execute_code",
                    {"code": code},
                    agent=self.name,
                    context=tool_context,
                    allowed=self.allowed_tools,
                )
            except ToolError as exc:
                # The sandbox itself is unavailable. Say so rather than
                # implying the code was checked.
                yield ToolUse("execute_code", str(exc), ok=False)
                yield Delta(f"\n\n_Could not verify this code: {exc}_")
                return

            tool = tool_registry.get("execute_code")
            yield ToolUse("execute_code", tool.summarize(result) if tool else "ok")
            yield Execution(
                code=code,
                stdout=result["stdout"],
                stderr=result["stderr"],
                exit_code=result["exit_code"],
                timed_out=result["timed_out"],
            )

            succeeded = result["exit_code"] == 0 and not result["timed_out"]
            if succeeded:
                yield Delta("\n\n_Verified: the code above ran successfully._")
                return

            if attempt >= self.max_corrections:
                # Out of retries. Report the failure rather than dressing it up.
                yield Delta(
                    "\n\n_The code still fails after one correction attempt. "
                    "The error output above is the real result — it has not "
                    "been fixed._"
                )
                return

            yield Delta("\n\n---\n\n**That failed. Correcting it once…**\n\n")
            conversation.append({"role": "assistant", "content": answer})
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        "That code failed when it was run.\n\n"
                        f"exit code: {result['exit_code']}\n"
                        f"timed out: {result['timed_out']}\n"
                        f"stderr:\n{result['stderr'][:2000]}\n\n"
                        "Fix it and reply with the corrected complete program "
                        "in a single ```python block. Do not explain at length."
                    ),
                }
            )


def _extract_python(text: str) -> str | None:
    """Pull the runnable program out of a model reply.

    Prefers explicitly tagged Python blocks, then any fenced block. The
    longest match wins: models often emit a short example invocation
    alongside the real program, and the program is the longer one.
    """
    for pattern in (_PY_FENCE, _ANY_FENCE):
        blocks = [b.strip() for b in pattern.findall(text) if b.strip()]
        # Ignore blocks that are obviously not Python — models sometimes emit
        # a JSON tool-call sketch, which must never be executed.
        blocks = [b for b in blocks if not b.lstrip().startswith(("{", "["))]
        if blocks:
            return max(blocks, key=len)
    return None
