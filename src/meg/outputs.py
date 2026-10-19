"""Keep the event files the user asked for (LHE, HepMC) in <run>/output/.

The big intermediates stay where the stages wrote them (that is what makes resuming possible);
this step puts a named copy next to the final results. Uncompressed copies are hard links, so
they cost no extra disk."""
from __future__ import annotations

import gzip
import os
import shutil
from pathlib import Path

from .context import RunContext


def _keep(src: Path, dest: Path, compress: bool) -> Path:
    if compress:
        dest = dest.with_name(dest.name + ".gz")
        with open(src, "rb") as fi, gzip.open(dest, "wb", compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
    else:
        try:
            os.link(src, dest)
        except OSError:
            shutil.copy2(src, dest)
    return dest


def run(ctx: RunContext) -> dict[str, str | None]:
    cfg = ctx.plan.config
    out = ctx.stage_dir("output")
    name = cfg.run.name
    result: dict[str, str | None] = {}
    if cfg.output.lhe:
        src = ctx.out("generate", "lhe")
        result["lhe"] = ctx.rel(_keep(src, out / f"{name}.lhe", cfg.output.compress))
    if cfg.output.hepmc:
        src = ctx.out("shower", "hepmc") or ctx.out("generate", "hepmc")
        result["hepmc"] = ctx.rel(_keep(src, out / f"{name}.hepmc", cfg.output.compress))
    return result
