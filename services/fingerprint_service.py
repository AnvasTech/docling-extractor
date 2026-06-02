"""SHA-256 fingerprinting. Caching itself lives in Supabase (web app), not here."""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
