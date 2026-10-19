"""One replica, as it runs on a worker node (or in a local subprocess).

The contract with every scheduler: run one ordinary MEG run in node-local scratch, then leave a
directory `outbox/` of final, uniquely named files plus `status.json`. How the outbox gets back to the
submit side is the scheduler's business (HTCondor transfers it). The job reads only the two small
files it is given (campaign.json, config.json), so it needs no access to the campaign directory."""
from __future__ import annotations

import gzip
import json
import os
import shutil
import socket
import tarfile
import tempfile
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__, runner
from ..config import Config
from ..util import MegError, log, sha256_file
from .campaign import tag, unique_name

LOG_SUFFIXES = {".log", ".mg5", ".txt"}
LOG_NAMES = {"config.resolved.json", "manifest.json", "run_card.dat", "param_card.dat", "madspin_card.dat",
             "proc_card_mg5.dat"}
MAX_LOG_BYTES = 20 << 20


def _scratch_parent() -> str | None:
    return os.environ.get("_CONDOR_SCRATCH_DIR") or os.environ.get("TMPDIR") or None


def _gzip(src: Path, dest: Path) -> None:
    with open(src, "rb") as fi, gzip.open(dest, "wb", compresslevel=4) as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)


def _find_hepmc(run_dir: Path) -> Path | None:
    for pattern in ("shower/*.hepmc", "shower/*.hepmc.gz", "generate/events.hepmc", "generate/events.hepmc.gz"):
        hits = sorted(run_dir.glob(pattern))
        if hits:
            return hits[0]
    return None


def _logs_tar(run_dir: Path, dest: Path) -> None:
    """Small provenance bundle: logs, command files, cards, stage records, manifest. Never the big files."""
    with tarfile.open(dest, "w:gz", compresslevel=6) as t:
        if not run_dir.is_dir():
            return
        for f in sorted(run_dir.rglob("*")):
            if not f.is_file() or f.stat().st_size > MAX_LOG_BYTES:
                continue
            rel = f.relative_to(run_dir)
            in_proc = "mg5_proc" in rel.parts
            wanted = f.name in LOG_NAMES if in_proc else (
                f.suffix in LOG_SUFFIXES or f.name in LOG_NAMES or rel.parts[0] == ".meg")
            if in_proc and "Cards" not in rel.parts:
                wanted = False
            if wanted:
                t.add(f, arcname=str(Path(run_dir.name) / rel), recursive=False)


def _archive_run(run_dir: Path, dest: Path) -> None:
    with tarfile.open(dest, "w:gz", compresslevel=4) as t:
        t.add(run_dir, arcname=run_dir.name)


def _write_outputs(cfg: Config, result: runner.RunResult, outbox: Path, cid: str, seed: int) -> None:
    ex = cfg.execution
    if ex.retrieve == "all":
        _archive_run(result.run_dir, outbox / unique_name(cid, seed, "run"))
        return
    for kind in ex.retrieve or []:
        if kind == "delphes":
            src = result.delphes_root
            if not src:
                raise MegError("retrieve = delphes, but the run produced no Delphes file")
            shutil.copy2(src, outbox / unique_name(cid, seed, "delphes"))
        elif kind == "lhe":
            src = result.lhe
            if not src:
                raise MegError("retrieve = lhe, but the run produced no LHE file")
            _gzip(src, outbox / unique_name(cid, seed, "lhe"))
        elif kind == "hepmc":
            src = _find_hepmc(result.run_dir)
            if not src:
                raise MegError("retrieve = hepmc, but the run produced no HepMC file")
            if src.suffix == ".gz":
                shutil.copy2(src, outbox / unique_name(cid, seed, "hepmc"))
            else:
                _gzip(src, outbox / unique_name(cid, seed, "hepmc"))


def _ship(outbox: Path, dest: Path) -> dict[str, dict]:
    """Move every file of the outbox (status.json aside) to `dest`, which a worker node can write to but the
    submit side may not have room for. Each file is copied under a temporary name, size-checked, renamed, and
    only then removed from the outbox. Returns the files' records, marked remote."""
    dest.mkdir(parents=True, exist_ok=True)
    moved: dict[str, dict] = {}
    for f in sorted(outbox.iterdir()):
        if not f.is_file() or f.name.startswith("status.json"):
            continue
        size, digest = f.stat().st_size, sha256_file(f)
        part = dest / (f.name + ".part")
        shutil.copyfile(f, part)
        if part.stat().st_size != size:
            part.unlink(missing_ok=True)
            raise MegError(f"copy of {f.name} to {dest} came out {part.stat().st_size} bytes, not {size}")
        part.replace(dest / f.name)
        f.unlink()
        moved[f.name] = {"bytes": size, "sha256": digest, "remote": True}
    return moved


def _drop_payload(outbox: Path) -> None:
    """After a failed copy to the remote directory: keep only the small provenance files locally."""
    for f in outbox.iterdir():
        if f.is_file() and f.name != "status.json" and not f.name.endswith((".logs.tar.gz", ".manifest.json")):
            f.unlink()


def run_replica(meta_path: Path, config_path: Path, seed: int, outbox: Path) -> int:
    """Run replica `seed`. Returns the process exit status (0 = outputs complete)."""
    meta = json.loads(Path(meta_path).read_text())
    base = json.loads(Path(config_path).read_text())
    cid = meta["id"]
    if meta.get("offline"):
        os.environ["MEG_OFFLINE"] = "1"
    outbox = Path(outbox)
    out_root = (base.get("execution") or {}).get("output_dir")
    remote = Path(out_root) / cid if out_root else None
    if outbox.exists():
        shutil.rmtree(outbox)             # nothing from an earlier attempt may look like this attempt's result
    outbox.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix=f"meg-{tag(seed)}-", dir=_scratch_parent()))
    name = f"{cid}_{tag(seed)}"
    run_dir = scratch / name
    started = datetime.now(UTC)
    t0 = time.time()
    status: dict = {"state": "failed", "campaign": cid, "seed": seed, "host": socket.gethostname(),
                    "started": started.isoformat(timespec="seconds"), "meg_version": __version__}
    try:
        data = dict(base)
        data["run"] = {**data["run"], "name": name, "seed": seed, "output_dir": str(scratch)}
        cfg = Config.model_validate(data)
        result = runner.run(cfg, echo="none")
        _write_outputs(cfg, result, outbox, cid, seed)
        shutil.copy2(result.manifest_path, outbox / unique_name(cid, seed, "manifest"))
        lhe = result.manifest.get("lhe", {})
        status.update(state="ok", xsec_pb=lhe.get("xsec_pb"), xsec_err_pb=lhe.get("xsec_err_pb"),
                      events=lhe.get("events"))
    except Exception as e:                     # noqa: BLE001 - whatever happened is reported, never lost
        status["error"] = f"{type(e).__name__}: {e}"
        status["traceback"] = traceback.format_exc()[-4000:]
        log.error("replica %s failed: %s", tag(seed), e)
    finally:
        try:
            _logs_tar(run_dir, outbox / unique_name(cid, seed, "logs"))
        except Exception as e:                 # noqa: BLE001
            status["logs_error"] = str(e)
        if status["state"] != "ok":
            status.setdefault("error", "interrupted or killed before the run finished")
        status["seconds"] = round(time.time() - t0, 1)
        status["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
        shipped: dict[str, dict] = {}
        if remote is not None and status["state"] == "ok":
            try:
                shipped = _ship(outbox, remote)
                status["remote_dir"] = str(remote)
            except Exception as e:             # noqa: BLE001 - a failed copy makes the replica a failed one
                status.update(state="failed", error=f"copying the results to {remote}: {type(e).__name__}: {e}")
                _drop_payload(outbox)
                for part in remote.glob("*.part"):
                    if part.name.startswith(f"{name}."):
                        part.unlink(missing_ok=True)
        local_files = {f.name: {"bytes": f.stat().st_size, "sha256": sha256_file(f)}
                       for f in sorted(outbox.iterdir()) if f.is_file() and not f.name.startswith("status.json")}
        status["files"] = {**shipped, **local_files}
        tmp = outbox / "status.json.tmp"
        tmp.write_text(json.dumps(status, indent=2) + "\n")
        tmp.replace(outbox / "status.json")    # appears only when complete: its presence means "finished"
        shutil.rmtree(scratch, ignore_errors=True)
    return 0 if status["state"] == "ok" else 1
