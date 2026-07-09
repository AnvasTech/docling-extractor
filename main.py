"""Application entrypoint.

Stateless Intelligent PDF Extraction & OCR Orchestrator for the Indian Property
Title Verification platform. Wires the API routers and starts the async job
workers. No persistence — see ARCHITECTURE in README.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import extract as extract_api
from api import health as health_api
from core.config import settings
from core.logging_setup import configure_logging, get_logger, log
import logging
from services import job_queue

configure_logging(settings.log_level)
logger = get_logger("startup")


def _warmup() -> None:
    """Preload OCR models so the first request doesn't pay model-load latency.

    Best-effort and off the request path — a failure here only means the old
    lazy-load behavior for that engine.
    """
    codes = [c.strip() for c in settings.warmup_langs.split(",") if c.strip()]
    if not codes:
        return
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001
        pass
    try:
        from extractors.easyocr_extractor import _codes_for, _reader
        from schemas.document_schema import Language

        by_code = {l.value: l for l in Language}
        for code in codes:
            lang = by_code.get(code)
            if lang is None:
                continue
            _reader(_codes_for(lang))
            log(logger, logging.INFO, "warmup_reader_ready", lang=code)
    except Exception as exc:  # noqa: BLE001
        log(logger, logging.WARNING, "warmup_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks: list[asyncio.Task] = []
    job_queue.start(tasks)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _warmup)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="Document Extraction Orchestrator", version="2.0", lifespan=lifespan)
app.include_router(health_api.router)
app.include_router(extract_api.router)
