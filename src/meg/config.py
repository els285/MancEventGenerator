"""The run configuration: one TOML file, validated into typed models.

Unknown keys are errors (a typo must not silently run with a default). Defaults that depend on
other settings (model and PDF for LO vs NLO) are filled in once, here, so everything downstream
sees a fully resolved configuration.
"""
from __future__ import annotations

import json
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


class ExecutionCfg(_Section):
    executor: Literal["local"] = Field("local", description="Only 'local' exists in v0.1")
    cores: int = Field(0, ge=0, description="0 = all cores")


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
        return self

    def fingerprint(self) -> str:
        """Identity of the physics: everything except where the output goes."""
        d = self.model_dump(mode="json")
        d["run"].pop("output_dir")
        d["run"].pop("name")
        return sha256_json(d)


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


def load_config(path: str | Path | None = None, overrides: list[str] | None = None) -> Config:
    """Read a TOML file (or start from defaults) and apply `--set a.b=c` style overrides."""
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
