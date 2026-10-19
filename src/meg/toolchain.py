"""Find MG5 and make it use the environment's Pythia8 / LHAPDF / FastJet / Delphes.

This replaces the spike's setup_mg5.sh, set_mg5_config.py and fix_rpath.sh. Everything here is
idempotent: calling it on an already-configured MG5 changes nothing.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .cache import offline
from .sysenv import conda_prefix, is_macos
from .util import MegError, log


@dataclass
class MG5:
    launcher: Path
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "input" / "mg5_configuration.txt"

    @property
    def py8_interface(self) -> Path:
        return self.root / "HEPTools" / "MG5aMC_PY8_interface" / "MG5aMC_PY8_interface"

    def builtin_models(self) -> set[str]:
        d = self.root / "models"
        return {p.name for p in d.iterdir() if p.is_dir()} if d.is_dir() else set()

    @property
    def ninja_lib_dirs(self) -> list[Path]:
        return [self.root / "HEPTools" / "ninja" / "lib", self.root / "HEPTools" / "lib"]

    def has_ninja(self) -> bool:
        return any(d.is_dir() and any(d.glob("libninja.*")) for d in self.ninja_lib_dirs)

    def is_builtin_model(self, name: str) -> bool:
        """`sm`, or MG5's `<model>-<restriction>` form such as `loop_sm-no_b_mass` (the restriction is
        the file `models/<model>/restrict_<restriction>.dat`, not a directory of its own)."""
        base, _, restriction = name.partition("-")
        if base not in self.builtin_models():
            return False
        return not restriction or (self.root / "models" / base / f"restrict_{restriction}.dat").is_file()

    def version(self) -> str:
        v = self.root / "VERSION"
        if v.exists():
            for line in v.read_text().splitlines():
                if line.startswith("version"):
                    return line.split("=", 1)[1].strip()
        return "unknown"


def locate_mg5(env: Mapping[str, str]) -> MG5:
    explicit = env.get("MG5_BIN")
    found = explicit or shutil.which("mg5_aMC", path=env.get("PATH"))
    if not found:
        raise MegError("mg5_aMC not found. Run inside the MEG environment (`pixi run meg ...` or "
                       "`pixi shell`), or set MG5_BIN. Check with `meg doctor`.")
    launcher = Path(found).resolve()
    return MG5(launcher=launcher, root=launcher.parent.parent)


def set_config_options(path: Path, wanted: dict[str, str], write: bool = True) -> bool:
    """Set `key = value` in mg5_configuration.txt (replacing a commented-out line, or appending).
    Returns True if the file changed (or, with write=False, would change)."""
    lines = path.read_text().splitlines()
    original = list(lines)
    done: set[str] = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*#?\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in wanted and m.group(1) not in done:
            lines[i] = f"{m.group(1)} = {wanted[m.group(1)]}"
            done.add(m.group(1))
    for key, val in wanted.items():
        if key not in done:
            lines.append(f"{key} = {val}")
    if lines == original:
        return False
    if write:
        path.write_text("\n".join(lines) + "\n")
    return True


def configure_mg5(mg5: MG5, env: Mapping[str, str]) -> None:
    prefix = conda_prefix(env)
    if prefix is None:
        raise MegError("CONDA_PREFIX is not set: run inside `pixi run` / `pixi shell`")
    opts = {
        "pythia8_path": str(prefix),
        "lhapdf_py3": str(prefix / "bin" / "lhapdf-config"),
        "delphes_path": str(prefix),
        "automatic_html_opening": "False",
        "auto_update": "0",
    }
    if (prefix / "bin" / "fastjet-config").exists():
        opts["fastjet"] = str(prefix / "bin" / "fastjet-config")
    cfg = mg5.config
    if cfg.exists() and not set_config_options(cfg, opts, write=False):
        return          # already configured: nothing to write (batch nodes may see a read-only tree)
    if cfg.exists() and _writable(cfg):
        if set_config_options(cfg, opts):
            log.info("configured %s", cfg)
        return
    # No writable tree (e.g. a read-only package layout): let MG5 save per-user options instead.
    log.warning("%s is not writable; saving MG5 options to ~/.mg5 instead", cfg)
    with tempfile.NamedTemporaryFile("w", suffix=".mg5", delete=False) as f:
        f.write("".join(f"set {k} {v}\n" for k, v in opts.items()) + "save options\n")
    try:
        subprocess.run([str(mg5.launcher), f.name], env=dict(env), check=True,
                       capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise MegError(f"could not save MG5 options:\n{e.stdout[-1500:]}{e.stderr[-1500:]}") from e
    finally:
        Path(f.name).unlink(missing_ok=True)


def _writable(p: Path) -> bool:
    import os
    return os.access(p, os.W_OK)


def ensure_py8_interface(mg5: MG5, env: Mapping[str, str]) -> None:
    """Install MG5's Pythia8 interface once (needs network), then make its binary relocatable."""
    if not mg5.py8_interface.exists():
        if offline():
            raise MegError("MG5's Pythia8 interface is not installed and MEG_OFFLINE=1. Run "
                           "`meg setup` once on a machine with network access.")
        log.info("installing mg5amc_py8_interface (one time, needs network access to Launchpad)")
        with tempfile.NamedTemporaryFile("w", suffix=".mg5", delete=False) as f:
            f.write("install mg5amc_py8_interface\n")
        try:
            r = subprocess.run([str(mg5.launcher), f.name], env=dict(env), capture_output=True,
                               text=True)
        finally:
            Path(f.name).unlink(missing_ok=True)
        if r.returncode != 0 or not mg5.py8_interface.exists():
            raise MegError("installing mg5amc_py8_interface failed:\n" + (r.stdout + r.stderr)[-2500:])
    fix_rpath_macos(mg5, env)


def ensure_loop_tools(mg5: MG5, env: Mapping[str, str]) -> None:
    """NLO needs a loop-reduction library. MG5 builds Ninja from source the first time a loop process
    is generated, and starts again from scratch every time that build did not finish. Do it once, here,
    with a log and progress lines, so an interrupted build is not repeated silently on every run."""
    if mg5.has_ninja():
        return
    if offline():
        raise MegError("NLO needs MG5's Ninja library, which is not installed, and MEG_OFFLINE=1. "
                       "Run `meg setup` once on a machine with network access.")
    from . import proc
    from .cache import cache_dir

    log.info("installing Ninja for NLO loops (one time; compiles from source). "
             "Do not interrupt it - an unfinished build is started again from scratch.")
    with tempfile.NamedTemporaryFile("w", suffix=".mg5", delete=False) as f:
        f.write("install ninja\n")
    log_file = cache_dir("logs") / "install_ninja.log"
    try:
        proc.run([mg5.launcher, f.name], log_file=log_file, cwd=Path(tempfile.gettempdir()), env=env,
                 echo="none", heartbeat=60.0)
    finally:
        Path(f.name).unlink(missing_ok=True)
    if not mg5.has_ninja():
        raise MegError(f"installing Ninja did not produce a library. See {log_file} and "
                       f"{mg5.root / 'HEPTools' / 'ninja' / 'ninja_install.log'}")
    log.info("Ninja installed")


def _find_tool(name: str) -> str | None:
    for t in (name, f"arm64-apple-darwin20.0.0-{name}", f"/usr/bin/{name}"):
        found = shutil.which(t)
        if found:
            return found
    return None


def fix_rpath_macos(mg5: MG5, env: Mapping[str, str]) -> None:
    """MG5 copies the Pythia8 interface binary into every run directory. The conda-packaged binary
    finds libpythia8 through a *relative* rpath, so each copy aborts with 'Library not loaded:
    @rpath/libpythia8.dylib'. Add an absolute rpath (and re-sign: arm64 macOS kills binaries whose
    signature no longer matches). SIP strips DYLD_* variables, so an env var cannot do this."""
    if not is_macos():
        return
    prefix = conda_prefix(env)
    binary = mg5.py8_interface
    if prefix is None or not binary.exists():
        return
    want = str(prefix / "lib")
    otool = _find_tool("otool")
    if otool:
        out = subprocess.run([otool, "-l", str(binary)], capture_output=True, text=True).stdout
        if re.search(rf"path {re.escape(want)} ", out):
            return
    int_tool = _find_tool("install_name_tool")
    if not int_tool:
        raise MegError("install_name_tool not found; install the Xcode command line tools: "
                       "xcode-select --install")
    r = subprocess.run([int_tool, "-add_rpath", want, str(binary)], capture_output=True, text=True)
    if r.returncode != 0 and "would duplicate" not in (r.stdout + r.stderr):
        raise MegError(f"install_name_tool failed: {r.stdout}{r.stderr}")
    codesign = _find_tool("codesign")
    if not codesign:
        raise MegError("codesign not found (needed after editing a binary on Apple Silicon)")
    if subprocess.run([codesign, "-f", "-s", "-", str(binary)], capture_output=True).returncode:
        raise MegError(f"codesign failed for {binary}")
    log.info("patched and re-signed %s (rpath %s)", binary.name, want)
