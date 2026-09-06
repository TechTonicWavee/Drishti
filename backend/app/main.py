"""Drishti Workbench API.

A self-hosted, air-gapped agentic AI workbench. This process makes no outbound
network calls except to the OpenAI-compatible model server configured as
MODEL_SERVER_URL, which lives on the local machine or the private network.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import chat, health
from app.services.model_client import ModelServingClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One client, one connection pool, for the life of the process.
    app.state.model_client = ModelServingClient(
        settings.model_server_url,
        timeout=settings.model_request_timeout_seconds,
        system_prompt=settings.system_prompt,
    )
    try:
        yield
    finally:
        await app.state.model_client.aclose()


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
app.include_router(chat.router)
