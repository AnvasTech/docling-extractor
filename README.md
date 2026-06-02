# docling-extractor

Shared OCR / document-to-text microservice. A FastAPI wrapper around
[Docling](https://github.com/DS4SD/docling) that converts PDFs and images
(including scanned and multilingual — Indian regional scripts) into structured
Markdown + page count.

**Generic, no app logic.** Any app POSTs a file and gets text back, then runs
its own LLM analysis downstream:
- land-title verification → legal title prompt
- trading research → company / components / info prompt

## API

Auth: if `DOCLING_SERVICE_TOKEN` is set, send `Authorization: Bearer <token>`.

| Method | Path            | Body                      | Returns |
|--------|-----------------|---------------------------|---------|
| GET    | `/health`       | —                         | service + queue stats |
| POST   | `/extract`      | multipart `file=@doc.pdf` | waits, returns `{ ok, pages, chars, markdown }` |
| POST   | `/jobs`         | multipart `file=@doc.pdf` | `{ job_id, status }` immediately |
| GET    | `/jobs/{id}`    | —                         | `{ status, result }` (`queued`/`processing`/`done`/`error`) |

### Sync (simple, low volume)
```bash
curl -s -H "Authorization: Bearer $TOKEN" -F "file=@deed.pdf" \
  https://docling.example.com/extract | jq '{pages, chars}'
```

### Async + poll (concurrency / long docs)
```bash
JOB=$(curl -s -H "Authorization: Bearer $TOKEN" -F "file=@deed.pdf" \
  https://docling.example.com/jobs | jq -r .job_id)
curl -s -H "Authorization: Bearer $TOKEN" \
  https://docling.example.com/jobs/$JOB | jq .status   # poll until "done"
```

## Queue

Extraction is serialised through an in-process queue so concurrent callers from
multiple apps don't thrash a CPU box — requests **queue** instead of competing.
Both `/extract` and `/jobs` feed the same queue; `/extract` just waits on the
result. Tune via env:

| Env | Default | Meaning |
|-----|---------|---------|
| `DOCLING_WORKERS` | `1` | parallel conversions (raise only with more RAM) |
| `DOCLING_QUEUE_MAX` | `32` | max queued jobs (`503` when full) |
| `DOCLING_EXTRACT_TIMEOUT` | `300` | seconds `/extract` waits before `504` |
| `DOCLING_JOB_TTL` | `600` | seconds a finished job is retained for polling |
| `DOCLING_MAX_BYTES` | `41943040` | max upload size (40 MB) |
| `DOCLING_SERVICE_TOKEN` | — | bearer token; unset = no auth (local only) |

> The queue + job store are **in-process** — run a single uvicorn worker (the
> Dockerfile does). State is lost on restart; for durable cross-process queuing,
> swap in Redis/RQ. Single CPU worker is right for low/moderate volume.

## Run locally
```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000      # first call downloads Docling models
```

## Deploy (Docker, e.g. Hetzner)
```bash
export DOCLING_SERVICE_TOKEN="$(openssl rand -hex 32)"   # save it
docker compose up -d --build                              # models baked at build
curl -s localhost:8000/health
```
Put behind a TLS reverse proxy (Caddy auto-TLS):
```
docling.example.com {
    reverse_proxy 127.0.0.1:8000
    request_body { max_size 40MB }
}
```
Notes:
- CPU-only torch (Dockerfile) — avoids multi-GB CUDA libs.
- Give the container ≥ 4 GB RAM; CPU works (≈10–60 s/doc), GPU faster.
- Models are baked into the image (no runtime download).

## Callers
Each app sets:
```
DOCLING_SERVICE_URL=https://docling.example.com
DOCLING_SERVICE_TOKEN=<same token>
```
and POSTs to `/extract` (or `/jobs`).
