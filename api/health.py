"""Health + metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from core.config import settings
from services import job_queue
from services.metrics_service import metrics

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "document-extractor",
        "version": "2.0",
        "engines": ["pymupdf", "easyocr", "tesseract", "docling", "opendataloader"],
        "modes": ["auto", "fast", "legal", "rag"],
        "default_mode": settings.default_mode,
        "workers": settings.workers,
        "queue_depth": job_queue.queue_depth(),
        "jobs_tracked": job_queue.jobs_tracked(),
    }


@router.get("/metrics")
def get_metrics() -> dict:
    return metrics.snapshot()
