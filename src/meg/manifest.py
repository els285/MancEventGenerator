"""The per-run manifest: enough to say exactly what produced a sample, plus sanity numbers."""
from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .context import RunContext
from .util import log, sha256_file

KEY_PACKAGES = {"mg5amcnlo", "pythia8", "herwig", "thepeg", "lhapdf", "fastjet", "delphes",
                "hepmc2", "hepmc3", "gfortran", "python", "uproot", "pydantic"}


def lhe_summary(path: Path) -> dict:
    """Event count and cross-section from an LHE file, streaming (files can be large)."""
    events, xsec, xerr, expect = 0, None, None, 0
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("<event"):
                events += 1
            elif expect:
                expect -= 1
                if expect == 0 and xsec is None:
                    parts = line.split()
                    try:
                        xsec, xerr = float(parts[0]), float(parts[1])
                    except (ValueError, IndexError):
                        pass
            elif line.startswith("<init"):
                expect = 2           # <init>, beam line, then the line with xsec and its error
    return {"file": path.name, "events": events, "xsec_pb": xsec, "xsec_err_pb": xerr,
            "sha256": sha256_file(path)}


def root_summary(path: Path) -> dict:
    out: dict = {"file": path.name, "sha256": sha256_file(path)}
    try:
        import numpy as np
        import uproot
    except ImportError:
        out.update(entries=None, note="uproot not installed; entries not checked")
        return out
    with uproot.open(path) as f:
        tree = f["Delphes"]
        out["entries"] = int(tree.num_entries)
        out["has_Jet"] = "Jet" in tree.keys(recursive=False)
        try:
            sizes = tree["Jet_size"].array(library="np")
            out["mean_jet_multiplicity"] = float(np.mean(sizes)) if len(sizes) else None
        except Exception as e:  # noqa: BLE001
            out["mean_jet_multiplicity"] = f"unavailable ({e.__class__.__name__})"
    return out


def packages(env: dict) -> dict:
    prefix = env.get("CONDA_PREFIX")
    found: dict = {}
    if prefix:
        for p in Path(prefix, "conda-meta").glob("*.json"):
            m = json.loads(p.read_text())
            if m["name"] in KEY_PACKAGES:
                found[m["name"]] = {"version": m["version"], "build": m.get("build"),
                                    "channel": m.get("channel")}
    return found


def lockfile_hash(env: dict) -> str | None:
    root = env.get("PIXI_PROJECT_ROOT")
    lock = Path(root, "pixi.lock") if root else None
    return sha256_file(lock) if lock and lock.is_file() else None


def build(ctx: RunContext, fetched, timings: dict) -> dict:
    cfg = ctx.plan.config
    env = dict(ctx.env)
    m: dict = {
        "meg_version": __version__,
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "run": cfg.run.name,
        "fingerprint": cfg.fingerprint(),
        "config": cfg.model_dump(mode="json"),
        "toolchain": {"mg5_version": ctx.mg5.version(), "lockfile_sha256": lockfile_hash(env),
                      "packages": packages(env)},
        "model": ({"name": fetched.name, "tree_sha256": fetched.tree_sha256,
                   "source": fetched.source} if fetched else {"name": cfg.model.name, "builtin": True}),
        "stages": timings,
    }
    lhe = ctx.out("generate", "lhe")
    if lhe:
        m["lhe"] = lhe_summary(lhe)
    saved = {k: v for k, v in ctx.state.get("output", {}).get("outputs", {}).items() if v}
    if saved:
        m["saved"] = saved
    root = ctx.out("detector", "root")
    if root:
        m["delphes"] = root_summary(root)
    return m


def check(m: dict) -> list[str]:
    """Problems that mean the result is unusable (an empty sample is not a success)."""
    bad = []
    if m.get("lhe", {}).get("events") == 0:
        bad.append("the LHE file has no events")
    d = m.get("delphes")
    if d:
        if d.get("entries") == 0:
            bad.append("the Delphes tree has no entries (see detector/delphes.log)")
        if d.get("has_Jet") is False:
            bad.append("the Delphes tree has no Jet branch (did the FastJet module in the card run?)")
    return bad


def write(ctx: RunContext, m: dict) -> Path:
    p = ctx.run_dir / "manifest.json"
    p.write_text(json.dumps(m, indent=2) + "\n")
    log.info("manifest: %s", p)
    return p
