"""Pack, unpack and relocate an MG5 process directory so that it can be built once and used elsewhere.

An MG5 process directory is not relocatable as it stands: it has symlinks that are relative to where it
was built (for example lib/libLHAPDF.a pointing up into the conda environment) and text files that can
embed the build path. `pack` makes the links absolute where they leave the tree; `unpack` extracts and
rewrites any embedded build path to the new location."""
from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

from .util import MegError, log

MAX_TEXT = 2 << 20


def make_relocatable(proc_dir: Path) -> int:
    """Turn relative symlinks that leave `proc_dir` into absolute ones. Returns how many were changed."""
    root = os.path.realpath(proc_dir)
    changed = 0
    for dirpath, dirnames, filenames in os.walk(proc_dir, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            if not os.path.islink(p):
                continue
            target = os.readlink(p)
            if os.path.isabs(target):
                continue
            resolved = os.path.normpath(os.path.join(os.path.realpath(dirpath), target))
            if resolved != root and not resolved.startswith(root + os.sep):
                os.unlink(p)
                os.symlink(resolved, p)
                changed += 1
    return changed


def relocate(proc_dir: Path, old: str, new: str) -> int:
    """Replace the path `old` by `new` in every text file under `proc_dir`. Returns files changed."""
    if old == new:
        return 0
    o, n = old.encode(), new.encode()
    changed = 0
    for dirpath, _, filenames in os.walk(proc_dir, followlinks=False):
        for name in filenames:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                continue
            try:
                if os.path.getsize(p) > MAX_TEXT:
                    continue
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if o not in data or b"\0" in data[:8192]:
                continue
            with open(p, "wb") as f:
                f.write(data.replace(o, n))
            changed += 1
    return changed


def pack(proc_dir: Path, archive: Path, meta: dict) -> None:
    """Write `archive` holding the process directory and a process.json describing where it was built."""
    proc_dir = Path(proc_dir).resolve()
    n = make_relocatable(proc_dir)
    log.info("process directory packed (%d links made absolute)", n)
    info = {**meta, "build_dir": str(proc_dir), "dir_name": proc_dir.name}
    side = proc_dir.parent / "process.json"
    side.write_text(json.dumps(info, indent=2) + "\n")
    with tarfile.open(archive, "w:gz", compresslevel=6) as t:
        t.add(side, arcname="process.json", recursive=False)
        t.add(proc_dir, arcname=proc_dir.name)


def unpack(archive: Path, dest: Path) -> Path:
    """Extract into `dest` and return the process directory, with embedded build paths rewritten."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                raise MegError(f"unsafe member in process archive: {m.name}")
        if hasattr(tarfile, "fully_trusted_filter"):
            t.extractall(dest, filter="fully_trusted")        # our own archive: links are meant to be kept
        else:
            t.extractall(dest)
    info = json.loads((dest / "process.json").read_text())
    proc_dir = dest / info["dir_name"]
    if not (proc_dir / "Cards").is_dir():
        raise MegError(f"{archive} does not contain a process directory (no {info['dir_name']}/Cards)")
    n = relocate(proc_dir, info["build_dir"], str(proc_dir.resolve()))
    log.info("prebuilt process unpacked (%d files re-pointed from %s)", n, info["build_dir"])
    return proc_dir
