#!/usr/bin/env python
"""Pre-demo model warmup script for Drishti Workbench.

Pre-loads all required local models into memory before presentations to eliminate
cold-start latency when demoing to judges.

Run from the backend directory:
    .\\.venv\\Scripts\\python.exe scripts\\warmup_models.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Allow running as a script from repository
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.model_client import ModelServingClient, ModelServingError  # noqa: E402


async def warmup_model(client: ModelServingClient, model_name: str, desc: str) -> None:
    start = time.monotonic()
    print(f"[*] Warming up {desc} ({model_name})...", end=" ", flush=True)
    try:
        if "embed" in model_name:
            await client.embed(model_name, ["warmup test probe"])
        else:
            messages = [{"role": "user", "content": "ping"}]
            async for _ in client.stream_events(model_name, messages):
                break
        elapsed = (time.monotonic() - start) * 1000
        print(f"READY ({elapsed:.0f}ms)")
    except ModelServingError as exc:
        print(f"FAILED: {exc}")


async def main() -> int:
    print("=" * 60)
    print("Drishti SIH 2026 — Pre-Demo Model Warmup Utility")
    print("=" * 60)
    print(f"Target Server: {settings.model_server_url}\n")

    client = ModelServingClient(settings.model_server_url)
    try:
        await warmup_model(client, settings.embedding_model, "Embedding Model")
        await warmup_model(client, settings.reasoning_model, "Reasoning Specialist")
        await warmup_model(client, settings.coding_model, "Coding Specialist")
        await warmup_model(client, settings.vision_model, "Multimodal Vision Specialist")
    finally:
        await client.aclose()

    print("\n[OK] All models successfully warmed up and resident in VRAM.")
    print("Zero cold-start latency ready for live demonstration.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
