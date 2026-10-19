"""Herwig 7: build an input file from Herwig's own LHE template, then `read` and `run`."""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from . import proc
from .sysenv import conda_prefix
from .util import MegError, StageError

FAIL = re.compile(r"\*\* ERROR")      # as for Delphes: reported but exit status 0
TEMPLATES = {"LO": "LHE.in", "NLO": "LHE-MCatNLO.in"}


def build_input(template: str, *, lhe: Path, pdf: str, events: int, seed: int) -> tuple[str, str]:
    """Return (input text, run name). Every substitution must match exactly once, so a changed
    template fails here with a clear message instead of silently running with defaults."""
    s = template

    def sub(pattern: str, text: str) -> None:
        nonlocal s
        s, k = re.subn(pattern, lambda m: text, s, flags=re.MULTILINE)
        if k != 1:
            raise MegError(f"Herwig input: {pattern!r} matched {k} times (expected 1); "
                           "has Herwig's template changed?")

    sub(r"^set LesHouchesReader:FileName .*$", f"set LesHouchesReader:FileName {lhe}")
    sub(r"^set /Herwig/Partons/LHAPDF:PDFName .*$", f"set /Herwig/Partons/LHAPDF:PDFName {pdf}")
    sub(r"^set EventGenerator:NumberOfEvents .*$", f"set EventGenerator:NumberOfEvents {events}")
    sub(r"^set EventGenerator:RandomNumberGenerator:Seed .*$",
        f"set EventGenerator:RandomNumberGenerator:Seed {seed}")
    m = re.search(r"^saverun (\S+) EventGenerator\s*$", s, flags=re.MULTILINE)
    if not m:
        raise MegError("Herwig input: no 'saverun <name> EventGenerator' line in the template")
    # HepMC output, switched on before the run is saved
    s = s[:m.start()] + "read snippets/HepMC.in\n" + s[m.start():]
    return s, m.group(1)


def run(order: str, lhe: Path, pdf: str, events: int, seed: int, cwd: Path,
        env: Mapping[str, str], echo: str) -> Path:
    """Shower `lhe` with Herwig 7 and return the HepMC file."""
    prefix = conda_prefix(env)
    if prefix is None:
        raise MegError("CONDA_PREFIX is not set")
    tmpl = prefix / "share" / "Herwig" / TEMPLATES[order]
    if not tmpl.is_file():
        raise MegError(f"Herwig template not found: {tmpl}")
    text, runname = build_input(tmpl.read_text(), lhe=lhe, pdf=pdf, events=events, seed=seed)
    (cwd / "hw7.in").write_text(text)
    proc.run(["Herwig", "read", "hw7.in"], log_file=cwd / "herwig_read.log", cwd=cwd, env=env,
             echo=echo, fail_re=FAIL)
    if not (cwd / f"{runname}.run").is_file():
        raise StageError(f"Herwig read did not write {runname}.run (see herwig_read.log)")
    proc.run(["Herwig", "run", f"{runname}.run", "-N", str(events)], log_file=cwd / "herwig_run.log",
             cwd=cwd, env=env, echo=echo, fail_re=FAIL)
    hepmc = sorted(cwd.glob("*.hepmc*"))
    if not hepmc:
        raise StageError("Herwig finished but wrote no HepMC file (see herwig_run.log)")
    return hepmc[0]
