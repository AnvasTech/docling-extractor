"""In-process async job queue for the backward-compatible /jobs endpoints.

State is ephemeral and per-process (no persistence, no shared store) — each
worker/replica runs independently, which keeps the service horizontally
scalable. The web app is the source of truth.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from core.config import settings
from orchestrator.extraction_manager import extract as run_extract
from schemas.document_schema import ExtractionMode
from services.temp_file_manager import materialize

_jobs: dict[str, dict] = {}
_queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=settings.queue_max)


def queue_depth() -> int:
    return _queue.qsize()


def jobs_tracked() -> int:
    return len(_jobs)


def submit(data: bytes, filename: str | None, engine: str) -> str:
    if len(data) > settings.max_bytes:
        raise ValueError("File too large")
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {
        "status": "queued",
        "data": data,
        "filename": filename,
        "engine": engine,
        "result": None,
        "event": asyncio.Event(),
        "created_at": time.time(),
    }
    try:
        _queue.put_nowait(job_id)
    except asyncio.QueueFull:
        _jobs.pop(job_id, None)
        raise RuntimeError("Extraction queue full")
    return job_id


def get(job_id: str) -> dict | None:
    rec = _jobs.get(job_id)
    if rec is None:
        return None
    result = rec.get("result")
    return {
        "job_id": job_id,
        "status": rec["status"],
        "filename": rec.get("filename"),
        "engine": rec.get("engine"),
        "result": result.model_dump() if result is not None else None,
    }


async def _worker() -> None:
    loop = asyncio.get_running_loop()
    while True:
        job_id = await _queue.get()
        rec = _jobs.get(job_id)
        if rec is None:
            _queue.task_done()
            continue
        rec["status"] = "processing"
        try:
            data = rec["data"]
            engine = rec["engine"]

            def _do() -> object:
                with materialize(data) as path:
                    return run_extract(
                        path,
                        mode=ExtractionMode.AUTO,
                        file_name=rec.get("filename") or "",
                        force_engine=engine if engine != "auto" else None,
                    )

            rec["result"] = await loop.run_in_executor(None, _do)
            rec["status"] = "done" if rec["result"].ok else "error"
        except Exception:  # noqa: BLE001
            import traceback

            print(
                f"[job] FAILED {rec.get('filename')}: {traceback.format_exc()}",
                flush=True,
            )
            rec["status"] = "error"
        finally:
            rec["finished_at"] = time.time()
            rec.pop("data", None)
            rec["event"].set()
            _queue.task_done()


async def _reaper() -> None:
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale = [k for k, v in _jobs.items() if v.get("finished_at") and now - v["finished_at"] > settings.job_ttl_s]
        for k in stale:
            _jobs.pop(k, None)


def start(loop_tasks: list) -> None:
    for _ in range(max(1, settings.workers)):
        loop_tasks.append(asyncio.create_task(_worker()))
    loop_tasks.append(asyncio.create_task(_reaper()))


async def wait(job_id: str, timeout_s: int) -> dict:
    rec = _jobs[job_id]
    await asyncio.wait_for(rec["event"].wait(), timeout=timeout_s)
    return get(job_id)  # type: ignore[return-value]
