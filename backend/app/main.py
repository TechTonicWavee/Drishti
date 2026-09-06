"""Drishti Workbench API.

A self-hosted, air-gapped agentic AI workbench. This process makes no
outbound network calls except, in future, to a locally-running Ollama on the
host or the local Docker network.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import health

app = FastAPI(
    title="Drishti Workbench API",
    version="0.1.0",
    summary="Air-gapped agentic AI workbench for on-premise industrial use.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
