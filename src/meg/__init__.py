"""MEG: a MadGraph Event Generator pipeline (MG5_aMC + Pythia8/Herwig7 + Delphes) driven by TOML.

    import meg
    cfg = meg.load_config("run.toml", overrides=["generation.events=1000"])
    result = meg.generate(cfg)
    result.delphes_root, result.cross_section_pb
"""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("meg")
except PackageNotFoundError:        # running from a source tree without installation
    __version__ = "0.1.0"

from .config import Config, load_config
from .plan import Plan, build_plan
from .runner import RunResult, run
from .util import MegError, StageError

generate = run          # same function; `meg generate` on the command line, meg.generate(cfg) in Python

__all__ = [
    "Config",
    "MegError",
    "Plan",
    "RunResult",
    "StageError",
    "__version__",
    "build_plan",
    "generate",
    "load_config",
    "run",
]
