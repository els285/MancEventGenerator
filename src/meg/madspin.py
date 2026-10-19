"""MadSpin: decay the (undecayed) tops, or any other particle, in the generated events.

MG5 runs MadSpin itself during `launch` when the switch `madspin=ON` is given; MEG's job is to write
Cards/madspin_card.dat beforehand and to find the right output afterwards. MadSpin does not
overwrite the undecayed run: it writes a second one next to it (`Events/run_01_decayed_1/`), and
any shower then runs on that. The LHE cross-section there includes the branching ratio of the
chosen decay channels."""
from __future__ import annotations

from pathlib import Path

from .config import MadSpinCfg
from .util import StageError


def _statement(keyword: str, text: str) -> str:
    """`decay t > ...` / `define l+ = ...`; tolerate users who already typed the keyword."""
    text = text.strip()
    return text if text.split(None, 1)[0] == keyword else f"{keyword} {text}"


def build_card(cfg: MadSpinCfg, seed: int) -> str:
    """The madspin_card.dat: options, definitions, then your decay statements, then `launch`."""
    lines = ["# written by MEG", f"set seed {seed}"]
    lines += [f"set {k} {v}" for k, v in cfg.options.items()]
    lines += [_statement("define", d) for d in cfg.define]
    lines += [_statement("decay", d) for d in cfg.decays]
    lines.append("launch")
    return "\n".join(lines) + "\n"


def write_card(process_dir: Path, cfg: MadSpinCfg, seed: int) -> Path:
    card = process_dir / "Cards" / "madspin_card.dat"
    card.write_text(build_card(cfg, seed))
    return card


def events_dir(process_dir: Path) -> Path:
    """The directory holding the decayed events (and their shower output)."""
    events = process_dir / "Events"
    found = sorted(events.glob("run_01_decayed_*"), key=lambda p: int(p.name.rsplit("_", 1)[1]))
    if not found:
        listing = sorted(p.name for p in events.glob("*")) if events.is_dir() else []
        raise StageError("MadSpin was switched on but MG5 produced no decayed events "
                         f"(expected Events/run_01_decayed_*; found {listing}). Look in "
                         "generate/launch.log for 'MadSpin' lines and in the decayed run's logs.")
    return found[-1]
