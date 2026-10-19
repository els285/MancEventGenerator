"""Platform fixes, applied to the environment of the programs we launch (never to our own).

Each one is a lesson from building MG5 against a conda-forge toolchain:
 * conda's compiler activation always defines LDFLAGS, which makes MG5 drop the C++ standard
   library from its link line (undefined std:: symbols in libpdf.a). Put it back.
 * MG5's bundled fjcore uses std::auto_ptr, removed in C++17; conda's clang defaults to C++17+.
 * Linux: MG5 copies the Pythia8 interface binary into run directories, which breaks its relative
   rpath, so the environment's lib directory must be on LD_LIBRARY_PATH. (macOS: see toolchain.py.)
"""
from __future__ import annotations

import os
import platform
import resource
from collections.abc import Mapping
from pathlib import Path

from .cache import cache_dir


def conda_prefix(env: Mapping[str, str] | None = None) -> Path | None:
    p = (env or os.environ).get("CONDA_PREFIX")
    return Path(p) if p else None


def is_macos() -> bool:
    return platform.system() == "Darwin"


def lhapdf_dirs(env: Mapping[str, str] | None = None) -> list[Path]:
    """PDF search path: MEG's cache first, then whatever the conda lhapdf package ships."""
    dirs = [cache_dir("lhapdf")]
    prefix = conda_prefix(env)
    if prefix:
        dirs.append(prefix / "share" / "LHAPDF")
    return dirs


def build_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    stdlib = "-lc++" if is_macos() else "-lstdc++"
    ldflags = env.get("LDFLAGS", "")
    if stdlib not in ldflags.split():
        env["LDFLAGS"] = f"{ldflags} {stdlib}".strip()
    cxxflags = env.get("CXXFLAGS", "")
    if "-std=" not in cxxflags:
        env["CXXFLAGS"] = f"{cxxflags} -std=c++14".strip()
    prefix = conda_prefix(env)
    if prefix and not is_macos():
        lib = str(prefix / "lib")
        parts = [p for p in env.get("LD_LIBRARY_PATH", "").split(":") if p]
        if lib not in parts:
            env["LD_LIBRARY_PATH"] = ":".join([lib, *parts])
    env["LHAPDF_DATA_PATH"] = ":".join(str(d) for d in lhapdf_dirs(env))
    return env


def raise_open_file_limit(target: int = 10240) -> None:
    """macOS defaults to 256 open files, which MG5's parallel runs exceed."""
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = target if hard == resource.RLIM_INFINITY else min(target, hard)
        if soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
    except (ValueError, OSError):
        pass


def default_cores() -> int:
    return os.cpu_count() or 2
