"""Client for an OpenAI-compatible chat-completions server.

Deliberately vendor-neutral. Ollama and vLLM both expose the same
`/v1/chat/completions` contract, so nothing in this module names either of
them: it speaks the protocol, not the product. Point `MODEL_SERVER_URL` at a
different server and this file keeps working unmodified.

That is the whole point. On a Mac dev machine the URL resolves to Ollama; on
MRPL's Linux + NVIDIA server it resolves to vLLM. Those two names appear in
this docstring to explain the design and nowhere else in the module — not in
the code, the imports, or the error messages, which all speak of "the model
server".

The server is always reached over the local network or a private interface —
this client never talks to a hosted API, and there is no credential to send.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, overload

import httpx

from app.core import outbound

# Sentinel that terminates an OpenAI-compatible SSE stream.
_DONE = "[DONE]"


class ModelServingError(RuntimeError):
    """The model server was unreachable, or answered with something unusable."""


class ModelServingClient:
    """Talks to any OpenAI-compatible chat-completions endpoint.

    One instance is shared for the lifetime of the application so that the
    underlying connection pool is reused; see the lifespan handler in
    `app.main`.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 300.0,
        system_prompt: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # Injected into every conversation that does not already carry a system
        # message. Passed in rather than hard-coded so this module stays a
        # protocol client with no product knowledge in it.
        self.system_prompt = system_prompt
        # Trailing slash matters: httpx resolves relative URLs against the base
        # and would otherwise drop the final path segment (".../v1" + "chat/..."
        # becomes ".../chat/...", losing the version prefix).
        self.base_url = base_url.rstrip("/") + "/"
        # Every request this client makes is counted, so the air-gap badge
        # reflects real traffic rather than an assumption.
        self._client = outbound.attach(
            client
            or httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(timeout, connect=10.0),
            )
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @overload
    async def chat_completion(
        self,
        model: str,
        messages: Sequence[dict[str, str]],
        stream: Literal[True] = ...,
    ) -> AsyncIterator[str]: ...

    @overload
    async def chat_completion(
        self,
        model: str,
        messages: Sequence[dict[str, str]],
        stream: Literal[False],
    ) -> str: ...

    async def chat_completion(
        self,
        model: str,
        messages: Sequence[dict[str, str]],
        stream: bool = True,
    ) -> AsyncIterator[str] | str:
        """Request a completion.

        With `stream=True` (the default) this returns an async iterator that
        yields text deltas as the server produces them — token by token, with
        no buffering of the whole answer. With `stream=False` it returns the
        finished text as a single string.

        Both forms are awaited once; the streaming form is then iterated:

            deltas = await client.chat_completion(model, messages)
            async for delta in deltas:
                ...
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._apply_system_prompt(messages),
            "stream": stream,
        }
        if stream:
            # Not awaited: this hands back the async generator itself, so the
            # HTTP response stays open for as long as the caller iterates.
            return self._stream_deltas(payload)
        return await self._collect(payload)

    async def chat_message(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """One non-streaming turn, returning the whole assistant message.

        Unlike chat_completion this hands back the message object rather than
        its text, because a tool-calling turn carries no text at all — the
        useful part is the `tool_calls` array. Streaming is not used here: a
        decision to call a tool is not worth rendering token by token, and the
        arguments are only valid once complete.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._apply_system_prompt(messages),
            "stream": False,
        }
        if tools:
            payload["tools"] = list(tools)

        try:
            response = await self._client.post("chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelServingError(self._describe_status(exc)) from exc
        except httpx.HTTPError as exc:
            raise ModelServingError(self._describe_transport(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ModelServingError("Model server returned malformed JSON.") from exc

        try:
            return body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelServingError(
                "Model server returned a response in an unexpected shape."
            ) from exc

    async def embed(
        self, model: str, texts: Sequence[str]
    ) -> list[list[float]]:
        """Embed one or more texts, returning vectors in the input order.

        `/v1/embeddings` is part of the same OpenAI-compatible surface as
        chat completions, so this stays engine-neutral: Ollama serves it today
        and vLLM serves it on the GPU server.
        """
        if not texts:
            return []

        payload = {"model": model, "input": list(texts)}
        try:
            response = await self._client.post("embeddings", json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelServingError(self._describe_status(exc)) from exc
        except httpx.HTTPError as exc:
            raise ModelServingError(self._describe_transport(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ModelServingError("Model server returned malformed JSON.") from exc

        try:
            # The server may return items out of order; "index" is authoritative.
            items = sorted(body["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in items]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelServingError(
                "Model server returned embeddings in an unexpected shape."
            ) from exc

        if len(vectors) != len(texts):
            raise ModelServingError(
                f"Asked for {len(texts)} embeddings but received {len(vectors)}."
            )
        return vectors

    def _apply_system_prompt(
        self, messages: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Prepend the configured system message.

        A caller that supplies its own system message wins — this only fills a
        gap, so callers keep the ability to override without fighting us.
        """
        conversation: list[dict[str, Any]] = list(messages)
        if not self.system_prompt:
            return conversation
        if any(m.get("role") == "system" for m in conversation):
            return conversation
        return [{"role": "system", "content": self.system_prompt}, *conversation]

    async def _collect(self, payload: dict[str, Any]) -> str:
        try:
            response = await self._client.post("chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelServingError(self._describe_status(exc)) from exc
        except httpx.HTTPError as exc:
            raise ModelServingError(self._describe_transport(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ModelServingError("Model server returned malformed JSON.") from exc

        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelServingError(
                "Model server returned a response in an unexpected shape."
            ) from exc

    async def _stream_deltas(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        try:
            async with self._client.stream(
                "POST", "chat/completions", json=payload
            ) as response:
                if response.status_code >= 400:
                    # The body has not been read yet on a streaming response.
                    await response.aread()
                    raise ModelServingError(
                        self._describe_status_response(response)
                    )

                async for line in response.aiter_lines():
                    delta = _parse_sse_line(line)
                    if delta is None:
                        continue
                    if delta is _StreamEnd:
                        return
                    yield delta
        except httpx.HTTPError as exc:
            raise ModelServingError(self._describe_transport(exc)) from exc

    # -- error messages -----------------------------------------------------
    # Phrased in terms of "the model server" so they read correctly whichever
    # engine is actually configured.

    def _describe_transport(self, exc: httpx.HTTPError) -> str:
        return (
            f"Could not reach the model server at {self.base_url}. "
            f"Check that it is running and that MODEL_SERVER_URL is correct. "
            f"({type(exc).__name__})"
        )

    def _describe_status(self, exc: httpx.HTTPStatusError) -> str:
        return self._describe_status_response(exc.response)

    def _describe_status_response(self, response: httpx.Response) -> str:
        detail = response.text.strip()
        if len(detail) > 400:
            detail = detail[:400] + "…"
        suffix = f" — {detail}" if detail else ""
        return f"Model server returned HTTP {response.status_code}{suffix}"


class _StreamEnd:
    """Marker for the `[DONE]` sentinel; never yielded to callers."""


def _parse_sse_line(line: str) -> str | type[_StreamEnd] | None:
    """Turn one SSE line into a text delta.

    Returns the delta, `_StreamEnd` at the terminating sentinel, or None for
    lines that carry nothing to display (keep-alives, comments, the initial
    chunk that only announces the assistant role).
    """
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None

    data = line[len("data:") :].strip()
    if data == _DONE:
        return _StreamEnd

    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        # A malformed chunk mid-stream is not worth aborting an otherwise
        # good answer for.
        return None

    choices = chunk.get("choices")
    if not choices:
        return None

    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content if content else None
