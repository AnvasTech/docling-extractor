# docling-extractor

Stateless **Intelligent PDF Extraction & OCR Orchestrator** for the Indian
Property Title Verification platform. It analyses each document, picks the
cheapest engine that can hit acceptable quality, escalates only when needed, and
returns one normalized JSON — the caller never knows which engine ran.

Engines: **PyMuPDF** (text layer) · **RapidOCR** (scanned) · **Docling**
(complex layout/tables) · **OpenDataLoader-PDF** (RAG, optional).

> **Stateless by design.** No DB, no cache, no persisted documents/text/metadata,
> no shared filesystem. Temp files are deleted after every request. Supabase
> (the web app) is the source of truth and the only cache. Run N replicas with
> zero coordination. See [MIGRATION.md](./MIGRATION.md) for architecture.

## API

Auth: if `DOCLING_SERVICE_TOKEN` is set, send `Authorization: Bearer <token>`.

### Stateless flow (recommended)
```
POST /extract     {"file_url": "<signed supabase url>", "mode": "auto|fast|legal|rag",
                   "document_id": "...", "document_type": "..."}
                  → unified ExtractionResult JSON
```
Server downloads the signed URL, extracts, returns JSON, deletes the temp file.
`/extract` also accepts a multipart `file` (legacy direct upload).

### Async queue (backward-compatible — used by the Title app today)
```
POST /jobs        multipart file=@doc.pdf  engine=auto|pymupdf|ocr|docling
                  → {job_id, status}
GET  /jobs/{id}   → {status, result}   # result has ok/markdown/method/pages/chars + unified fields
GET  /health      → engines, modes, queue
GET  /metrics     → request counts, avg latency, by-method
```

## Modes
| Mode | Pipeline | Use |
|------|----------|-----|
| `auto` | class-driven | default; digital→PyMuPDF, scanned→RapidOCR, tables/layout→Docling |
| `fast` | PyMuPDF → RapidOCR | bulk ingestion / indexing |
| `legal` | PyMuPDF → RapidOCR → Docling | title verification (reading order + tables matter) |
| `rag` | OpenDataLoader-PDF → Docling | RAG-ready markdown + chunks (only on request) |

Escalation is confidence-gated: an engine's output is scored (text/OCR/layout
confidence); below threshold the orchestrator escalates to the next engine.

## Unified output (excerpt)
```json
{
  "document_id": "", "file_name": "", "document_type": "", "page_count": 0,
  "primary_language": "en", "secondary_languages": [], "mixed_language": false,
  "page_languages": {}, "ocr_required": false,
  "extraction_method": "pymupdf", "extraction_chain": ["pymupdf"],
  "confidence_score": 0.0, "ocr_confidence": 0.0, "layout_confidence": 0.0,
  "language_confidence": 0.0, "processing_time_ms": 0,
  "text": "", "pages": [], "tables": [], "metadata": {},
  "ok": true, "markdown": "", "method": "pymupdf", "chars": 0
}
```
`ok`/`markdown`/`method`/`chars` are backward-compat mirrors for the existing app.

## Layout
```
api/  orchestrator/  analyzers/  extractors/  schemas/  services/  integrations/  core/  tests/
```
See [MIGRATION.md](./MIGRATION.md) for the module map, flow, and migration plan.

## Config (env)
`DOCLING_SERVICE_TOKEN`, `DOCLING_DEFAULT_MODE` (auto), `DOCLING_WORKERS` (1),
`DOCLING_OCR_DPI` (200), `DOCLING_EXTRACT_THRESHOLD` (0.90),
`DOCLING_LAYOUT_THRESHOLD` (0.60), `DOCLING_MAX_BYTES` (200 MB),
`DOCLING_JOB_TTL` (1800), `LOG_LEVEL` (INFO).

## Run / deploy
```bash
docker compose up -d --build      # behind nginx + TLS
curl -s localhost:8000/health
python3 -m pytest -q tests        # pure-logic tests (no engines needed)
```
Heavy image (PyTorch for Docling + ONNX OCR + models, ≥4 GB RAM). Engines
lazy-load, so only the one in use occupies memory. RAG deps are optional
(`requirements-rag.txt`, best-effort in the Dockerfile).
