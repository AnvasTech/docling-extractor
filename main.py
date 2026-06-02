"""
Docling extraction microservice (shared infra).

Generic OCR / document-to-text service. Converts a PDF or image (incl. scanned
and multilingual) to structured Markdown + page count. No app-specific logic —
any app (land-title verification, trading research, ...) POSTs a file and gets
text back, then runs its own LLM analysis downstream.

Two ways to call it:
  - POST /extract        synchronous: enqueue + wait for the result.
  - POST /jobs           async: enqueue, returns a job_id immediately.
    GET  /jobs/{job_id}  poll status / fetch the result.

Extraction is serialised through an in-process queue with a bounded number of
workers (DOCLING_WORKERS, default 1) so concurrent callers don't thrash a
CPU-only box — requests queue instead of competing.
"""

import asyncio
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Header, HTTPException, UploadFile

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TesseractCliOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

# --- config ----------------------------------------------------------------
# OCR languages — comma-separated. KEEP THIS SHORT: Tesseract re-OCRs every page
# against every language, so more langs = much slower (painful on a CPU box).
# Default English only; set e.g. DOCLING_OCR_LANGS="eng,tam" per deployment.
OCR_LANGS = [
    s.strip()
    for s in os.environ.get("DOCLING_OCR_LANGS", "eng").split(",")
    if s.strip()
]
SERVICE_TOKEN = os.environ.get("DOCLING_SERVICE_TOKEN", "")
MAX_BYTES = int(os.environ.get("DOCLING_MAX_BYTES", str(40 * 1024 * 1024)))
NUM_WORKERS = int(os.environ.get("DOCLING_WORKERS", "1"))
QUEUE_MAX = int(os.environ.get("DOCLING_QUEUE_MAX", "32"))
JOB_TTL = int(os.environ.get("DOCLING_JOB_TTL", "600"))  # keep finished jobs (s)
EXTRACT_TIMEOUT = int(os.environ.get("DOCLING_EXTRACT_TIMEOUT", "300"))  # /extract wait (s)


def _build_converter() -> DocumentConverter:
    ocr_options = TesseractCliOcrOptions(lang=OCR_LANGS)
    pipeline = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=ocr_options,
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)}
    )


CONVERTER = _build_converter()

# --- in-process job queue --------------------------------------------------
# Each job: { status, data, suffix, filename, result, event, created_at, ... }
# The data bytes are dropped once processed to free memory.
_jobs: dict[str, dict] = {}
_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX)


def _convert_blocking(data: bytes, suffix: str) -> dict:
    """Runs in a thread (Docling is blocking/CPU-bound)."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            result = CONVERTER.convert(tmp.name)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "markdown": "", "pages": 0, "chars": 0}
    doc = result.document
    markdown = doc.export_to_markdown()
    try:
        pages = len(doc.pages)
    except Exception:  # noqa: BLE001
        pages = 0
    return {"ok": True, "pages": pages, "chars": len(markdown), "markdown": markdown}


async def _worker() -> None:
    loop = asyncio.get_running_loop()
    while True:
        job_id = await _queue.get()
        rec = _jobs.get(job_id)
        if rec is None:
            _queue.task_done()
            continue
        rec["status"] = "processing"
        rec["started_at"] = time.time()
        name = rec.get("filename")
        print(f"[extract] start {name} (langs={OCR_LANGS})", flush=True)
        try:
            rec["result"] = await loop.run_in_executor(
                None, _convert_blocking, rec["data"], rec["suffix"]
            )
            rec["status"] = "done" if rec["result"].get("ok") else "error"
        except Exception as exc:  # noqa: BLE001
            rec["result"] = {"ok": False, "error": str(exc), "markdown": "", "pages": 0, "chars": 0}
            rec["status"] = "error"
        finally:
            dt = time.time() - rec["started_at"]
            r = rec.get("result") or {}
            print(
                f"[extract] done  {name} ok={r.get('ok')} pages={r.get('pages')} "
                f"chars={r.get('chars')} in {dt:.1f}s",
                flush=True,
            )
            rec["finished_at"] = time.time()
            rec.pop("data", None)
            rec["event"].set()
            _queue.task_done()


async def _reaper() -> None:
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale = [k for k, v in _jobs.items() if v.get("finished_at") and now - v["finished_at"] > JOB_TTL]
        for k in stale:
            _jobs.pop(k, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(_worker()) for _ in range(max(1, NUM_WORKERS))]
    tasks.append(asyncio.create_task(_reaper()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Docling Extractor", version="1.0", lifespan=lifespan)


def _check_auth(authorization: str | None) -> None:
    if not SERVICE_TOKEN:
        return
    if authorization != f"Bearer {SERVICE_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _enqueue(data: bytes, filename: str | None) -> str:
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    job_id = uuid.uuid4().hex
    suffix = os.path.splitext(filename or "")[1] or ".pdf"
    _jobs[job_id] = {
        "status": "queued",
        "data": data,
        "suffix": suffix,
        "filename": filename,
        "result": None,
        "event": asyncio.Event(),
        "created_at": time.time(),
    }
    try:
        _queue.put_nowait(job_id)
    except asyncio.QueueFull:
        _jobs.pop(job_id, None)
        raise HTTPException(status_code=503, detail="Extraction queue full, retry shortly")
    return job_id


def _public(rec: dict) -> dict:
    return {
        "status": rec["status"],
        "filename": rec.get("filename"),
        "queued_at": rec.get("created_at"),
        "result": rec.get("result"),
    }


# --- endpoints -------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "docling-extractor",
        "ocr_langs": OCR_LANGS,
        "workers": NUM_WORKERS,
        "queue_depth": _queue.qsize(),
        "queue_max": QUEUE_MAX,
        "jobs_tracked": len(_jobs),
    }


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict:
    """Synchronous: enqueue and wait for the result (bounded by EXTRACT_TIMEOUT)."""
    _check_auth(authorization)
    data = await file.read()
    job_id = _enqueue(data, file.filename)
    rec = _jobs[job_id]
    try:
        await asyncio.wait_for(rec["event"].wait(), timeout=EXTRACT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Extraction timed out; try /jobs (async)")
    return rec["result"]


@app.post("/jobs")
async def submit_job(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict:
    """Async: enqueue and return a job_id immediately. Poll GET /jobs/{id}."""
    _check_auth(authorization)
    data = await file.read()
    job_id = _enqueue(data, file.filename)
    return {"job_id": job_id, "status": "queued", "queue_depth": _queue.qsize()}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)) -> dict:
    _check_auth(authorization)
    rec = _jobs.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return {"job_id": job_id, **_public(rec)}
