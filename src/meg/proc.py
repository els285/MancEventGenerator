"""Run external programs: stream their output to a log file, show a filtered copy on screen,
and turn failures into errors. Many HEP tools exit 0 after printing an error, so besides the
exit status we also scan the output for a failure pattern."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from .util import StageError, log

# MG5 prints these a lot; they are harmless. They are hidden on screen only, never in the log.
MG5_NOISE = re.compile(r"run_card missed argument|DEBUG: (remove parameters|fix parameter value)|^\s*$")


class CommandFailed(StageError):
    pass


TERMINATE_GRACE = 5.0       # seconds each polite signal gets before the next, harder one


def _terminate(p: subprocess.Popen, name: str) -> None:
    """Stop `p` and everything it started (MG5 spawns make, compilers and worker processes).
    Politely first (SIGINT, then SIGTERM), then SIGKILL; a second Ctrl+C skips straight to SIGKILL."""
    log.warning("interrupted: stopping %s and its child processes ...", name)
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                return
            try:
                p.wait(timeout=TERMINATE_GRACE)
                break
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        log.warning("killing now")
    try:
        os.killpg(p.pid, signal.SIGKILL)      # anything the leader left behind
    except ProcessLookupError:
        pass
    p.wait()


def run(
    cmd: Sequence[str | Path],
    *,
    log_file: Path,
    cwd: Path,
    env: Mapping[str, str],
    echo: str = "none",               # "all" | "filtered" | "none": what reaches the screen
    noise: re.Pattern | None = None,
    fail_re: re.Pattern | None = None,
    heartbeat: float = 60.0,          # seconds between "still running" lines when output is hidden
) -> None:
    """Run `cmd`; raise CommandFailed if the exit status is non-zero or `fail_re` matches.
    The log file always gets everything; on failure the end of it is shown if it was hidden."""
    cmd = [str(c) for c in cmd]
    log_file.parent.mkdir(parents=True, exist_ok=True)
    matched: str | None = None
    try:
        # Own session/process group so Ctrl+C can be forwarded to the whole tree; no stdin, so a
        # tool that unexpectedly asks a question gets EOF instead of hanging on the terminal.
        p = subprocess.Popen(cmd, cwd=cwd, env=dict(env), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                             errors="replace", bufsize=1, start_new_session=True)
    except FileNotFoundError as e:
        raise CommandFailed(f"cannot run {cmd[0]!r}: {e}. Is it installed in this environment "
                            f"(run `meg doctor`)?") from e
    stop = threading.Event()
    if echo != "all" and heartbeat > 0:
        t0 = time.time()

        def beat() -> None:
            while not stop.wait(heartbeat):
                m, s = divmod(int(time.time() - t0), 60)
                log.info("  still running %s (%dm%02ds)  log: %s", Path(cmd[0]).name, m, s, log_file)

        threading.Thread(target=beat, daemon=True).start()
    try:
        with open(log_file, "w") as lf:
            lf.write("$ " + " ".join(cmd) + "\n")
            assert p.stdout is not None
            for line in p.stdout:
                lf.write(line)
                if fail_re and matched is None and fail_re.search(line):
                    matched = line.strip()
                if echo == "all" or (echo == "filtered" and not (noise and noise.search(line))):
                    sys.stdout.write(line)
            rc = p.wait()
    except KeyboardInterrupt:
        _terminate(p, Path(cmd[0]).name)
        raise
    finally:
        stop.set()
    name = Path(cmd[0]).name
    problem = (f"`{name}` failed with exit status {rc}" if rc != 0 else
               f"`{name}` exited 0 but reported: {matched}" if matched else None)
    if problem:
        msg = f"{problem} (log: {log_file})"
        if echo != "all":          # the user has not seen the output, so show where it went wrong
            tail = [ln for ln in log_file.read_text(errors="replace").splitlines() if ln.strip()][-25:]
            msg += "\n--- end of the log ---\n" + "\n".join(tail)
        raise CommandFailed(msg)


def capture(cmd: Sequence[str | Path], env: Mapping[str, str], timeout: int = 60) -> str:
    """Run a short command and return stdout+stderr (never raises)."""
    try:
        r = subprocess.run([str(c) for c in cmd], env=dict(env), capture_output=True, text=True,
                           timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001 - diagnostics must not fail
        return f"<failed: {e}>"
