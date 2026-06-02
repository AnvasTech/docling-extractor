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
from core.logging_setup import configure_logging
from services import job_queue

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks: list[asyncio.Task] = []
    job_queue.start(tasks)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="Document Extraction Orchestrator", version="2.0", lifespan=lifespan)
app.include_router(health_api.router)
app.include_router(extract_api.router)
