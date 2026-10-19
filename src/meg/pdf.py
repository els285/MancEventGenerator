"""LHAPDF sets: find them, fetch them into the cache, look up their LHAPDF ID."""
from __future__ import annotations

import re
import shutil
import tempfile
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from .cache import cache_dir, offline
from .proc import capture
from .sysenv import lhapdf_dirs
from .util import MegError, log, safe_extract

MIRRORS = [
    "https://lhapdfsets.web.cern.ch/current",
    "http://lhapdfsets.web.cern.ch/lhapdfsets/current",
    "https://lhapdfsets.web.cern.ch/lhapdfsets/current",
]
# What Herwig 7.3 needs for its own defaults (hadronisation/MPI tunes), besides the events' PDF.
HERWIG_DEFAULT_SETS = ["CT14lo", "CT14nlo"]
BUILTIN_LO_HERWIG_PDF = "NNPDF23_lo_as_0130_qed"   # LHAPDF counterpart of MG5's built-in nn23lo1


def find_set(name: str, env: Mapping[str, str]) -> Path | None:
    for d in lhapdf_dirs(env):
        if (d / name).is_dir():
            return d / name
    return None


def lhaid(name: str, env: Mapping[str, str]) -> int:
    p = find_set(name, env)
    if p is None:
        raise MegError(f"PDF set {name} is not installed; run `meg pdf fetch {name}`")
    m = re.search(r"^SetIndex:\s*(\d+)", (p / f"{name}.info").read_text(), re.MULTILINE)
    if not m:
        raise MegError(f"cannot read SetIndex from {p / (name + '.info')}")
    return int(m.group(1))


def ensure(name: str, env: Mapping[str, str]) -> Path:
    found = find_set(name, env)
    if found:
        return found
    if offline():
        raise MegError(f"PDF set {name} is not in the cache and MEG_OFFLINE=1")
    dest = cache_dir("lhapdf")
    log.info("fetching PDF set %s into %s", name, dest)
    out = capture(["lhapdf", f"--pdfdir={dest}", "install", name], env, timeout=900)
    if (dest / name).is_dir():
        return dest / name
    log.warning("`lhapdf install` failed (%s); trying direct downloads", out.splitlines()[-1:] or "")
    bases = (env.get("LHAPDF_MIRRORS") or "").split() or MIRRORS
    errors = []
    for base in bases:
        url = f"{base}/{name}.tar.gz"
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "set.tar.gz"
            try:
                with urllib.request.urlopen(url, timeout=300) as r, open(arc, "wb") as f:
                    shutil.copyfileobj(r, f)
                safe_extract(arc, dest)
            except Exception as e:  # noqa: BLE001 - try the next mirror
                errors.append(f"{url}: {e}")
                continue
        if (dest / name).is_dir():
            return dest / name
        errors.append(f"{url}: unpacked, but {dest / name} does not exist")
    raise MegError(f"could not fetch PDF set {name}:\n  " + "\n  ".join(errors) +
                   f"\nManual fallback: download {name}.tar.gz from "
                   f"https://lhapdfsets.web.cern.ch/current/ and extract it into {dest}")
