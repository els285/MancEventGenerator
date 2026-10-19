"""The 'build once' job: generate the MG5 process directory a single time for the whole campaign.

Model import and diagram generation (the `output` step) depend on the physics, not on the seed, and for
NLO they take minutes. This job does them once and packs the result (process.tar.gz) into its outbox;
every replica then unpacks it and only edits the cards and launches. Same contract as a replica: an
outbox with a status.json that appears only when the job has finished."""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__, process_dir, runner
from ..config import Config
from ..util import log
from .job import _logs_tar, _scratch_parent

ARCHIVE = "process.tar.gz"


def run_prepare(meta_path: Path, config_path: Path, outbox: Path) -> int:
    meta = json.loads(Path(meta_path).read_text())
    base = json.loads(Path(config_path).read_text())
    cid = meta["id"]
    if meta.get("offline"):
        os.environ["MEG_OFFLINE"] = "1"
    outbox = Path(outbox)
    if outbox.exists():
        shutil.rmtree(outbox)
    outbox.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="meg-prepare-", dir=_scratch_parent()))
    name = f"{cid}_prepare"
    run_dir = scratch / name
    t0 = time.time()
    status: dict = {"state": "failed", "stage": "prepare", "campaign": cid, "host": socket.gethostname(),
                    "started": datetime.now(UTC).isoformat(timespec="seconds"), "meg_version": __version__}
    try:
        data = dict(base)
        data["run"] = {**data["run"], "name": name, "seed": meta["seeds"][0], "output_dir": str(scratch)}
        cfg = Config.model_validate(data)
        proc_dir = runner.build_process(cfg, run_dir)
        process_dir.pack(proc_dir, outbox / ARCHIVE, {"campaign": cid, "process_id": cfg.process_id(),
                                                      "meg_version": __version__})
        status.update(state="ok", bytes=(outbox / ARCHIVE).stat().st_size)
    except Exception as e:                       # noqa: BLE001
        status["error"] = f"{type(e).__name__}: {e}"
        status["traceback"] = traceback.format_exc()[-4000:]
        log.error("prepare failed: %s", e)
    finally:
        try:
            _logs_tar(run_dir, outbox / f"{cid}_prepare.logs.tar.gz")
        except Exception as e:                   # noqa: BLE001
            status["logs_error"] = str(e)
        if status["state"] != "ok":
            status.setdefault("error", "interrupted or killed before the process was built")
        status["seconds"] = round(time.time() - t0, 1)
        status["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
        tmp = outbox / "status.json.tmp"
        tmp.write_text(json.dumps(status, indent=2) + "\n")
        tmp.replace(outbox / "status.json")
        shutil.rmtree(scratch, ignore_errors=True)
    return 0 if status["state"] == "ok" else 1
