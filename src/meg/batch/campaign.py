"""The campaign directory: identity, layout and the state every command reads.

    <campaign_dir>/<name>-<processid>/
        campaign.json   id, seeds, retrieve, submissions (cluster ids), versions
        config.json     the frozen base configuration (paths made absolute)
        seeds.txt       one "seed,tag" line per replica (HTCondor `queue ... from`)
        env.sh job.sh submit.sub
        replicas/s0007/ job.out job.err outbox/   one directory per replica
        outputs/        the unique-named results, filled by `meg collect`
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..util import MegError

KINDS = {                      # kind -> file suffix; every file is named <campaign>_<tag>.<suffix>
    "delphes": "delphes.root",
    "lhe": "lhe.gz",
    "hepmc": "hepmc.gz",
    "run": "run.tar.gz",
    "logs": "logs.tar.gz",
    "manifest": "manifest.json",
    "status": "status.json",
}


def tag(seed: int) -> str:
    return f"s{seed:04d}"


def campaign_id(cfg: Config) -> str:
    return f"{cfg.run.name}-{cfg.process_id()}"


def unique_name(cid: str, seed: int, kind: str) -> str:
    return f"{cid}_{tag(seed)}.{KINDS[kind]}"


@dataclass
class Campaign:
    dir: Path
    meta: dict

    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def seeds(self) -> list[int]:
        return list(self.meta["seeds"])

    @property
    def config_path(self) -> Path:
        return self.dir / "config.json"

    @property
    def meta_path(self) -> Path:
        return self.dir / "campaign.json"

    @property
    def outputs(self) -> Path:
        return self.dir / "outputs"

    def config(self) -> Config:
        return Config.model_validate_json(self.config_path.read_text())

    def replica_dir(self, seed: int) -> Path:
        return self.dir / "replicas" / tag(seed)

    def outbox(self, seed: int) -> Path:
        return self.replica_dir(seed) / "outbox"

    def read_status(self, seed: int) -> dict | None:
        p = self.outbox(seed) / "status.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None

    def save(self) -> None:
        self.meta_path.write_text(json.dumps(self.meta, indent=2) + "\n")

    @classmethod
    def load(cls, where: str | Path) -> Campaign:
        d = Path(where).expanduser()
        if not (d / "campaign.json").is_file():
            alt = Path("campaigns") / str(where)
            if (alt / "campaign.json").is_file():
                d = alt
            else:
                raise MegError(f"{where} is not a campaign directory (no campaign.json). "
                               "Give the path printed by `meg submit`.")
        return cls(d.resolve(), json.loads((d / "campaign.json").read_text()))
