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
                  json.dumps(arguments)[:120], exc)
        raise ToolError(f"Bad arguments for {name}: {exc}") from exc
    except Exception as exc:
        log.error('agent=%s | tool=%s | FAILED | %s: %s', agent, name,
                  type(exc).__name__, exc)
        raise ToolError(f"{name} failed: {exc}") from exc

    log.info(
        'agent=%s | tool=%s | args=%s | result=%s',
        agent, name, json.dumps(arguments, default=str)[:120],
        tool.summarize(result),
    )
    return result
