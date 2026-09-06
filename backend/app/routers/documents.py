"""Knowledge base management.

Adding a document here is different from dropping a scan on the chat: this
indexes the file so future questions can be answered from it, rather than
reading it once and moving on.

Filenames are kept human-readable rather than replaced with a UUID, because
the filename is what appears in a citation. "According to
fcc_unit_shutdown_procedure.txt" is checkable; "according to
a3f9c2...docx" is not. That makes sanitising the name the job here, since a
client-supplied name is reaching the filesystem.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import settings
from app.services import knowledge_base
from app.services.dependencies import get_model_client
from app.services.knowledge_base import LIBRARY_PATH
from app.services.model_client import ModelServingClient, ModelServingError

router = APIRouter(prefix="/documents", tags=["documents"])

_ACCEPTED: Final = frozenset({".txt", ".pdf", ".md"})

# Everything outside this set becomes an underscore. Deliberately strict:
# the result is written to disk and echoed back in citations.
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")


class Document(BaseModel):
    source: str
    chunks: int
    on_disk: bool


class IngestResult(BaseModel):
    source: str
    chunks: int
    total_chunks: int
    replaced: bool


def _safe_name(raw: str | None) -> str:
    """Reduce a client-supplied filename to something safe to write."""
    name = Path(raw or "").name          # strips any directory component
    name = _UNSAFE.sub("_", name).strip(" ._")
    if not name:
        raise HTTPException(status_code=400, detail="Unusable filename.")

    suffix = Path(name).suffix.lower()
    if suffix not in _ACCEPTED:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix or 'unknown'}'. "
                f"Accepted: {', '.join(sorted(_ACCEPTED))}"
            ),
        )

    # Belt and braces: the sanitised name must still resolve inside the library.
    if not (LIBRARY_PATH / name).resolve().is_relative_to(LIBRARY_PATH.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return name


@router.get("", response_model=list[Document])
async def list_documents() -> list[Document]:
    """Everything currently searchable."""
    return [Document(**d) for d in knowledge_base.list_documents()]


@router.post("", response_model=IngestResult)
async def add_document(
    file: UploadFile = File(...),
    client: ModelServingClient = Depends(get_model_client),
) -> IngestResult:
    """Store a document and index it for retrieval."""
    name = _safe_name(file.filename)
    LIBRARY_PATH.mkdir(parents=True, exist_ok=True)
    destination = LIBRARY_PATH / name

    # Uploading the same name updates that document rather than creating a
    # near-duplicate: ingest_document already replaces a file's chunks, so
    # anything else would leave two versions answering the same question.
    replaced = destination.is_file()

    written = 0
    with destination.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > settings.max_upload_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the "
                    f"{settings.max_upload_bytes // (1024 * 1024)}MB limit.",
                )
            handle.write(chunk)

    if written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file was empty.")

    try:
        await knowledge_base.ingest_document(str(destination), client=client)
    except ModelServingError as exc:
        # Embedding failed, so nothing is searchable. Remove the file rather
        # than leaving it on disk looking indexed.
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not embed the document: {exc}. Is the model server "
                f"running, and has '{settings.embedding_model}' been pulled?"
            ),
        ) from exc
    except (ValueError, FileNotFoundError) as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    indexed = {d["source"]: d["chunks"] for d in knowledge_base.list_documents()}
    return IngestResult(
        source=name,
        chunks=indexed.get(name, 0),
        total_chunks=knowledge_base.document_count(),
        replaced=replaced,
    )


@router.delete("/{source}", response_model=list[Document])
async def remove_document(source: str) -> list[Document]:
    """Drop a document from the index and disk, returning what remains."""
    try:
        removed = knowledge_base.remove_document(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if removed == 0:
        raise HTTPException(status_code=404, detail="No such document.")
    return [Document(**d) for d in knowledge_base.list_documents()]
