"""Small shared helpers."""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import shutil
import tarfile
from pathlib import Path
from typing import Any

log = logging.getLogger("meg")


class MegError(RuntimeError):
    """A problem the user can act on. The CLI prints the message without a traceback."""


class StageError(MegError):
    """A pipeline stage failed. `diag` is filled in with the path of the diagnostics file."""

    def __init__(self, message: str, diag: Path | None = None):
        super().__init__(message)
        self.diag = diag


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def gunzip(src: Path, dest: Path) -> Path:
    with gzip.open(src, "rb") as fi, open(dest, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    return dest


def safe_extract(archive: Path, dest: Path) -> None:
    """Extract a tar archive, refusing absolute paths, '..' and links."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            if m.issym() or m.islnk() or m.name.startswith("/") or ".." in Path(m.name).parts:
                raise MegError(f"unsafe member in archive: {m.name}")
        if hasattr(tarfile, "data_filter"):
            t.extractall(dest, filter="data")
        else:
            t.extractall(dest)
