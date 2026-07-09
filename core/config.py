"""Runtime configuration, sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Auth
    service_token: str = field(default_factory=lambda: os.environ.get("DOCLING_SERVICE_TOKEN", ""))

    # Limits
    max_bytes: int = field(default_factory=lambda: _int("DOCLING_MAX_BYTES", 200 * 1024 * 1024))
    download_timeout_s: int = field(default_factory=lambda: _int("DOCLING_DOWNLOAD_TIMEOUT", 120))

    # Async queue (backward-compatible /jobs path)
    workers: int = field(default_factory=lambda: _int("DOCLING_WORKERS", 1))
    queue_max: int = field(default_factory=lambda: _int("DOCLING_QUEUE_MAX", 32))
    job_ttl_s: int = field(default_factory=lambda: _int("DOCLING_JOB_TTL", 1800))
    extract_timeout_s: int = field(default_factory=lambda: _int("DOCLING_EXTRACT_TIMEOUT", 600))

    # Routing / engines
    default_mode: str = field(default_factory=lambda: os.environ.get("DOCLING_DEFAULT_MODE", "auto"))
    # 300 DPI: Indic vowel marks (matras, kombu) blur at 200 and OCR accuracy drops.
    ocr_dpi: int = field(default_factory=lambda: _int("DOCLING_OCR_DPI", 300))
    lang_sample_dpi: int = field(default_factory=lambda: _int("DOCLING_LANG_SAMPLE_DPI", 120))

    # VLM lane (Claude vision) — used for handwriting and as the escalation
    # target when local OCR confidence is low. Disabled unless an Anthropic
    # API key is present (ANTHROPIC_API_KEY).
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    vlm_model: str = field(default_factory=lambda: os.environ.get("DOCLING_VLM_MODEL", "claude-sonnet-5"))
    vlm_escalation_model: str = field(
        default_factory=lambda: os.environ.get("DOCLING_VLM_ESCALATION_MODEL", "claude-opus-4-8")
    )
    # 200 DPI keeps an A4 page under Claude's 2576px high-res limit (no server
    # downscale) while staying sharp enough for handwriting.
    vlm_dpi: int = field(default_factory=lambda: _int("DOCLING_VLM_DPI", 200))
    vlm_page_workers: int = field(default_factory=lambda: _int("DOCLING_VLM_PAGE_WORKERS", 4))

    # Engine warm-up at startup: comma-separated EasyOCR language codes to
    # preload (e.g. "ta,en"). Empty string disables warm-up.
    warmup_langs: str = field(default_factory=lambda: os.environ.get("DOCLING_WARMUP_LANGS", "en"))

    # Confidence thresholds (0..1) — escalate to the next engine below these.
    text_min_per_page: int = field(default_factory=lambda: _int("DOCLING_TEXT_MIN_PER_PAGE", 50))
    extraction_threshold: float = field(default_factory=lambda: _float("DOCLING_EXTRACT_THRESHOLD", 0.90))
    layout_threshold: float = field(default_factory=lambda: _float("DOCLING_LAYOUT_THRESHOLD", 0.60))

    # Classification: scanned pages whose sample-OCR word confidence falls
    # below this are treated as handwritten.
    handwriting_conf_threshold: float = field(default_factory=lambda: _float("DOCLING_HANDWRITING_CONF", 0.40))

    # EasyOCR runtime
    easyocr_gpu: bool = field(default_factory=lambda: os.environ.get("DOCLING_EASYOCR_GPU", "0") == "1")
    ocr_page_workers: int = field(default_factory=lambda: _int("DOCLING_OCR_PAGE_WORKERS", 4))

    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))


settings = Settings()
