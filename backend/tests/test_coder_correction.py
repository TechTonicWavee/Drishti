"""Deterministic test of the Coder Agent's verify-and-correct loop.

The loop is hard to exercise through the real model, because qwen2.5-coder is
good at avoiding failures once told what the sandbox provides — it will
rewrite a numpy request to use `statistics` rather than fail and retry. That
is the right product behaviour, but it leaves the correction branch untested.

So the model is stubbed here and the sandbox is real: the assertions are about
the agent's control flow, which is what "exactly one self-correction" is a
claim about.

Run:  .venv/bin/python tests/test_coder_correction.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.base_agent import Delta, Execution  # noqa: E402
from app.agents.coding_agent import CoderAgent  # noqa: E402


class StubClient:
    """Replays scripted replies in place of the model. Sandbox stays real."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.system_prompt = None

    async def stream_events(self, model, messages, tools=None):
        self.calls += 1
        reply = self.replies.pop(0) if self.replies else "no more replies"
        yield {"type": "delta", "text": reply}


async def scenario(name: str, replies: list[str]) -> tuple[int, list[Execution], str]:
    client = StubClient(replies)
    agent = CoderAgent(client)  # type: ignore[arg-type]
    executions: list[Execution] = []
    text = ""
    async for event in agent.run_stream("irrelevant", {}):
        if isinstance(event, Execution):
            executions.append(event)
        elif isinstance(event, Delta):
            text += event.text
    print(f"\n── {name}")
    print(f"   model calls   : {client.calls}")
    print(f"   executions    : {len(executions)} -> exit codes {[e.exit_code for e in executions]}")
    return client.calls, executions, text


BAD = "```python\nraise ValueError('first attempt fails')\n```"
GOOD = "```python\nprint('corrected output')\n```"


async def main() -> int:
    failures = 0

    # 1. First attempt works: one execution, no retry.
    calls, execs, text = await scenario("succeeds first time", [GOOD])
    ok = calls == 1 and len(execs) == 1 and execs[0].exit_code == 0
    ok &= "Verified" in text
    print(f"   {'PASS' if ok else 'FAIL'}  one run, no correction, reported verified")
    failures += not ok

    # 2. Fails then is corrected: exactly two executions, honest success.
    calls, execs, text = await scenario("fails then corrects", [BAD, GOOD])
    ok = calls == 2 and len(execs) == 2
    ok &= execs[0].exit_code != 0 and execs[1].exit_code == 0
    ok &= "corrected output" in execs[1].stdout
    ok &= "Correcting it once" in text and "Verified" in text
    print(f"   {'PASS' if ok else 'FAIL'}  exactly one correction, then verified success")
    failures += not ok

    # 3. Fails twice: stops after one retry and says so, rather than looping.
    calls, execs, text = await scenario("fails twice", [BAD, BAD, GOOD])
    ok = calls == 2 and len(execs) == 2
    ok &= all(e.exit_code != 0 for e in execs)
    ok &= "still fails after one correction attempt" in text
    ok &= "Verified" not in text
    print(f"   {'PASS' if ok else 'FAIL'}  stopped after one retry, reported failure honestly")
    failures += not ok

    # 4. No code in the reply: nothing is executed.
    calls, execs, text = await scenario("prose only", ["Here is some advice, no code."])
    ok = calls == 1 and len(execs) == 0
    print(f"   {'PASS' if ok else 'FAIL'}  no code, nothing executed")
    failures += not ok

    print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
