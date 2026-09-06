"""Shared file-logger construction.

The audit logs (routing, tools, delegation) each go to their own file under
backend/logs/ so a reviewer can read one concern at a time. They are audit
trails rather than console noise, so nothing here propagates to the root
logger.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

# backend/app/core/logs.py -> backend/
LOG_DIR: Final = Path(__file__).resolve().parents[2] / "logs"


def get_file_logger(name: str, filename: str) -> logging.Logger:
    """A logger writing to backend/logs/<filename>, created once per name."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    # Guard against duplicate handlers when modules are re-imported under
    # uvicorn's reloader.
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_DIR / filename, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    logger.propagate = False
    return logger
