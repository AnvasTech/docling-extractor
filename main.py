"""
Document extraction microservice (shared infra).

Tiered extraction, cheapest-first:
  1. PyMuPDF  — primary. Pulls the embedded text layer of digital PDFs. Instant.
  2. RapidOCR — fallback OCR for scanned pages. Runs the PP-OCR (PaddleOCR)
                models via ONNX Runtime: same model quality, no paddlepaddle
                (which segfaults on constrained CPU boxes), lighter, reliable.
  3. Docling  — complex layouts (tables, multi-column) when explicitly asked.
Downstream, the calling app runs the AI analysis (Claude / GPT) on the text.

Engine per request via the `engine` field:
  auto (default) → PyMuPDF; if the text layer is thin (scanned), OCR.
  pymupdf        → text layer only.
  ocr | paddle   → force OCR (RapidOCR / PP-OCR models).
  docling        → force Docling (complex layouts).

Sync POST /extract (waits) and async POST /jobs + GET /jobs/{id} both feed one
in-process queue so concurrent callers don't thrash a CPU box.
"""

import asyncio
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

# --- config ----------------------------------------------------------------
SERVICE_TOKEN = os.environ.get("DOCLING_SERVICE_TOKEN", "")
MAX_BYTES = int(os.environ.get("DOCLING_MAX_BYTES", str(40 * 1024 * 1024)))
NUM_WORKERS = int(os.environ.get("DOCLING_WORKERS", "1"))
QUEUE_MAX = int(os.environ.get("DOCLING_QUEUE_MAX", "32"))
JOB_TTL = int(os.environ.get("DOCLING_JOB_TTL", "1800"))
EXTRACT_TIMEOUT = int(os.environ.get("DOCLING_EXTRACT_TIMEOUT", "600"))
DEFAULT_ENGINE = os.environ.get("DOCLING_DEFAULT_ENGINE", "auto")
OCR_DPI = int(os.environ.get("DOCLING_OCR_DPI", "200"))
# Min chars (per page) for PyMuPDF text to count as a real text layer.
TEXT_MIN_PER_PAGE = int(os.environ.get("DOCLING_TEXT_MIN_PER_PAGE", "50"))

# --- lazy engine singletons (load only what's used; saves RAM) --------------
_ocr = None
_docling = None


def get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr = RapidOCR()
    return _ocr


def get_docling():
    global _docling
    if _docling is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TesseractCliOcrOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=True,
            ocr_options=TesseractCliOcrOptions(lang=["eng"]),
        )
        _docling = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)}
        )
    return _docling


# --- extractors ------------------------------------------------------------
def _pymupdf_text(path: str) -> tuple[str, int]:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        pages = doc.page_count or 1
        parts = [doc.load_page(i).get_text() for i in range(doc.page_count)]
        return "\n\n".join(parts).strip(), pages
    finally:
        doc.close()


def _ocr_image(path: str) -> str:
    engine = get_ocr()
    result, _elapse = engine(path)
    if not result:
        return ""
    # result rows: [box, text, score]
    return "\n".join(row[1] for row in result if len(row) >= 2 and row[1])


def _ocr_pdf(path: str) -> tuple[str, int]:
    import fitz

    doc = fitz.open(path)
    out: list[str] = []
    try:
        pages = doc.page_count or 1
        for i in range(doc.page_count):
            pix = doc.load_page(i).get_pixmap(dpi=OCR_DPI)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as img:
                pix.save(img.name)
                out.append(_ocr_image(img.name))
        return "\n\n".join(p for p in out if p).strip(), pages
    finally:
        doc.close()


def _docling_convert(path: str) -> tuple[str, int]:
    result = get_docling().convert(path)
    doc = result.document
    try:
        pages = len(doc.pages)
    except Exception:  # noqa: BLE001
        pages = 0
    return doc.export_to_markdown(), pages


def _extract(data: bytes, suffix: str, engine: str) -> dict:
    """Runs in a thread (CPU-bound)."""
    suffix = suffix.lower() or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        path = tmp.name
        try:
            is_pdf = suffix == ".pdf"
            if engine == "docling":
                text, pages = _docling_convert(path)
                method = "docling"
            elif is_pdf and engine in ("auto", "pymupdf"):
                text, pages = _pymupdf_text(path)
                method = "pymupdf"
                thin = len(text) < max(200, pages * TEXT_MIN_PER_PAGE)
                if thin and engine == "auto":
                    text, pages = _ocr_pdf(path)  # scanned → OCR
                    method = "ocr"
            elif is_pdf and engine == "ocr":
                text, pages = _ocr_pdf(path)
                method = "ocr"
            else:  # image input
                text = _docling_convert(path)[0] if engine == "docling" else _ocr_image(path)
                pages = 1
                method = "docling" if engine == "docling" else "ocr"
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "markdown": "", "pages": 0, "chars": 0}

    text = (text or "").strip()
    return {"ok": True, "pages": pages, "chars": len(text), "markdown": text, "method": method}


# --- in-process job queue --------------------------------------------------
_jobs: dict[str, dict] = {}
_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX)


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
        print(f"[extract] start {name} engine={rec['engine']}", flush=True)
        try:
            rec["result"] = await loop.run_in_executor(
                None, _extract, rec["data"], rec["suffix"], rec["engine"]
            )
            rec["status"] = "done" if rec["result"].get("ok") else "error"
        except Exception as exc:  # noqa: BLE001
            rec["result"] = {"ok": False, "error": str(exc), "markdown": "", "pages": 0, "chars": 0}
            rec["status"] = "error"
        finally:
            dt = time.time() - rec["started_at"]
            r = rec.get("result") or {}
            print(
                f"[extract] done  {name} ok={r.get('ok')} method={r.get('method')} "
                f"pages={r.get('pages')} chars={r.get('chars')} in {dt:.1f}s",
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


app = FastAPI(title="Document Extractor", version="2.0", lifespan=lifespan)


def _check_auth(authorization: str | None) -> None:
    if SERVICE_TOKEN and authorization != f"Bearer {SERVICE_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _norm_engine(engine: str | None) -> str:
    e = (engine or DEFAULT_ENGINE).lower()
    if e == "paddle":
        e = "ocr"  # accept the old keyword
    return e if e in ("auto", "pymupdf", "ocr", "docling") else "auto"


def _enqueue(data: bytes, filename: str | None, engine: str) -> str:
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    job_id = uuid.uuid4().hex
    suffix = os.path.splitext(filename or "")[1] or ".pdf"
    _jobs[job_id] = {
        "status": "queued",
        "data": data,
        "suffix": suffix,
        "engine": engine,
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


# --- endpoints -------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "document-extractor",
        "engines": ["pymupdf", "ocr", "docling"],
        "default_engine": DEFAULT_ENGINE,
        "workers": NUM_WORKERS,
        "queue_depth": _queue.qsize(),
        "queue_max": QUEUE_MAX,
        "jobs_tracked": len(_jobs),
    }


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    engine: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    _check_auth(authorization)
    data = await file.read()
    job_id = _enqueue(data, file.filename, _norm_engine(engine))
    rec = _jobs[job_id]
    try:
        await asyncio.wait_for(rec["event"].wait(), timeout=EXTRACT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Extraction timed out; use /jobs (async)")
    return rec["result"]


@app.post("/jobs")
async def submit_job(
    file: UploadFile = File(...),
    engine: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    _check_auth(authorization)
    data = await file.read()
    job_id = _enqueue(data, file.filename, _norm_engine(engine))
    return {"job_id": job_id, "status": "queued", "queue_depth": _queue.qsize()}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)) -> dict:
    _check_auth(authorization)
    rec = _jobs.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return {
        "job_id": job_id,
        "status": rec["status"],
        "filename": rec.get("filename"),
        "engine": rec.get("engine"),
        "result": rec.get("result"),
    }
