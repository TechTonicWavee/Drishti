"""The one place tools are defined and invoked.

Agents never hold a reference to a Python function. They hold tool *names*,
and every invocation goes through `call` below. That indirection is the point:
it gives a single choke point where every tool call can be logged, argument
errors can be handled uniformly, and an agent's whitelist can be enforced —
none of which is possible if agents import and call functions directly.

Adding a tool means registering it here and adding its name to an agent's
allowed list. Nowhere else.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.logs import get_file_logger

log = get_file_logger("drishti.tools", "tools.log")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # JSON Schema for the arguments, in the shape the OpenAI-compatible
    # /v1/chat/completions "tools" parameter expects.
    parameters: dict[str, Any]
    func: Callable[..., Awaitable[Any]]
    # Turns a result into one short line for the audit log. Full results can be
    # long — whole document chunks — and a log nobody can read is not an audit
    # trail.
    summarize: Callable[[Any], str]

    # Argument names whose values must never be written to the log. Used for
    # arguments that carry arbitrary content — model-written code above all —
    # so tools.log does not become the dumping ground that sandbox.log was
    # carefully designed not to be.
    sensitive_args: frozenset[str] = frozenset()

    def spec(self) -> dict[str, Any]:
        """This tool as an OpenAI-compatible function definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in _REGISTRY:
        raise ValueError(f"Tool already registered: {tool.name}")
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def names() -> list[str]:
    return sorted(_REGISTRY)


def specs(allowed: list[str]) -> list[dict[str, Any]]:
    """Tool definitions for the names an agent is allowed to use.

    Unknown names are skipped rather than raising: an agent naming a tool that
    does not exist should lose that capability, not fail to start.
    """
    return [_REGISTRY[n].spec() for n in allowed if n in _REGISTRY]


class ToolError(RuntimeError):
    """A tool could not be run. Returned to the model, not raised to the user."""


async def call(
    name: str,
    arguments: dict[str, Any],
    *,
    agent: str,
    context: dict[str, Any],
    allowed: list[str],
) -> Any:
    """Invoke a tool on an agent's behalf, logging the call.

    Enforces the agent's whitelist here rather than trusting the caller: the
    model chooses the tool name, and a model asking for something outside its
    permitted set is exactly the case this needs to catch.
    """
    if name not in allowed:
        log.warning('agent=%s | tool=%s | DENIED (not in allowed list)', agent, name)
        raise ToolError(f"Agent '{agent}' is not permitted to use tool '{name}'.")

    tool = _REGISTRY.get(name)
    if tool is None:
        log.warning('agent=%s | tool=%s | DENIED (not registered)', agent, name)
        raise ToolError(f"No such tool: {name}")

    try:
        result = await tool.func(context=context, **arguments)
    except TypeError as exc:
        # Almost always the model inventing an argument name.
        log.error('agent=%s | tool=%s | BAD ARGS %s | %s', agent, name,
                  _redact(arguments, tool.sensitive_args), exc)
        raise ToolError(f"Bad arguments for {name}: {exc}") from exc
    except Exception as exc:
        log.error('agent=%s | tool=%s | FAILED | %s: %s', agent, name,
                  type(exc).__name__, exc)
        raise ToolError(f"{name} failed: {exc}") from exc

    log.info(
        'agent=%s | tool=%s | args=%s | result=%s',
        agent, name, _redact(arguments, tool.sensitive_args),
        tool.summarize(result),
    )
    return result


def _redact(arguments: dict[str, Any], sensitive: frozenset[str]) -> str:
    """Render arguments for the log, replacing sensitive values with a digest.

    The digest is the same sha256 prefix sandbox.log records, so an entry here
    can still be tied to its execution record without either log holding the
    content.
    """
    shown: dict[str, Any] = {}
    for key, value in arguments.items():
        if key in sensitive:
            text = value if isinstance(value, str) else json.dumps(value, default=str)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            shown[key] = f"<sha256={digest}, {len(text)} chars>"
        else:
            shown[key] = value
    return json.dumps(shown, default=str)[:200]


# ---------------------------------------------------------------------------
# Registered tools
#
# Everything an agent can do is declared below. Adding a capability means
# adding it here and naming it in an agent's allowed_tools — there is no other
# route in.
# ---------------------------------------------------------------------------

from app.core.config import settings  # noqa: E402
from app.core.logs import get_file_logger  # noqa: E402

delegation_log = get_file_logger("drishti.delegation", "delegation.log")

# Delegation is one level deep by design. The Coder Agent holds no tools, so
# it cannot delegate back, but the counter makes that a guarantee rather than
# a consequence of the current configuration.
MAX_DELEGATION_DEPTH = 1

# Ceiling on how long executed code may run, whatever the model asks for. The
# timeout argument is model-supplied, so it is clamped rather than trusted.
MAX_SANDBOX_TIMEOUT = 30


async def _search_knowledge_base(
    *, context: dict[str, Any], query: str, top_k: int | None = None
) -> list[dict[str, Any]]:
    """Retrieve relevant document chunks, filtered by relevance."""
    from app.services import knowledge_base

    hits = await knowledge_base.search(
        query,
        top_k or settings.rag_top_k,
        client=context.get("client"),
    )
    # Filtering here, not at the call site, so every caller gets the same
    # guarantee: an irrelevant chunk never reaches a prompt or the UI.
    return [h for h in hits if h["distance"] <= settings.rag_max_distance]


def _summarize_search(result: Any) -> str:
    if not result:
        return "0 chunks (nothing above the relevance threshold)"
    sources = sorted({h["source"] for h in result})
    nearest = min(h["distance"] for h in result)
    return f"{len(result)} chunk(s) from {', '.join(sources)} (nearest {nearest:.3f})"


async def _ask_coder_agent(*, context: dict[str, Any], question: str) -> str:
    """Hand a coding sub-question to the Coder Agent and return its answer."""
    # Late import: coding_agent imports base_agent, which imports this module.
    # Importing at module level would be a cycle.
    from app.agents.coding_agent import CoderAgent

    asker = context.get("agent", "unknown")
    depth = context.get("delegation_depth", 0)

    if depth >= MAX_DELEGATION_DEPTH:
        delegation_log.warning(
            'from=%s | to=Coder Agent | REFUSED (depth %s) | question="%s"',
            asker, depth, _preview(question),
        )
        raise ToolError("Delegation depth exceeded; answer directly instead.")

    client = context.get("client")
    if client is None:
        raise ToolError("No model client available for delegation.")

    delegation_log.info(
        'from=%s | to=Coder Agent | ASKED | question="%s"', asker, _preview(question)
    )

    coder = CoderAgent(client)
    answer = await coder.run(
        question,
        {**context, "delegation_depth": depth + 1, "delegated_from": asker},
    )

    delegation_log.info(
        'from=%s | to=Coder Agent | ANSWERED | %d chars | reply="%s"',
        asker, len(answer), _preview(answer),
    )
    return answer


def _preview(text: str, limit: int = 100) -> str:
    return " ".join(text.split())[:limit]


register(
    Tool(
        name="search_knowledge_base",
        description=(
            "Search the plant's internal documents — standard operating "
            "procedures, inspection guidelines, safety procedures — for "
            "excerpts relevant to a question. Use this for anything about "
            "plant equipment, procedures, standards or safety."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for, in plain language.",
                }
            },
            "required": ["query"],
        },
        func=_search_knowledge_base,
        summarize=_summarize_search,
    )
)

register(
    Tool(
        name="ask_coder_agent",
        description=(
            "Delegate a programming task to the coding specialist and get its "
            "answer back. Use this when a request needs code written, "
            "debugged or explained. Pass a self-contained description of only "
            "the coding part."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The coding task, stated so it can be understood "
                        "without the surrounding conversation."
                    ),
                }
            },
            "required": ["question"],
        },
        func=_ask_coder_agent,
        summarize=lambda r: f"delegated; {len(r)} char reply",
    )
)


async def _execute_code(
    *, context: dict[str, Any], code: str, timeout_seconds: int = 10
) -> dict[str, Any]:
    """Run Python in the sandbox and return stdout, stderr and exit code."""
    from app.services.sandbox import execute_code

    # The Docker SDK is blocking. Running it in a thread keeps the event loop
    # free, so other users' answers keep streaming while this code runs.
    return await asyncio.to_thread(
        execute_code,
        code,
        max(1, min(int(timeout_seconds), MAX_SANDBOX_TIMEOUT)),
    )


def _summarize_execution(result: Any) -> str:
    if not isinstance(result, dict):
        return "unexpected result"
    if result.get("timed_out"):
        return "timed out"
    return (
        f"exit={result.get('exit_code')} "
        f"stdout={len(result.get('stdout') or '')}B "
        f"stderr={len(result.get('stderr') or '')}B"
    )


register(
    Tool(
        name="execute_code",
        description=(
            "Run Python code in an isolated sandbox and get back its stdout, "
            "stderr and exit code. The sandbox has no network access and a "
            "read-only filesystem apart from /tmp. Use it to verify that code "
            "you have written actually runs before presenting it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Complete, self-contained Python to run.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Seconds to allow before killing it (max 30).",
                },
            },
            "required": ["code"],
        },
        func=_execute_code,
        summarize=_summarize_execution,
        # Never write model-written code into the audit log.
        sensitive_args=frozenset({"code"}),
    )
)


# --- Deliverable generation -------------------------------------------------


def _record_artifact(context: dict[str, Any], kind: str, path: str) -> str:
    """Note a generated file on the shared artifact list, and return its path."""
    artifacts = context.get("artifacts")
    if isinstance(artifacts, list):
        artifacts.append({"kind": kind, "path": path})
    return path


async def _generate_approval_note(
    *, context: dict[str, Any], findings: list[str], title: str,
    source_document: str | None = None,
) -> str:
    from app.services.document_generator import generate_approval_note

    # Fall back to what the turn already knows. The model frequently omits
    # this argument, and an approval note whose source reads "the
    # conversation" is not traceable back to the scan it came from — which is
    # most of the point of recording a source at all.
    source = (
        source_document
        or context.get("source_document")
        or context.get("attachment_name")
        or "the conversation"
    )

    # Writing a file is blocking; a thread keeps the event loop free.
    path = await asyncio.to_thread(
        generate_approval_note, list(findings), title, str(source)
    )
    return _record_artifact(context, "approval_note", path)


async def _generate_summary_deck(
    *, context: dict[str, Any], title: str, sections: list[dict[str, Any]]
) -> str:
    from app.services.document_generator import generate_summary_deck

    path = await asyncio.to_thread(generate_summary_deck, title, list(sections))
    return _record_artifact(context, "summary_deck", path)


async def _generate_calculation_sheet(
    *, context: dict[str, Any], title: str, steps: list[dict[str, Any]]
) -> str:
    from app.services.document_generator import generate_calculation_sheet

    path = await asyncio.to_thread(generate_calculation_sheet, title, list(steps))
    return _record_artifact(context, "calculation_sheet", path)


def _summarize_file(result: Any) -> str:
    from pathlib import Path

    if not isinstance(result, str) or not result:
        return "no file produced"
    path = Path(result)
    if not path.is_file():
        return f"{path.name} (missing on disk)"
    return f"{path.name}, {path.stat().st_size} bytes"


register(
    Tool(
        name="generate_approval_note",
        description=(
            "Create a Word (.docx) approval note listing findings, with a "
            "signature block for a human to sign. Use this when the user asks "
            "for an approval note, sign-off sheet or inspection note."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title."},
                "findings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One finding per entry, written out in full.",
                },
                "source_document": {
                    "type": "string",
                    "description": "What the findings came from, e.g. a scan filename.",
                },
            },
            "required": ["title", "findings"],
        },
        func=_generate_approval_note,
        summarize=_summarize_file,
    )
)

register(
    Tool(
        name="generate_summary_deck",
        description=(
            "Create a PowerPoint (.pptx) summary deck with a title slide and "
            "one slide per section. Use this when the user asks for slides, a "
            "deck, or a presentation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Deck title."},
                "sections": {
                    "type": "array",
                    "description": "One entry per slide.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["heading", "bullets"],
                    },
                },
            },
            "required": ["title", "sections"],
        },
        func=_generate_summary_deck,
        summarize=_summarize_file,
    )
)

register(
    Tool(
        name="generate_calculation_sheet",
        description=(
            "Create an Excel (.xlsx) calculation sheet with one row per step, "
            "showing description, formula or input, and result. Use this when "
            "the user asks for a calculation, a workbook or a spreadsheet. "
            "Include every intermediate step, not just the final number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Sheet title."},
                "steps": {
                    "type": "array",
                    "description": "One entry per calculation step, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string"},
                            "description": {"type": "string"},
                            "formula": {"type": "string"},
                            "result": {"type": "string"},
                        },
                        "required": ["description", "result"],
                    },
                },
            },
            "required": ["title", "steps"],
        },
        func=_generate_calculation_sheet,
        summarize=_summarize_file,
    )
)


async def _ask_document_agent(*, context: dict[str, Any], request: str) -> str:
    """Hand a deliverable request to the Document Agent and return its reply."""
    from app.agents.document_agent import DocumentAgent

    asker = context.get("agent", "unknown")
    depth = context.get("delegation_depth", 0)

    if depth >= MAX_DELEGATION_DEPTH:
        delegation_log.warning(
            'from=%s | to=Document Agent | REFUSED (depth %s) | request="%s"',
            asker, depth, _preview(request),
        )
        raise ToolError("Delegation depth exceeded; answer directly instead.")

    client = context.get("client")
    if client is None:
        raise ToolError("No model client available for delegation.")

    # Findings travel through the context rather than through the model's
    # arguments. Making the caller retype a page of extracted text into a tool
    # call is how details get dropped or quietly reworded.
    brief = request.strip()
    findings = context.get("findings")
    if findings:
        source = context.get("source_document") or context.get("attachment_name") or "the source document"
        listed = "\n".join(f"- {f}" for f in findings)
        brief = f"{brief}\n\nFindings extracted from {source}:\n{listed}"

    delegation_log.info(
        'from=%s | to=Document Agent | ASKED | request="%s" | findings=%d',
        asker, _preview(request), len(findings or []),
    )

    agent = DocumentAgent(client)
    answer = await agent.run(
        brief,
        {**context, "delegation_depth": depth + 1, "delegated_from": asker},
    )

    delegation_log.info(
        'from=%s | to=Document Agent | ANSWERED | %d chars', asker, len(answer)
    )
    return answer


register(
    Tool(
        name="ask_document_agent",
        description=(
            "Delegate to the document specialist to produce a real "
            "downloadable file — a Word approval note, a PowerPoint deck or an "
            "Excel calculation sheet. Use this whenever the user asks for a "
            "document, note, report, deck, slides or spreadsheet to be drafted "
            "or generated. State what is wanted; extracted findings are passed "
            "along automatically."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": (
                        "What deliverable is wanted and what it should cover."
                    ),
                }
            },
            "required": ["request"],
        },
        func=_ask_document_agent,
        summarize=lambda r: f"delegated; {len(r)} char reply",
    )
)
