"""When a stage fails, gather everything needed to debug it into <run>/<stage>/diag.txt.

MG5 hides the compiler output of the process builds it launches, so for NLO we repeat MG5's own
build targets in the first process directory and capture the real compiler/linker message."""
from __future__ import annotations

import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .context import RunContext
from .proc import capture

ENV_VARS = ("FC", "F77", "CC", "CXX", "FFLAGS", "FORTRANFLAGS", "CFLAGS", "CXXFLAGS", "CPPFLAGS",
            "LDFLAGS", "SDKROOT", "CONDA_BUILD_SYSROOT", "MACOSX_DEPLOYMENT_TARGET",
            "DEVELOPER_DIR", "LHAPDF_DATA_PATH", "CONDA_PREFIX", "LD_LIBRARY_PATH")
LOGS = ("proc.log", "launch.log", "herwig_read.log", "herwig_run.log", "delphes.log")
MG5_TARGETS = ("test_soft_col_limits", "gensym", "madevent_mintMC", "reweight_xsec_events")


def _tail(p: Path, n: int = 80) -> str:
    return "\n".join(p.read_text(errors="replace").splitlines()[-n:])


def _head(p: Path, n: int = 200) -> str:
    return "\n".join(p.read_text(errors="replace").splitlines()[:n])


def _make(cwd: Path, target: str | None, env) -> tuple[int, str]:
    cmd = ["make"] + ([target] if target else [])
    r = subprocess.run(cmd, cwd=cwd, env=dict(env), capture_output=True, text=True, timeout=1800)
    return r.returncode, "\n".join((r.stdout + r.stderr).splitlines()[-80:])


def collect(ctx: RunContext, stage: str, error: str) -> Path:
    d = ctx.run_dir / stage
    d.mkdir(parents=True, exist_ok=True)
    out = d / "diag.txt"
    env = ctx.env
    w: list[str] = []
    w.append(f"### diag for {ctx.plan.config.run.name}/{stage} "
             f"({datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')})")
    w.append(f"### error\n{error}")
    w.append(f"### platform\n{platform.platform()}")
    w.append("### environment variables that affect the build")
    w += [f"{k}={env[k]}" for k in ENV_VARS if k in env]
    w.append("### compilers")
    for t in (env.get("FC", "gfortran"), env.get("CXX", "c++")):
        w.append(f"--- {t}\n" + "\n".join(capture([t, "--version"], env).splitlines()[:2]))
    w.append("### resolved configuration")
    w.append(ctx.plan.config.model_dump_json(indent=2))

    proc_dirs = sorted(d.glob("mg5_proc"))
    for pd in proc_dirs:
        mk = pd / "Source" / "make_opts"
        if mk.is_file():
            keep = [ln for ln in mk.read_text().splitlines()
                    if re.match(r"^(lhapdf|lhapdf_config|STDLIB|DEFAULT_|FFLAGS|CXXFLAGS|LDFLAGS)", ln)]
            w.append("### make_opts (PDF / compiler / link settings)\n" + "\n".join(keep))
    for lg in LOGS:
        if (d / lg).is_file():
            w.append(f"### last 80 lines of {lg}\n{_tail(d / lg)}")
    if (d / "hw7.in").is_file():
        keep = [ln for ln in (d / "hw7.in").read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        w.append("### hw7.in (generated Herwig input)\n" + "\n".join(keep[:80]))

    for pd in proc_dirs:
        w.append("### MG5 debug logs, first 200 lines each (the compile or link error is in here)")
        for f in [d / "MG5_debug", *pd.glob("run_*_debug.log"), *pd.glob("*/ME5_debug")]:
            if f.is_file():
                w.append(f"--- {f}\n{_head(f)}")
        # MG5 hides the output of its NLO build targets; repeat them and stop at the first failure.
        subs = sorted((pd / "SubProcesses").glob("P*/makefile"))
        if subs:
            p0 = subs[0].parent
            w.append("### re-running MG5's own build targets in the first process directory")
            for t in MG5_TARGETS:
                rc, txt = _make(p0, t, env)
                w.append(f"--- make {t} in {p0}\n{txt}")
                if rc != 0:
                    w.append(f">>> make {t} FAILED (exit {rc})")
                    break
        n = 0
        for v in sorted((pd / "SubProcesses").glob("P*/V*/makefile")):
            if list(v.parent.glob("*.a")):
                continue
            if n >= 2:
                break
            n += 1
            w.append(f"### make where a library is missing: {v.parent}\n{_make(v.parent, None, env)[1]}")
    out.write_text("\n\n".join(w) + "\n")
    return out
