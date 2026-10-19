#!/usr/bin/env python3
"""Validate a smoke-test result and write a small provenance manifest.

This is a preview of the per-run manifest.json proposed for the new pipeline: it records
exactly which package builds produced the sample, plus basic sanity numbers.
Exit status is non-zero if there are no events or no Delphes entries.
"""
import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

KEY_PACKAGES = {"pythia8", "lhapdf", "fastjet", "delphes", "hepmc2", "mg5amcnlo",
                "gfortran", "gcc", "python", "uproot"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", errors="replace") as f:
        return f.read()


def lhe_summary(path: str) -> dict:
    if not path or not Path(path).exists():
        return {"present": False}
    text = read_text(Path(path))
    n_events = len(re.findall(r"<event[ >]", text))
    xsec = None
    m = re.search(r"<init>\s*\n[^\n]*\n\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)", text)
    if m:
        xsec = float(m.group(1))
    return {"present": True, "file": Path(path).name, "events": n_events, "xsec_pb": xsec}


def root_summary(path: str) -> dict:
    import numpy as np
    import uproot

    with uproot.open(path) as f:
        tree = f["Delphes"]
        out = {"entries": int(tree.num_entries), "has_Jet": "Jet" in tree.keys(recursive=False)}
        try:
            sizes = tree["Jet_size"].array(library="np")
            out["mean_jet_multiplicity"] = float(np.mean(sizes)) if len(sizes) else None
        except Exception as e:  # noqa: BLE001
            out["mean_jet_multiplicity"] = f"unavailable ({e.__class__.__name__})"
    return out


def packages() -> dict:
    prefix = os.environ.get("CONDA_PREFIX")
    found = {}
    if prefix:
        for p in Path(prefix, "conda-meta").glob("*.json"):
            m = json.loads(p.read_text())
            if m["name"] in KEY_PACKAGES:
                found[m["name"]] = {"version": m["version"], "build": m.get("build"),
                                    "channel": m.get("channel"), "sha256": m.get("sha256")}
    return found


def mg5_version(mg5: str) -> str:
    vfile = Path(mg5).resolve().parent.parent / "VERSION"
    if vfile.exists():
        for line in vfile.read_text().splitlines():
            if line.startswith("version"):
                return line.split("=", 1)[1].strip()
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--lhe", default="")
    ap.add_argument("--root", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--mg5", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    spike_root = Path(__file__).resolve().parent.parent
    lock = spike_root / "pixi.lock"
    manifest = {
        "stage": a.name,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": os.environ.get("PIXI_ENVIRONMENT_NAME", "default"),
        "platform": platform.platform(),
        "lockfile_sha256": sha256(lock) if lock.exists() else None,
        "mg5": {"launcher": a.mg5, "version": mg5_version(a.mg5)},
        "packages": packages(),
        "seed": a.seed,
        "lhe": lhe_summary(a.lhe),
        "delphes": root_summary(a.root),
    }
    Path(a.out).write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ("stage", "lhe", "delphes")}, indent=2))

    problems = []
    if manifest["lhe"].get("present") and manifest["lhe"]["events"] == 0:
        problems.append("LHE file has no events")
    if manifest["delphes"]["entries"] == 0:
        problems.append("Delphes ROOT tree has no entries")
    if not manifest["delphes"]["has_Jet"]:
        problems.append("Delphes tree has no Jet branch (FastJet module in the card did not run?)")
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
