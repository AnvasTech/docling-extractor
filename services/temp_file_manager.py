"""Guaranteed-cleanup temp files. The server keeps nothing on disk."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def temp_path(suffix: str = ".pdf") -> Iterator[str]:
    """Yield a path to an empty temp file; delete it on exit no matter what."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@contextmanager
def materialize(data: bytes, suffix: str = ".pdf") -> Iterator[str]:
    """Write bytes to a temp file, yield its path, delete on exit."""
    with temp_path(suffix) as path:
        with open(path, "wb") as fh:
            fh.write(data)
        yield path
