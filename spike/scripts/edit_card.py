#!/usr/bin/env python3
"""Edit values in an MG5 run_card.

Usage: edit_card.py CARD key=value [key=value ...]

Run-card lines look like `  1000 = nevents ! comment`. The value (left of `=`) is replaced,
the key match is case-insensitive and the comment is kept. Same idea as MadLAD's edit_run(),
but it is strict: an unknown key is an error instead of silently being appended, so a typo
cannot quietly change the physics.
"""
import sys
from pathlib import Path


def edit(path: Path, wanted: dict) -> None:
    lines = path.read_text().splitlines()
    used = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            body, bang, comment = line.partition("!")
            value, _, key = body.rpartition("=")
            k = key.strip().lower()
            if k in wanted:
                new = f" {wanted[k]} = {key.strip()}"
                line = new + (f"  !{comment}" if bang else "")
                used.add(k)
        out.append(line)
    missing = set(wanted) - used
    if missing:
        sys.exit(f"{path}: keys not found in card: {sorted(missing)}")
    path.write_text("\n".join(out) + "\n")
    for k in sorted(used):
        print(f"{path.name}: {k} = {wanted[k]}")


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    path = Path(argv[1])
    if not path.exists():
        sys.exit(f"no such card: {path}")
    wanted = {}
    for a in argv[2:]:
        k, _, v = a.partition("=")
        wanted[k.strip().lower()] = v
    edit(path, wanted)


if __name__ == "__main__":
    main(sys.argv)
