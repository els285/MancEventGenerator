"""Local backend: the replicas as subprocesses on this machine, N at a time.

It speaks the same job contract as the cluster (`meg _job`, an outbox per replica), so it is the cheap
way to try a campaign before sending it away, and what the tests use."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..util import log
from .campaign import Campaign, tag


def _kill(p: subprocess.Popen) -> None:
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(50):
            if p.poll() is not None:
                return
            time.sleep(0.1)
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_prepare(c: Campaign) -> int:
    """Build the campaign's process once, in a subprocess, like the cluster's PREPARE job."""
    pdir = c.dir / "prepare"
    pdir.mkdir(exist_ok=True)
    cmd = [sys.executable, "-m", "meg", "_prepare", "--meta", str(c.meta_path), "--config", str(c.config_path),
           "--outbox", str(pdir / "outbox")]
    log.info("building the MG5 process once ...")
    with open(pdir / "job.out", "w") as out, open(pdir / "job.err", "w") as err:
        p = subprocess.Popen(cmd, cwd=pdir, stdout=out, stderr=err, stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            return p.wait()
        except KeyboardInterrupt:
            _kill(p)
            raise


def run_all(c: Campaign, seeds: list[int], concurrency: int, prebuilt: Path | None = None) -> dict[int, int]:
    """Run `seeds` in a pool of `concurrency`; returns seed -> exit status."""
    live: list[subprocess.Popen] = []
    lock = threading.Lock()
    results: dict[int, int] = {}
    done = 0

    def one(seed: int) -> None:
        nonlocal done
        rdir = c.replica_dir(seed)
        rdir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "meg", "_job", "--meta", str(c.meta_path), "--config", str(c.config_path),
               "--seed", str(seed), "--outbox", str(rdir / "outbox")]
        if prebuilt:
            cmd += ["--prebuilt", str(prebuilt)]
        with open(rdir / "job.out", "w") as out, open(rdir / "job.err", "w") as err:
            p = subprocess.Popen(cmd, cwd=rdir, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                 start_new_session=True)
            with lock:
                live.append(p)
            rc = p.wait()
        with lock:
            live.remove(p)
            results[seed] = rc
            done += 1
            log.info("replica %s %s (%d/%d)", tag(seed), "ok" if rc == 0 else f"FAILED (exit {rc})",
                     done, len(seeds))

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            list(pool.map(one, seeds))
    except KeyboardInterrupt:
        with lock:
            for p in live:
                _kill(p)
        raise
    return results
