"""`meg doctor`: report whether this environment can run MEG, in a form that can be pasted into
an issue. Exit status is non-zero only for problems that make a run impossible."""
from __future__ import annotations

import shutil
import sys

from . import __version__, models, sysenv, toolchain
from .cache import cache_root, offline
from .manifest import packages
from .proc import capture


def run() -> int:
    env = sysenv.build_env()
    fails: list[str] = []
    warns: list[str] = []

    def need(tool: str, *, version: list[str] | None = None, required: bool = True, why: str = "") -> str | None:
        path = shutil.which(tool, path=env.get("PATH"))
        if path:
            ver = (capture(version, env).splitlines() or [""])[0] if version else ""
            print(f"  ok    {tool:16} {ver}  [{path}]")
            return path
        (fails if required else warns).append(f"{tool} not on PATH{(' (' + why + ')') if why else ''}")
        print(f"  {'FAIL' if required else 'WARN'}  {tool:16} not found{(' - ' + why) if why else ''}")
        return None

    prefix = sysenv.conda_prefix(env)
    print(f"MEG {__version__}  python {sys.version.split()[0]}  prefix={prefix}")
    if prefix is None:
        print("Not inside a conda/pixi environment. Use `pixi run meg doctor` or `pixi shell`.")
        return 2
    print(f"cache: {cache_root()}   offline: {offline()}")

    print("\nTools")
    need("mg5_aMC", version=None)
    need("lhapdf", version=["lhapdf", "--version"])
    need("fastjet-config", version=["fastjet-config", "--version"])
    need("pythia8-config", version=["pythia8-config", "--version"])
    need("gfortran", version=["gfortran", "--version"])
    need("make", version=["make", "--version"])
    need("git", version=["git", "--version"], required=False, why="needed to fetch UFO models from git")
    need("DelphesLHEF")
    need("DelphesHepMC2", required=False, why="needed to read Pythia8 HepMC")
    need("DelphesHepMC3", required=False, why="needed if Herwig writes HepMC3 'Asciiv3'")
    need("Herwig", version=["Herwig", "--version"], required=False, why="only for shower.kind = 'herwig7'")

    print("\nMG5")
    try:
        mg5 = toolchain.locate_mg5(env)
        print(f"  ok    {mg5.launcher}  version {mg5.version()}")
        cfg_ok = mg5.config.exists()
        print(f"  {'ok  ' if cfg_ok else 'WARN'}  config {mg5.config}")
        has_py8 = mg5.py8_interface.exists()
        print(f"  {'ok  ' if has_py8 else 'info'}  Pythia8 interface "
              f"{'installed' if has_py8 else 'not installed yet (`meg setup` installs it)'}")
        for model in ("sm", "loop_sm-no_b_mass"):
            ok = mg5.is_builtin_model(model)
            print(f"  {'ok  ' if ok else 'WARN'}  built-in model {model}")
            if not ok:
                warns.append(f"model {model} not in the MG5 tree")
    except Exception as e:  # noqa: BLE001
        fails.append(str(e))
        print(f"  FAIL  {e}")

    print("\nPlatform fixes applied to child processes")
    for k in ("LDFLAGS", "CXXFLAGS", "LD_LIBRARY_PATH", "LHAPDF_DATA_PATH"):
        print(f"  {k}={env.get(k, '<unset>')}")

    print("\nUFO models")
    print(f"  registry: {', '.join(sorted(models.registry())) or '(empty)'}")

    print("\nKey package versions (conda-meta)")
    for name, meta in sorted(packages(env).items()):
        print(f"  {name:12} {meta['version']:10} {meta.get('build') or '':22} {meta.get('channel') or ''}")

    print()
    for w in warns:
        print(f"WARN: {w}")
    for f in fails:
        print(f"FAIL: {f}")
    print("RESULT:", "FAIL" if fails else "ok")
    return 1 if fails else 0
