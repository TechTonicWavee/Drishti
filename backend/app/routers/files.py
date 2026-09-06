"""Download endpoint for generated deliverables.

Serves files from backend/data/generated/ and nothing else. The filename
arrives from the network, so it is treated as hostile: the resolved path must
land inside the generated directory or the request is refused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.document_generator import GENERATED_DIR

router = APIRouter(tags=["files"])

# Explicit types so a browser opens the download in the right application
# rather than treating it as an unknown binary.
_MEDIA_TYPES: Final = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/files/{filename}")
async def download(filename: str) -> FileResponse:
    """Serve one generated file by name."""
    # A path parameter cannot normally contain a slash, but percent-encoding
    # and unicode normalisation have both been used to smuggle one. Requiring
    # the name to equal its own basename rejects any path structure outright.
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    root = GENERATED_DIR.resolve()
    candidate = (root / filename).resolve()

    # The containment check is what actually enforces the boundary. It is done
    # after resolving, so symlinks and traversal segments are already collapsed
    # and cannot point outside.
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="No such file.")

    return FileResponse(
        candidate,
        media_type=_MEDIA_TYPES.get(candidate.suffix.lower(), "application/octet-stream"),
        filename=candidate.name,
        # attachment, so a browser downloads rather than trying to render it.
        content_disposition_type="attachment",
    )
