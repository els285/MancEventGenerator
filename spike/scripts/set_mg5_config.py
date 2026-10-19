#!/usr/bin/env python3
"""Set `key = value` options in an MG5 mg5_configuration.txt.

Usage: set_mg5_config.py FILE key=value [key=value ...]

Replaces an existing (possibly commented-out) `key = ...` line, or appends the option.
This is the programmatic version of the `sed -i 's/# pythia8_path = .../'` lines in MadLAD's
container/commands.py.
"""
import re
import sys
from pathlib import Path


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    path = Path(argv[1])
    wanted = dict(a.split("=", 1) for a in argv[2:])
    lines = path.read_text().splitlines()
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*#?\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in wanted and m.group(1) not in done:
            key = m.group(1)
            lines[i] = f"{key} = {wanted[key]}"
            done.add(key)
    for key, val in wanted.items():
        if key not in done:
            lines.append(f"{key} = {val}")
    path.write_text("\n".join(lines) + "\n")
    for key, val in wanted.items():
        print(f"{path.name}: {key} = {val}")


if __name__ == "__main__":
    main(sys.argv)
