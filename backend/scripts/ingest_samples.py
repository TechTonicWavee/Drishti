#!/usr/bin/env python
"""Ingest every sample document into the local vector store.

Run from the backend directory:

    .venv/bin/python scripts/ingest_samples.py

Safe to run repeatedly: each document replaces its own previous chunks rather
than duplicating them. Requires the local model server to be running and the
embedding model to be present:

    ollama pull nomic-embed-text
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as a plain script rather than a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.knowledge_base import (  # noqa: E402
    SAMPLE_DOCS_PATH,
    aclose,
    document_count,
    ingest_document,
)
from app.services.model_client import ModelServingError  # noqa: E402


async def main() -> int:
    documents = sorted(
        p for p in SAMPLE_DOCS_PATH.glob("*") if p.suffix.lower() in {".txt", ".pdf"}
    )
    if not documents:
        print(f"No documents found in {SAMPLE_DOCS_PATH}")
        return 1

    print(f"Ingesting {len(documents)} document(s) from {SAMPLE_DOCS_PATH}\n")
    try:
        for path in documents:
            before = document_count()
            await ingest_document(str(path))
            added = document_count() - before
            print(f"  {path.name:<45} {added:>3} chunk(s)")
    except ModelServingError as exc:
        # Much the most likely failure: the model server is not running, or the
        # embedding model was never pulled.
        print(f"\nEmbedding failed: {exc}", file=sys.stderr)
        print(
            "Is the model server running, and has `ollama pull "
            "nomic-embed-text` been done?",
            file=sys.stderr,
        )
        return 1
    finally:
        await aclose()

    print(f"\nStored {document_count()} chunk(s) total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
