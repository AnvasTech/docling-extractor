# docling-extractor

Shared document-to-text microservice. Tiered extraction, cheapest-first:

1. **PyMuPDF** — primary. Pulls the embedded text layer of digital PDFs. Instant.
2. **RapidOCR** — fallback OCR for scanned pages. Runs the PP-OCR (PaddleOCR)
   models via ONNX Runtime — same model quality, no fragile `paddlepaddle`.
3. **Docling** — complex layouts (tables, multi-column) when explicitly asked.

Downstream, the calling app runs the AI analysis (Claude / GPT) on the text.

**Generic, no app logic.** Any app POSTs a file and gets text back:
- land-title verification → legal title prompt
- trading research → company / components / info prompt

## API

Auth: if `DOCLING_SERVICE_TOKEN` is set, send `Authorization: Bearer <token>`.

| Method | Path         | Body                                   | Returns |
|--------|--------------|----------------------------------------|---------|
| GET    | `/health`    | —                                      | engines + queue stats |
| POST   | `/extract`   | multipart `file=@doc.pdf` `engine=`    | waits → `{ ok, method, pages, chars, markdown }` |
| POST   | `/jobs`      | multipart `file=@doc.pdf` `engine=`    | `{ job_id, status }` immediately |
| GET    | `/jobs/{id}` | —                                      | `{ status, result }` |

**`engine`** (optional form field): `auto` (default — PyMuPDF, then RapidOCR if
the text layer is thin), `pymupdf` (text layer only), `ocr` (force OCR;
`paddle` accepted as an alias), `docling` (complex layouts). The result's
`method` reports which actually ran.

```bash
# auto: instant for digital PDFs, OCR fallback for scans
curl -s -H "Authorization: Bearer $TOKEN" -F "file=@ec.pdf" \
  https://docling.example.com/extract | jq '{method, pages, chars}'

# async + poll for big scans
JOB=$(curl -s -H "Authorization: Bearer $TOKEN" -F "file=@deed.pdf" -F "engine=paddle" \
  https://docling.example.com/jobs | jq -r .job_id)
curl -s -H "Authorization: Bearer $TOKEN" https://docling.example.com/jobs/$JOB | jq .status
```

## Queue

Both `/extract` and `/jobs` feed one in-process queue so concurrent callers
don't thrash a CPU box. `/extract` waits on the result; `/jobs` returns an id to
poll. Env:

| Env | Default | Meaning |
|-----|---------|---------|
| `DOCLING_DEFAULT_ENGINE` | `auto` | engine when the request omits one |
| `DOCLING_OCR_DPI` | `200` | page render DPI for OCR (higher = better + slower) |
| `DOCLING_WORKERS` | `1` | parallel conversions (raise only with more RAM) |
| `DOCLING_QUEUE_MAX` | `32` | max queued jobs (`503` when full) |
| `DOCLING_EXTRACT_TIMEOUT` | `600` | seconds `/extract` waits before `504` |
| `DOCLING_JOB_TTL` | `1800` | seconds a finished job is retained for polling |
| `DOCLING_MAX_BYTES` | `41943040` | max upload size (40 MB) |
| `DOCLING_SERVICE_TOKEN` | — | bearer token; unset = no auth (local only) |

> Queue + job store are **in-process** — single uvicorn worker. State is lost on
> restart; for durable cross-process queuing, swap in Redis/RQ.

## Speed

- **Digital PDFs** (most registrar-portal ECs/deeds have a text layer) → PyMuPDF,
  seconds regardless of page count.
- **Scanned PDFs/images** → RapidOCR per page (~1-3 s/page on CPU).
- **Complex tables/layout** → `engine=docling` (slowest, best structure).

## Deploy (Docker, e.g. Hetzner)
```bash
export DOCLING_SERVICE_TOKEN="$(openssl rand -hex 32)"   # save it
docker compose up -d --build                              # models baked at build
curl -s localhost:8000/health
```
Behind a TLS reverse proxy (nginx/Caddy), raise `client_max_body_size` to 40 MB.

> **Image is heavy** — PyTorch (Docling) + ONNX OCR + models. Give the box
> ≥ 4 GB RAM and a few GB free disk. Engines lazy-load, so only the one in use
> occupies memory at runtime.

## Callers
```
DOCLING_SERVICE_URL=https://docling.example.com
DOCLING_SERVICE_TOKEN=<same token>
```
POST to `/extract` (small/sync) or `/jobs` (big/async), optionally with `engine`.
