"""Fetch documents from Supabase Storage signed URLs.

A signed URL is a plain authenticated GET — no Supabase SDK or service key on
the extraction server. The server downloads, processes, and deletes; it never
writes back. Persistence is the web app's job.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = os.path.basename(unquote(path))
    return name or "document.pdf"


async def download(url: str, dest_path: str, *, timeout_s: int, max_bytes: int) -> int:
    """Stream a signed URL to `dest_path`. Returns bytes written. Enforces size cap."""
    import httpx

    written = 0
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_s) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=1 << 16):
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError("Downloaded file exceeds max size")
                    fh.write(chunk)
    return written
