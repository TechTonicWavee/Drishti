"""Local document knowledge base.

Retrieval-augmented generation with no network dependency beyond the local
model server. Documents are chunked, embedded through the same
OpenAI-compatible endpoint that serves chat, and stored in an embedded
ChromaDB instance under backend/data/chroma.

Two ChromaDB defaults are actively unsafe here and are disabled below:

  * Anonymised telemetry posts usage data to PostHog. Switched off through
    both the environment variable and the Settings object, because the two
    have historically been read at different points in start-up.
  * The bundled default embedding function downloads an ONNX model from the
    internet the first time it is called. It is never used: every call passes
    embeddings computed by the local model server explicitly, and the
    collection is created with embedding_function=None so ChromaDB has no
    means of doing it for us.
"""

from __future__ import annotations

import os

# Must precede the chromadb import: the telemetry client reads this during
# module initialisation.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import re
from pathlib import Path
from typing import Any, Final

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.services.model_client import ModelServingClient

# backend/app/services/knowledge_base.py -> backend/
_BACKEND_ROOT: Final = Path(__file__).resolve().parents[2]
CHROMA_PATH: Final = _BACKEND_ROOT / "data" / "chroma"
SAMPLE_DOCS_PATH: Final = _BACKEND_ROOT / "data" / "sample_docs"

_COLLECTION_NAME: Final = "drishti_documents"

# Roughly 500 tokens. English runs about 1.3 tokens per word, so 375 words is
# close to the target without pulling in a tokenizer dependency just to count.
# The overlap keeps a fact that straddles a boundary retrievable from either
# side of it.
CHUNK_WORDS: Final = 375
OVERLAP_WORDS: Final = 60

# Markdown is read as plain text; it needs no separate handling, and refusing
# it would be arbitrary when .txt is accepted.
_SUPPORTED_SUFFIXES: Final = frozenset({".txt", ".pdf", ".md"})

# Documents added through the UI live alongside the bundled samples, so one
# directory is the whole corpus and scripts/ingest_samples.py rebuilds all of
# it after the store is deleted.
LIBRARY_PATH: Final = SAMPLE_DOCS_PATH

_client: chromadb.ClientAPI | None = None
_owned_model_client: ModelServingClient | None = None


def _collection() -> chromadb.Collection:
    """The single persistent collection, created on first use."""
    global _client
    if _client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_PATH),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client.get_or_create_collection(
        name=_COLLECTION_NAME,
        # Cosine distance suits normalised embeddings; the default is L2,
        # whose values would make the relevance threshold meaningless.
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


def _resolve_client(client: ModelServingClient | None) -> ModelServingClient:
    """Use the caller's client, or lazily build one for scripts."""
    global _owned_model_client
    if client is not None:
        return client
    if _owned_model_client is None:
        _owned_model_client = ModelServingClient(settings.model_server_url)
    return _owned_model_client


async def aclose() -> None:
    """Release the client this module created for itself, if any."""
    global _owned_model_client
    if _owned_model_client is not None:
        await _owned_model_client.aclose()
        _owned_model_client = None


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        # A page with no extractable text yields None, not "".
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping, roughly token-sized chunks.

    Paragraphs are kept whole wherever they fit, so a numbered procedure step
    is not cut in half. A paragraph longer than the budget falls back to a
    plain word window.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    def flush() -> None:
        nonlocal current, current_words
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0

    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) > CHUNK_WORDS:
            flush()
            for start in range(0, len(words), CHUNK_WORDS - OVERLAP_WORDS):
                window = words[start : start + CHUNK_WORDS]
                if window:
                    chunks.append(" ".join(window))
            continue
        if current_words + len(words) > CHUNK_WORDS:
            flush()
        current.append(paragraph)
        current_words += len(words)

    flush()

    if len(chunks) <= 1:
        return chunks

    # Prepend the tail of each previous chunk so context that straddles a
    # boundary stays retrievable from both sides.
    overlapped = [chunks[0]]
    for previous, chunk in zip(chunks, chunks[1:]):
        tail = " ".join(previous.split()[-OVERLAP_WORDS:])
        overlapped.append(f"{tail}\n\n{chunk}")
    return overlapped


async def ingest_document(
    filepath: str, *, client: ModelServingClient | None = None
) -> None:
    """Chunk, embed and store one .txt or .pdf file.

    Re-ingesting the same file replaces its chunks rather than duplicating
    them, so the script is safe to run repeatedly.
    """
    path = Path(filepath).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No such document: {path}")
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported file type '{path.suffix}'. "
            f"Supported: {', '.join(sorted(_SUPPORTED_SUFFIXES))}"
        )

    text = _read_text(path)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError(f"No extractable text in {path.name}")

    embeddings = await _resolve_client(client).embed(
        settings.embedding_model, chunks
    )

    collection = _collection()
    # Drop any previous version of this document first: a shorter revision
    # would otherwise leave orphaned chunks behind with stale content.
    collection.delete(where={"source": path.name})
    collection.upsert(
        ids=[f"{path.name}::{i}" for i in range(len(chunks))],
        embeddings=embeddings,
        documents=chunks,
        metadatas=[
            {"source": path.name, "chunk_index": i} for i in range(len(chunks))
        ],
    )


async def search(
    query: str,
    top_k: int = 4,
    *,
    client: ModelServingClient | None = None,
) -> list[dict[str, Any]]:
    """Return the top matching chunks, nearest first.

    Every hit is returned with its distance; filtering by relevance is left to
    the caller, so this stays usable for debugging retrieval as well as for
    answering. See settings.rag_max_distance for the threshold used in chat.
    """
    collection = _collection()
    if collection.count() == 0:
        return []

    vector = (await _resolve_client(client).embed(settings.embedding_model, [query]))[0]
    result = collection.query(
        query_embeddings=[vector],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]

    return [
        {
            "text": document,
            "source": (metadata or {}).get("source", "unknown"),
            "chunk_index": (metadata or {}).get("chunk_index", -1),
            "distance": distance,
        }
        for document, metadata, distance in zip(
            documents[0], metadatas[0], distances[0]
        )
    ]


def document_count() -> int:
    """Number of stored chunks. Useful for scripts and health checks."""
    return _collection().count()


def list_documents() -> list[dict[str, Any]]:
    """Every indexed document, with how many chunks each contributed.

    Read from the store rather than the directory: what matters is what is
    actually searchable, and a file sitting on disk unindexed would otherwise
    look available when it is not.
    """
    collection = _collection()
    if collection.count() == 0:
        return []

    stored = collection.get(include=["metadatas"])
    counts: dict[str, int] = {}
    for metadata in stored.get("metadatas") or []:
        source = (metadata or {}).get("source")
        if source:
            counts[source] = counts.get(source, 0) + 1

    return [
        {
            "source": source,
            "chunks": count,
            # Whether the original file is still on disk. A document can be
            # indexed but have had its source removed, and the UI should not
            # imply the file is there to open.
            "on_disk": (LIBRARY_PATH / source).is_file(),
        }
        for source, count in sorted(counts.items())
    ]


def remove_document(source: str) -> int:
    """Drop a document from the index and delete its file. Returns chunks removed.

    The filename is treated as hostile: only its basename is used, and the
    resolved path must still sit inside the library directory.
    """
    name = Path(source).name
    if not name or name != source:
        raise ValueError("Invalid document name.")

    collection = _collection()
    existing = collection.get(where={"source": name}, include=[])
    removed = len(existing.get("ids") or [])
    if removed:
        collection.delete(where={"source": name})

    path = (LIBRARY_PATH / name).resolve()
    if path.is_relative_to(LIBRARY_PATH.resolve()) and path.is_file():
        path.unlink()

    return removed
