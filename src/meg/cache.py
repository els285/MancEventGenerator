"""Where MEG keeps mutable, content-keyed data (UFO models, PDF sets).

Nothing here lives inside the conda environment, so the environment stays immutable and
reproducible. Override the location with MEG_CACHE.
"""
from __future__ import annotations

import os
from pathlib import Path


def cache_root() -> Path:
    env = os.environ.get("MEG_CACHE")
    if env:
        root = Path(env).expanduser()
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "meg"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir(name: str) -> Path:
    d = cache_root() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def offline() -> bool:
    """MEG_OFFLINE=1 forbids all network access (cluster nodes without internet)."""
    return os.environ.get("MEG_OFFLINE") == "1"
