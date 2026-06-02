"""Extraction endpoints.

  POST /extract   — stateless flow: {file_url, mode} (signed Supabase URL) OR a
                    multipart file. Downloads, extracts, returns JSON, deletes.
  POST /jobs      — backward-compatible async queue (multipart file + engine).
  GET  /jobs/{id} — poll an async job.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel

from core.config import settings
from integrations import supabase_client
from orchestrator.extraction_manager import extract as run_extract
from schemas.document_schema import ExtractionMode
from schemas.extraction_result import ExtractionResult
from services import job_queue
from services.metrics_service import metrics
from services.temp_file_manager import materialize, temp_path

router = APIRouter()


def _auth(authorization: str | None) -> None:
    if settings.service_token and authorization != f"Bearer {settings.service_token}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _mode(value: str | None) -> ExtractionMode:
    try:
        return ExtractionMode((value or settings.default_mode).lower())
    except ValueError:
        return ExtractionMode.AUTO


async def _run_blocking(fn) -> ExtractionResult:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn)


class ExtractRequest(BaseModel):
    file_url: str
    mode: str | None = None
    document_id: str | None = None
    document_type: str | None = None


@router.post("/extract")
async def extract(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    _auth(authorization)
    content_type = request.headers.get("content-type", "")

    # --- JSON: signed-URL flow (the stateless, source-of-truth path) ---------
    if content_type.startswith("application/json"):
        body = ExtractRequest(**(await request.json()))
        mode = _mode(body.mode)
        file_name = supabase_client.filename_from_url(body.file_url)
        with temp_path(_suffix(file_name)) as path:
            await supabase_client.download(
                body.file_url,
                path,
                timeout_s=settings.download_timeout_s,
                max_bytes=settings.max_bytes,
            )
            result = await _run_blocking(
                lambda: run_extract(
                    path,
                    mode=mode,
                    file_name=file_name,
                    document_id=body.document_id or "",
                    document_type=body.document_type or "",
                )
            )
        metrics.record(result.method, result.processing_time_ms, result.ok)
        return result.model_dump()

    # --- multipart: legacy direct-upload flow --------------------------------
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=400, detail="Provide JSON {file_url, mode} or a multipart file")
    data = await upload.read()
    if len(data) > settings.max_bytes:
        raise HTTPException(status_code=413, detail="File too large")
    engine = form.get("engine")
    mode = _mode(form.get("mode"))
    with materialize(data, _suffix(upload.filename or "")) as path:
        result = await _run_blocking(
            lambda: run_extract(
                path,
                mode=mode,
                file_name=upload.filename or "",
                force_engine=engine if engine and engine != "auto" else None,
            )
        )
    metrics.record(result.method, result.processing_time_ms, result.ok)
    return result.model_dump()


@router.post("/jobs")
async def submit_job(
    file: UploadFile = File(...),
    engine: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    _auth(authorization)
    data = await file.read()
    try:
        job_id = job_queue.submit(data, file.filename, (engine or "auto").lower())
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"job_id": job_id, "status": "queued", "queue_depth": job_queue.queue_depth()}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)) -> dict:
    _auth(authorization)
    rec = job_queue.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return rec


def _suffix(name: str) -> str:
    import os

    return os.path.splitext(name)[1] or ".pdf"
