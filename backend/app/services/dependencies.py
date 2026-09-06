"""Shared service dependencies.

The model client owns an HTTP connection pool, so a single instance is created
at start-up and reused for every request rather than rebuilt per call.
"""

from fastapi import Request

from app.services.model_client import ModelServingClient


def get_model_client(request: Request) -> ModelServingClient:
    return request.app.state.model_client
