"""Strict editors for MG5's run_card.dat and param_card.dat.

Strict means an unknown key is an error, not a silently appended line, so a typo cannot quietly
change the physics. (MadLAD's edit_run() appended unknown keys.)
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from .util import MegError


def fmt_card_value(v: bool | float | str) -> str:
    """Format a Python value the way MG5 cards expect. Strings are written verbatim."""
    if isinstance(v, bool):
        return ".true." if v else ".false."
    if isinstance(v, float):
        return repr(v)
    return str(v)


def edit_run_card(path: Path, edits: Mapping[str, bool | int | float | str]) -> dict[str, str]:
    """Run-card lines look like `  1000 = nevents ! comment`: value left of '=', key right."""
    wanted = {k.strip().lower(): fmt_card_value(v) for k, v in edits.items()}
    used: dict[str, str] = {}
    out = []
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            body, bang, comment = line.partition("!")
            _, _, key = body.rpartition("=")
            k = key.strip().lower()
            if k in wanted:
                line = f" {wanted[k]} = {key.strip()}" + (f"  !{comment}" if bang else "")
                used[k] = wanted[k]
        out.append(line)
    missing = sorted(set(wanted) - set(used))
    if missing:
        raise MegError(f"{path.name}: keys not found in the card: {missing}. Check the spelling "
                       f"against the card MG5 generated (it differs between MG5 versions).")
    path.write_text("\n".join(out) + "\n")
    return used


_BLOCK = re.compile(r"^\s*block\s+(\S+)", re.IGNORECASE)
_ENTRY = re.compile(r"^(\s*)((?:\d+\s+)+)(\S+)(\s*#\s*)(\S+)(.*)$")
_DECAY = re.compile(r"^(\s*decay\s+)(\d+)(\s+)(\S+)(.*)$", re.IGNORECASE)


def edit_param_card(path: Path, params: Mapping[str, float | int]) -> dict[str, float | int]:
    """Set parameters by name (the word after '#') or by 'BLOCK:id[,id]' (e.g. 'MASS:6')."""
    wanted = {k: v for k, v in params.items()}
    hits: dict[str, int] = {k: 0 for k in wanted}
    lines = path.read_text().splitlines()
    block = ""
    for i, line in enumerate(lines):
        mb = _BLOCK.match(line)
        if mb:
            block = mb.group(1).upper()
            continue
        md = _DECAY.match(line)
        if md:        # the width line often has no comment (SMEFTsim), so DECAY:<pdg> always works
            named = re.match(r"\s*#\s*(\S+)", md.group(5))
            keys = {f"decay:{md.group(2)}"} | ({named.group(1).lower()} if named else set())
            for k, v in wanted.items():
                if k.lower() in keys:
                    lines[i] = f"{md.group(1)}{md.group(2)}{md.group(3)}{v!r}{md.group(5)}"
                    hits[k] += 1
            continue
        me = _ENTRY.match(line)
        if me and block:
            ids = ",".join(me.group(2).split())
            keys = {me.group(5).lower(), f"{block}:{ids}".lower()}
            for k, v in wanted.items():
                if k.lower() in keys:
                    lines[i] = (f"{me.group(1)}{me.group(2)}{v!r}{me.group(4)}"
                                f"{me.group(5)}{me.group(6)}")
                    hits[k] += 1
    problems = [f"{k!r} not found" for k, n in hits.items() if n == 0]
    problems += [f"{k!r} matches {n} entries (use BLOCK:id)" for k, n in hits.items() if n > 1]
    if problems:
        raise MegError(f"{path.name}: " + "; ".join(problems) +
                       ". Names are the word after '#' in the card; open the card in the run "
                       "directory to see them.")
    path.write_text("\n".join(lines) + "\n")
    return dict(wanted)
