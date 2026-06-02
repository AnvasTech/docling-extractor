# Migration & Architecture

## What changed

The service evolved from a single-engine (Docling/RapidOCR) extractor into a
**stateless extraction orchestrator** that picks the cheapest engine capable of
acceptable quality, then escalates only when needed.

```
api/            HTTP layer (extract, jobs, health, metrics)
orchestrator/   routing_engine → strategy_selector → extraction_manager (cascade + escalation)
analyzers/      pdf_classifier, language_detector, layout_detector, quality_analyzer
extractors/     pymupdf, rapidocr, docling, opendataloader  (Extractor ABC)
schemas/        document_schema (analysis), extraction_result (unified output)
services/       temp_file_manager, fingerprint_service, metrics_service, job_queue
integrations/   supabase_client (signed-URL download)
core/           config, logging_setup
```

### Flow
```
file_url (signed Supabase URL) → download to temp → analyze (class + language +
OCR need) → routing plan → cascade extract with confidence escalation →
normalize to unified JSON → return → delete temp
```

## Statelessness
- No DB, no cache, no shared FS, no persisted documents/text/metadata.
- Temp files via `services/temp_file_manager` are always deleted (context managers).
- The only in-memory state is the ephemeral async job queue (per-process, lost on
  restart) — it is processing state, not storage, and is independent per replica,
  so the service scales horizontally with zero coordination.
- Source of truth + caching live in Supabase (web app). Caching pattern: web app
  hashes the file (or calls `fingerprint_service`), checks Supabase, and only
  calls `/extract` on a miss.

## Backward compatibility
The Title Verification app is unchanged:
- `POST /jobs` (multipart `file` + `engine`) → `{job_id}`  — still works.
- `GET /jobs/{id}` → `{status, result}` where `result` carries the legacy
  `ok` / `markdown` / `method` / `pages` / `chars` fields (mirrored by
  `ExtractionResult.finalize()`), plus the new unified fields.
- `engine` values `pymupdf|ocr|paddle|docling` map to forced single-engine runs.

## New API
```
POST /extract
  { "file_url": "<signed supabase url>", "mode": "auto|fast|legal|rag",
    "document_id": "...", "document_type": "..." }
  → unified ExtractionResult JSON
```
`/extract` also accepts a multipart `file` (legacy direct upload).

## Modes
- **auto** — class-driven (digital→PyMuPDF, scanned→RapidOCR, table/layout→Docling).
- **fast** — PyMuPDF → RapidOCR. Bulk ingestion.
- **legal** — PyMuPDF → RapidOCR → Docling. Title verification (default for TITAN).
- **rag** — OpenDataLoader-PDF (→ Docling fallback). Only when RAG output requested.

## Migration plan (zero downtime)
1. Build + deploy the new image alongside (same `/jobs` contract) — TITAN keeps working.
2. Switch TITAN's heavy/large-doc path to `POST /extract` with `file_url` + `mode=legal`
   (signed URL from Supabase) when ready; until then `/jobs` is unchanged.
3. Enable `mode=rag` once OpenDataLoader-PDF is validated on the box
   (`pip install -r requirements-rag.txt`).
4. Add future languages by extending `Language` + `_SCRIPT_RANGES` and Paddle/RapidOCR
   language packs — no routing changes needed.

## Deployment
```bash
docker compose up -d --build      # behind nginx + TLS (already configured)
curl -s localhost:8000/health     # engines + modes + queue
```
Horizontal scale: run N replicas behind the proxy; each is independent (no shared
state). For Kubernetes, the same image runs as a Deployment with a Service +
HPA on CPU.

## Future consumers
The unified schema (text, pages, tables, languages, confidences, metadata) feeds
the Title Verification engine, ownership-chain builder, knowledge-graph engine,
risk detection, embedding pipeline, and document search/chat without any of them
knowing which extractor produced the result.
