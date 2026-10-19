"""Everything a stage needs, in one object."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .plan import Plan
from .toolchain import MG5


@dataclass
class RunContext:
    plan: Plan
    run_dir: Path
    env: Mapping[str, str]
    mg5: MG5
    cores: int
    echo: str = "filtered"
    state: dict = field(default_factory=dict)          # outputs of finished stages, by stage name

    def stage_dir(self, name: str) -> Path:
        d = self.run_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.run_dir))

    def out(self, stage: str, key: str) -> Path | None:
        v = self.state.get(stage, {}).get("outputs", {}).get(key)
        return self.run_dir / v if v else None
