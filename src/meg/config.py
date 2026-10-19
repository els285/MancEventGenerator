"""The run configuration: one TOML file, validated into typed models.

Unknown keys are errors (a typo must not silently run with a default). Defaults that depend on
other settings (model and PDF for LO vs NLO) are filled in once, here, so everything downstream
sees a fully resolved configuration.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .util import MegError, sha256_json

CardValue = bool | int | float | str


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunCfg(_Section):
    name: str = Field("meg_run", description="Run name; the output goes to <output_dir>/<name>/")
    seed: int = Field(1, ge=1, description="Random seed (MG5 iseed, Herwig seed)")
    output_dir: Path = Field(Path("results"), description="Parent directory for run directories")

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", v):
            raise ValueError("only letters, digits, '_', '.' and '-' are allowed")
        return v


class ModelCfg(_Section):
    name: str | None = Field(
        None, description="MG5 built-in model (sm, loop_sm-no_b_mass, ...), a model registered in "
        "models.toml, or the name to give a UFO given by git/url below. Default: sm (LO), "
        "loop_sm-no_b_mass (NLO)")
    restriction: str | None = Field(None, description="UFO restriction card, e.g. 'massless'")
    params: dict[str, float | int] = Field(
        default_factory=dict, description="param_card edits by name, e.g. {cHW = 0.1}, or by "
        "'BLOCK:id' e.g. {'MASS:6' = 172.5}. Unknown names are errors.")
    git: str | None = Field(None, description="Git URL of a UFO not in the registry (needs rev)")
    rev: str | None = Field(None, description="Full 40-character commit SHA (tags can move)")
    url: str | None = Field(None, description="Archive URL of a UFO (needs sha256)")
    sha256: str | None = Field(None, description="sha256 of the archive")
    subdir: str = Field("", description="Folder inside the source that holds the UFO")

    @model_validator(mode="after")
    def _source(self) -> ModelCfg:
        if self.git and self.url:
            raise ValueError("give either git or url, not both")
        if self.git and not self.rev:
            raise ValueError("'git' needs 'rev' (a full commit SHA)")
        if self.url and not self.sha256:
            raise ValueError("'url' needs 'sha256'")
        if (self.git or self.url) and not self.name:
            raise ValueError("an inline git/url model needs a 'name'")
        if self.rev and not re.fullmatch(r"[0-9a-f]{40}", self.rev):
            raise ValueError("'rev' must be a full 40-character lowercase commit SHA")
        return self


class ProcessCfg(_Section):
    definition: str = Field("p p > t t~", description="MG5 process, without 'generate'. For NLO "
                            "'[QCD]' is appended if you did not write brackets.")
    order: Literal["LO", "NLO"] = "LO"
    extra_commands: list[str] = Field(
        default_factory=list, description="Raw MG5 commands run after 'import model' and before "
        "'generate', e.g. [\"define p = p b b~\"]")


class GenerationCfg(_Section):
    events: int = Field(500, gt=0)
    pdf: str | None = Field(None, description="'builtin' (MG5's own, LO only) or an LHAPDF set "
                            "name. Default: builtin (LO), NNPDF30_nlo_as_0118 (NLO)")
    nlo_accuracy: float = Field(0.01, gt=0, description="NLO only: run_card req_acc")
    run_card: dict[str, CardValue] = Field(
        default_factory=dict, description="Extra run_card edits {key = value}. Unknown keys are "
        "errors. Strings are written verbatim, so quote them as MG5 expects, e.g. \"'lhapdf'\".")


class ShowerCfg(_Section):
    kind: Literal["pythia8", "herwig7", "none"] = "pythia8"


class DetectorCfg(_Section):
    kind: Literal["delphes", "none"] = "delphes"
    card: str = Field("ATLAS", description="Name of a packaged Delphes card, or a path to a .tcl")


class MadSpinCfg(_Section):
    enable: bool = Field(False, description="Decay particles in the generated events with MadSpin")
    decays: list[str] = Field(
        default_factory=list, description="MadSpin decay statements, written exactly as in a "
        "madspin_card but without the word 'decay', e.g. [\"t > w+ b, w+ > l+ vl\", "
        "\"t~ > w- b~, w- > l- vl~\"]. Required when enable = true.")
    define: list[str] = Field(default_factory=list, description="MadSpin 'define' lines (without "
                              "the word 'define'), e.g. [\"l+ = e+ mu+\", \"vl = ve vm\"]")
    options: dict[str, float | int | str] = Field(
        default_factory=dict, description="MadSpin 'set' options, e.g. {BW_cut = 15, "
        "spinmode = \"onshell\"}")

    @model_validator(mode="after")
    def _check(self) -> MadSpinCfg:
        if self.enable and not self.decays:
            raise ValueError("madspin.enable = true needs 'decays', e.g. "
                             "[\"t > w+ b, w+ > all all\", \"t~ > w- b~, w- > all all\"]")
        return self


class OutputCfg(_Section):
    lhe: bool = Field(False, description="Keep the LHE event file in <run>/output/")
    hepmc: bool = Field(False, description="Keep the showered HepMC file in <run>/output/ "
                        "(needs a shower)")
    compress: bool = Field(True, description="gzip the saved files (HepMC files are very large)")


MAX_SEED = 30081 * 30081          # the largest seed MG5 accepts
_SIZE = re.compile(r"\d+(\.\d+)?\s?(KB|MB|GB|TB|K|M|G|T)?", re.IGNORECASE)


class HTCondorCfg(_Section):
    """Site-specific HTCondor settings. Put these in ~/.config/meg/site.toml once, not in every config."""
    universe: str = Field("vanilla")
    requirements: str | None = Field(None, description="ClassAd 'requirements' expression")
    accounting_group: str | None = Field(None)
    extra: list[str] = Field(
        default_factory=list, description="Raw submit-file lines added before 'queue', e.g. "
        "[\"+JobFlavour = 'workday'\", \"MY.SingularityImage = 'x'\"]")


class ExecutionCfg(_Section):
    executor: Literal["local", "htcondor"] = Field(
        "local", description="Where `meg submit` runs the replicas ('meg generate' always runs one run here)")
    cores: int = Field(0, ge=0, description="Cores per run. 0 = all cores locally, 1 in a batch job")
    replicas: int = Field(1, ge=1, description="How many independent runs `meg submit` makes; "
                          "replica i has seed seed_start + i")
    seed_start: int | None = Field(None, ge=1, description="First replica's seed (default: run.seed)")
    memory: str = Field("4GB", description="Memory request per job")
    disk: str = Field("20GB", description="Scratch-disk request per job (20k events with HepMC need ~10 GB)")
    walltime: str | None = Field(None, description="HH:MM:SS limit per job (sites differ in how they honour it)")
    max_running: int | None = Field(None, ge=1, description="At most this many jobs in the queue/running at once")
    retrieve: list[Literal["delphes", "lhe", "hepmc"]] | Literal["all"] | None = Field(
        None, description="What to bring back from every job: a list of delphes / lhe / hepmc, or "
        "\"all\" (the whole run directory as one archive). Default: [\"delphes\"], or [\"lhe\"] without a "
        "detector. The manifest and logs always come back.")
    campaign_dir: Path = Field(Path("campaigns"), description="Parent directory for campaign directories")
    output_dir: Path | None = Field(
        None, description="Absolute path (e.g. on EOS, visible from the worker nodes) that the jobs write their "
        "results to, into <output_dir>/<campaign id>/. Only the small status files then travel back to the "
        "campaign directory, which can stay on a small disk. Default: results come back into the campaign "
        "directory.")
    htcondor: HTCondorCfg = Field(default_factory=HTCondorCfg)

    @field_validator("memory", "disk")
    @classmethod
    def _size(cls, v: str) -> str:
        if not _SIZE.fullmatch(v.strip()):
            raise ValueError("write a size like 4GB, 500MB or 2048")
        return v.strip()

    @field_validator("output_dir")
    @classmethod
    def _output_dir(cls, v: Path | None) -> Path | None:
        if v is not None and not v.is_absolute():
            raise ValueError("write output_dir as an absolute path, e.g. /eos/user/e/ethan/meg "
                             "(a job on a worker node cannot resolve a relative one)")
        return v

    @field_validator("walltime")
    @classmethod
    def _walltime(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d+:[0-5]\d:[0-5]\d", v):
            raise ValueError("write walltime as HH:MM:SS, e.g. 12:00:00")
        return v

    def walltime_seconds(self) -> int | None:
        if self.walltime is None:
            return None
        h, m, sec = (int(x) for x in self.walltime.split(":"))
        return h * 3600 + m * 60 + sec


class Config(_Section):
    run: RunCfg = Field(default_factory=RunCfg)
    model: ModelCfg = Field(default_factory=ModelCfg)
    process: ProcessCfg = Field(default_factory=ProcessCfg)
    generation: GenerationCfg = Field(default_factory=GenerationCfg)
    madspin: MadSpinCfg = Field(default_factory=MadSpinCfg)
    shower: ShowerCfg = Field(default_factory=ShowerCfg)
    detector: DetectorCfg = Field(default_factory=DetectorCfg)
    output: OutputCfg = Field(default_factory=OutputCfg)
    execution: ExecutionCfg = Field(default_factory=ExecutionCfg)

    @model_validator(mode="after")
    def _resolve(self) -> Config:
        nlo = self.process.order == "NLO"
        if self.model.name is None:
            self.model.name = "loop_sm-no_b_mass" if nlo else "sm"
        if self.generation.pdf is None:
            self.generation.pdf = "NNPDF30_nlo_as_0118" if nlo else "builtin"
        if nlo and self.generation.pdf == "builtin":
            raise ValueError("generation.pdf: NLO needs an LHAPDF set (e.g. NNPDF30_nlo_as_0118), "
                             "not 'builtin'")
        if nlo and self.shower.kind == "none":
            raise ValueError("shower.kind: NLO (MC@NLO) events are only meaningful with a shower")
        if self.output.hepmc and self.shower.kind == "none":
            raise ValueError("output.hepmc: there is no HepMC file when shower.kind = \"none\"")
        if self.detector.kind == "delphes" and not self.detector.card:
            raise ValueError("detector.card must not be empty")
        ex = self.execution
        if ex.retrieve is None:
            ex.retrieve = ["delphes"] if self.detector.kind == "delphes" else ["lhe"]
        wanted = ex.retrieve if isinstance(ex.retrieve, list) else []
        if "delphes" in wanted and self.detector.kind != "delphes":
            raise ValueError("execution.retrieve: 'delphes' asked for, but detector.kind is not \"delphes\"")
        if "hepmc" in wanted and self.shower.kind == "none":
            raise ValueError("execution.retrieve: 'hepmc' asked for, but shower.kind is \"none\"")
        last = self.first_seed() + ex.replicas - 1
        if last > MAX_SEED:
            raise ValueError(f"seeds run up to {last}, but MG5 accepts at most {MAX_SEED}")
        return self

    def first_seed(self) -> int:
        return self.execution.seed_start or self.run.seed

    def seeds(self) -> list[int]:
        return list(range(self.first_seed(), self.first_seed() + self.execution.replicas))

    def fingerprint(self) -> str:
        """Identity of one run's physics: everything except where the output goes and how it is executed."""
        d = self.model_dump(mode="json")
        d["run"].pop("output_dir")
        d["run"].pop("name")
        d.pop("execution")
        return sha256_json(d)

    def process_id(self) -> str:
        """Short identity of the physics shared by all replicas: like fingerprint(), but without the
        seed and without the choice of what to keep. Two campaigns with the same name and settings
        get the same id."""
        d = self.model_dump(mode="json")
        for k in ("output_dir", "name", "seed"):
            d["run"].pop(k)
        d.pop("execution")
        d.pop("output")
        return sha256_json(d)[:8]


# --------------------------------------------------------------------------- loading

def _set_dotted(d: dict, dotted: str, value: Any) -> None:
    *parents, last = dotted.split(".")
    for p in parents:
        d = d.setdefault(p, {})
        if not isinstance(d, dict):
            raise MegError(f"--set {dotted}: '{p}' is not a table")
    d[last] = value


def _parse_value(text: str) -> Any:
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text          # bare words like herwig7 are strings


def _format_errors(e: ValidationError, source: str) -> str:
    lines = [f"Invalid configuration ({source}):"]
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "(top level)"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def site_path() -> Path:
    env = os.environ.get("MEG_SITE")
    return Path(env).expanduser() if env else Path.home() / ".config" / "meg" / "site.toml"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_site() -> dict:
    """Per-machine defaults for the [execution] table (queue, accounting group, ...). Optional."""
    p = site_path()
    if not p.is_file():
        return {}
    try:
        data = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as e:
        raise MegError(f"{p}: not valid TOML: {e}") from e
    extra = set(data) - {"execution"}
    if extra:
        raise MegError(f"{p}: only an [execution] table is allowed here, found: {', '.join(sorted(extra))}")
    return data


def load_config(path: str | Path | None = None, overrides: list[str] | None = None) -> Config:
    """Read a TOML file (or start from defaults) and apply `--set a.b=c` style overrides.
    Machine-wide [execution] defaults from the site file sit underneath the project's own settings."""
    data: dict[str, Any] = {}
    source = "defaults"
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise MegError(f"config file not found: {p}")
        try:
            data = tomllib.loads(p.read_text())
        except tomllib.TOMLDecodeError as e:
            raise MegError(f"{p}: not valid TOML: {e}") from e
        source = str(p)
    site = load_site()
    if site:
        data["execution"] = _merge(site["execution"], data.get("execution", {}))
    for item in overrides or []:
        if "=" not in item:
            raise MegError(f"override {item!r} must look like section.key=value")
        key, _, value = item.partition("=")
        _set_dotted(data, key.strip(), _parse_value(value.strip()))
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise MegError(_format_errors(e, source)) from None


def json_schema() -> str:
    return json.dumps(Config.model_json_schema(), indent=2)
