"""Delphes: pick the right reader for the input file and check the result."""
from __future__ import annotations

import gzip
import re
import shutil
from collections.abc import Mapping
from pathlib import Path

from . import proc
from .util import MegError, StageError, gunzip

FAIL = re.compile(r"\*\* ERROR")       # Delphes prints this and still exits 0 with an empty tree


def resolve_card(card: str) -> Path:
    """A path to a .tcl file, or the name of a packaged card (e.g. ATLAS)."""
    p = Path(card).expanduser()
    if p.is_file():
        return p.resolve()
    from importlib import resources
    packaged = resources.files("meg") / "data" / "delphes" / f"{card}.tcl"
    if packaged.is_file():
        return Path(str(packaged))
    names = sorted(x.name[:-4] for x in (resources.files("meg") / "data" / "delphes").iterdir()
                   if x.name.endswith(".tcl"))
    raise MegError(f"Delphes card {card!r} is neither a file nor a packaged card ({', '.join(names)})")


def hepmc_header(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", errors="replace") as f:
        return "".join(f.readline() for _ in range(5))


def executable_for(path: Path, env: Mapping[str, str]) -> str:
    """Delphes has two HepMC parsers: DelphesHepMC2 reads the legacy 'IO_GenEvent' layout and
    DelphesHepMC3 reads HepMC3's 'Asciiv3'. Choose by the file header, not by assumption."""
    name = path.name
    if name.endswith((".lhe", ".lhe.gz")):
        exe = "DelphesLHEF"
    elif name.endswith((".hepmc", ".hepmc.gz", ".hepmc2", ".hepmc3")) or ".hepmc" in name:
        exe = "DelphesHepMC3" if "Asciiv3" in hepmc_header(path) else "DelphesHepMC2"
    else:
        raise MegError(f"don't know how to read {path.name} with Delphes")
    found = shutil.which(exe, path=env.get("PATH"))
    if not found:
        raise MegError(f"{exe} not found in this environment (run `meg doctor`)")
    return found


def run(events: Path, card: Path, out_root: Path, cwd: Path, env: Mapping[str, str],
        echo: str) -> None:
    if events.suffix == ".gz":             # Delphes readers need plain files
        events = gunzip(events, cwd / events.name[:-3])
    exe = executable_for(events, env)
    proc.run([exe, card, out_root, events], log_file=cwd / "delphes.log", cwd=cwd, env=env,
             echo=echo, fail_re=FAIL)
    if not out_root.is_file():
        raise StageError(f"Delphes did not write {out_root.name}")
