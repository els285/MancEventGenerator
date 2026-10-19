"""Gather a campaign's results into outputs/ under their unique names and combine the cross sections."""
from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path

from ..util import MegError, log, sha256_file
from .campaign import Campaign, tag


def _link(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def combine(points: list[tuple[float, float]]) -> dict:
    """Inverse-variance weighted mean of per-replica cross sections, with a consistency check.
    `chi2_ndf` near 1 means the replicas agree within their quoted errors."""
    pts = [(x, e) for x, e in points if x is not None]
    if not pts:
        return {}
    if all(e and e > 0 for _, e in pts):
        w = [1 / e**2 for _, e in pts]
        mean = sum(wi * x for wi, (x, _) in zip(w, pts, strict=True)) / sum(w)
        err = math.sqrt(1 / sum(w))
        out = {"xsec_pb": mean, "xsec_err_pb": err, "replicas": len(pts)}
        if len(pts) > 1:
            out["chi2_ndf"] = sum(wi * (x - mean) ** 2 for wi, (x, _) in zip(w, pts, strict=True)) / (len(pts) - 1)
        return out
    mean = sum(x for x, _ in pts) / len(pts)
    return {"xsec_pb": mean, "xsec_err_pb": None, "replicas": len(pts)}


def collect(c: Campaign, *, verify: bool = False) -> dict:
    c.outputs.mkdir(exist_ok=True)
    ok, bad, missing, points, events = [], [], [], [], 0
    for s in c.seeds:
        st = c.read_status(s)
        if st is None:
            missing.append(s)
            continue
        if st["state"] != "ok":
            bad.append(s)
        else:
            ok.append(s)
            events += st.get("events") or 0
            points.append((st.get("xsec_pb"), st.get("xsec_err_pb")))
        # every finished replica brings its files home, failures included (their logs say why)
        for name, info in st.get("files", {}).items():
            if info.get("remote"):
                # lives where the job put it (e.g. EOS); checked here, never copied onto the campaign disk
                rsrc = Path(st["remote_dir"]) / name
                if not rsrc.is_file():
                    raise MegError(f"{rsrc} is listed in the replica's status but missing")
                if rsrc.stat().st_size != info["bytes"] or (verify and sha256_file(rsrc) != info["sha256"]):
                    raise MegError(f"{rsrc} does not match the checksum recorded by the job")
                continue
            src = c.outbox(s) / name
            if not src.is_file():
                raise MegError(f"{src} is listed in the replica's status but missing")
            if src.stat().st_size != info["bytes"] or (verify and sha256_file(src) != info["sha256"]):
                raise MegError(f"{src} does not match the checksum recorded by the job (damaged transfer?)")
            _link(src, c.outputs / name)
        _link(c.outbox(s) / "status.json", c.outputs / f"{c.id}_{tag(s)}.status.json")
    summary = {"campaign": c.id, "replicas": len(c.seeds), "ok": len(ok), "failed": bad, "missing": missing,
               "events": events, **combine([(x, e) for x, e in points])}
    if c.meta.get("output_dir"):
        summary["output_dir"] = c.meta["output_dir"]
    (c.outputs / f"{c.id}.summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    log.info("collected %d replicas into %s", len(ok) + len(bad), c.outputs)
    return summary


def summary_text(s: dict) -> str:
    lines = [f"campaign {s['campaign']}: {s['ok']}/{s['replicas']} replicas ok, {s['events']} events"]
    if s.get("xsec_pb") is not None:
        err = f" +- {s['xsec_err_pb']:.3g}" if s.get("xsec_err_pb") else ""
        lines.append(f"combined cross-section: {s['xsec_pb']:.6g}{err} pb")
        if s.get("chi2_ndf") is not None:
            lines.append(f"replica consistency chi2/ndf = {s['chi2_ndf']:.2f} (about 1 is healthy)")
    if s.get("output_dir"):
        lines.append(f"results are in {s['output_dir']}")
    if s["failed"]:
        more = " ..." if len(s["failed"]) > 20 else ""
        lines.append("failed: " + ", ".join(tag(x) for x in s["failed"][:20]) + more)
    if s["missing"]:
        lines.append(f"not finished yet: {len(s['missing'])} replicas")
    return "\n".join(lines)
