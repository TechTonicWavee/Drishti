"""Drishti Workbench API.

A self-hosted, air-gapped agentic AI workbench. This process makes no outbound
network calls except to the OpenAI-compatible model server configured as
MODEL_SERVER_URL, which lives on the local machine or the private network.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import (
    audit,
    auth,
    chat,
    documents,
    files,
    health,
    memory,
    plant_graph,
    system,
    threads,
)
from app.services import auth_service
from app.services.model_client import ModelServingClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize authentication storage and seed accounts (demo & operator)
    auth_service.seed_initial_users()

    # One client, one connection pool, for the life of the process.
    app.state.model_client = ModelServingClient(
        settings.model_server_url,
        # The longest operation sets the ceiling. A vision turn renders and
        # reads a full page and takes far longer than a text turn; httpx
        # applies this as a read timeout, so a generous value costs a short
        # call nothing — the 10s connect timeout still catches a dead server.
        timeout=max(
            settings.model_request_timeout_seconds,
            settings.vision_request_timeout_seconds,
        ),
        system_prompt=settings.system_prompt,
    )
    # First run on a fresh machine: index the sample procedures in the
    # background so questions have documents to cite, without anyone having to
    # remember scripts/ingest_samples.py. Never blocks or fails start-up.
    indexing = asyncio.create_task(_index_library_if_empty(app.state.model_client))
    try:
        yield
    finally:
        indexing.cancel()
        await app.state.model_client.aclose()


async def _index_library_if_empty(client: ModelServingClient) -> None:
    log = logging.getLogger("uvicorn.error")
    try:
        from app.services import knowledge_base

        if knowledge_base.document_count() > 0:
            return
        files = sorted(
            p for p in knowledge_base.SAMPLE_DOCS_PATH.glob("*")
            if p.suffix.lower() in {".txt", ".pdf", ".md"}
        )
        for path in files:
            await knowledge_base.ingest_document(str(path), client=client)
        log.info("Drishti: indexed %d document(s) into the empty library", len(files))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("Drishti: automatic indexing skipped (%s). Run scripts/ingest_samples.py.", exc)


app = FastAPI(
    title="Drishti Workbench API",
    version="0.1.0",
    summary="Air-gapped agentic AI workbench for on-premise industrial use.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(system.router)
app.include_router(files.router)
app.include_router(documents.router)
app.include_router(memory.router)
app.include_router(threads.router)
app.include_router(audit.router)
app.include_router(plant_graph.router)
