#!/usr/bin/env python3
"""Inspect the active environment and report what the spike cares about.

Exit code is non-zero only for hard failures (a tool that cannot work at all). Things that
need a human look (Pythia8 build options, compiler versions) are printed as WARN so the
output of this script can be pasted into an issue when the spike fails.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FAILS: list[str] = []
WARNS: list[str] = []


def run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001 - we want to report anything
        return f"<failed: {e}>"


def need(name: str, version_cmd: list[str] | None = None) -> str | None:
    path = shutil.which(name)
    if not path:
        FAILS.append(f"{name} not on PATH")
        print(f"  FAIL  {name:18} not found")
        return None
    ver = run(version_cmd).splitlines()[0] if version_cmd else ""
    print(f"  ok    {name:18} {ver}  [{path}]")
    return path


def main() -> int:
    prefix = os.environ.get("CONDA_PREFIX")
    print(f"Environment: {os.environ.get('PIXI_ENVIRONMENT_NAME', 'default')}  prefix={prefix}")
    if not prefix:
        print("Not inside a conda/pixi environment. Use `pixi run check`.")
        return 2

    print("\nCommand-line tools")
    need("lhapdf-config", ["lhapdf-config", "--version"])
    need("lhapdf")
    need("fastjet-config", ["fastjet-config", "--version"])
    pc = need("pythia8-config", ["pythia8-config", "--version"])
    need("gfortran", ["gfortran", "--version"])
    need("gcc", ["gcc", "--version"])
    need("make", ["make", "--version"])
    need("DelphesLHEF")
    if not (shutil.which("DelphesHepMC2") or shutil.which("DelphesHepMC")):
        FAILS.append("neither DelphesHepMC2 nor DelphesHepMC on PATH")
        print("  FAIL  DelphesHepMC2/DelphesHepMC not found")
    else:
        print(f"  ok    {'DelphesHepMC2':18} {shutil.which('DelphesHepMC2') or shutil.which('DelphesHepMC')}")

    print("\nPythia8 build options (MadLAD's build enables hepmc2 + lhapdf6 + gzip)")
    if pc:
        cfg = run(["pythia8-config", "--config"]) + " " + run(["pythia8-config", "--libs"])
        for needle in ("hepmc2", "lhapdf6"):
            if needle in cfg.lower():
                print(f"  ok    {needle} mentioned in pythia8-config output")
            else:
                msg = f"pythia8-config output does not mention {needle}; check the build manually"
                WARNS.append(msg)
                print(f"  WARN  {msg}")
        print(f"  info  xmldoc: {run(['pythia8-config', '--xmldoc'])}")

    print("\nMG5")
    mg5 = os.environ.get("MG5_BIN") or shutil.which("mg5_aMC")
    cache = sorted(Path(os.environ.get("MADLAD_CACHE", "cache")).glob("mg5/MG5_aMC_v*/bin/mg5_aMC"))
    if cache:
        mg5 = str(cache[-1])
    if mg5:
        root = Path(mg5).resolve().parent.parent
        vfile = root / "VERSION"
        print(f"  ok    mg5_aMC            {mg5}")
        if vfile.exists():
            line = next((ln for ln in vfile.read_text().splitlines() if ln.startswith("version")), "")
            print(f"  info  {line}")
        for model in ("sm", "loop_sm-no_b_mass"):
            ok = (root / "models" / model).exists()
            print(f"  {'ok  ' if ok else 'WARN'}  model {model:18} {'bundled' if ok else 'not in MG5 tree (smoke test will need it)'}")
            if not ok:
                WARNS.append(f"model {model} not bundled in {root}/models")
    else:
        WARNS.append("no MG5 yet (default env: run `pixi run fetch-mg5`)")
        print("  WARN  no MG5 found yet (default env: `pixi run fetch-mg5`)")

    print("\nKey package provenance (from conda-meta)")
    for p in sorted(Path(prefix, "conda-meta").glob("*.json")):
        meta = json.loads(p.read_text())
        if meta["name"] in {"pythia8", "lhapdf", "fastjet", "delphes", "hepmc2", "mg5amcnlo",
                            "gfortran", "gcc", "python", "uproot"}:
            print(f"  {meta['name']:12} {meta['version']:10} {meta.get('build', ''):22} {meta.get('channel', '')}")

    print()
    for w in WARNS:
        print(f"WARN: {w}")
    for f in FAILS:
        print(f"FAIL: {f}")
    print("RESULT:", "FAIL" if FAILS else "ok")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
