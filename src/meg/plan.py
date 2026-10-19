"""Turn a validated Config into a concrete plan: what MG5 is told, what the shower step is, which
PDF sets are needed. Pure (no files, no network), so `meg plan` can show it and tests can check it."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .pdf import BUILTIN_LO_HERWIG_PDF, HERWIG_DEFAULT_SETS


@dataclass(frozen=True)
class Plan:
    config: Config
    mg5_process: str
    mg5_shower_switch: str | None      # value for MG5's `shower=` menu entry; None = launch with -f
    parton_shower: str | None          # NLO run_card parton_shower (which shower's counterterms)
    uses_lhapdf: bool                  # MG5 itself uses LHAPDF (else its built-in PDF)
    herwig_pdf: str | None             # PDF of the events, as Herwig must be told
    pdf_sets: tuple[str, ...]          # LHAPDF sets to have installed before running
    stages: tuple[str, ...]

    @property
    def order(self) -> str:
        return self.config.process.order

    @property
    def madspin(self) -> bool:
        return self.config.madspin.enable

    @property
    def external_shower(self) -> bool:
        return self.config.shower.kind == "herwig7"

    def describe(self) -> str:
        c = self.config
        lines = [
            f"run         {c.run.name}  (seed {c.run.seed}) -> {c.run.output_dir / c.run.name}",
            f"process     generate {self.mg5_process}   [{self.order}]",
            f"model       {c.model.name}" + (f"-{c.model.restriction}" if c.model.restriction else "")
            + (f"  params: {dict(c.model.params)}" if c.model.params else ""),
            f"events      {c.generation.events}   PDF: "
            + (c.generation.pdf if self.uses_lhapdf else "MG5 built-in (nn23lo1)"),
            *([f"madspin     {'; '.join(c.madspin.decays)}"] if c.madspin.enable else []),
            f"shower      {c.shower.kind}"
            + ("  (inside MG5)" if c.shower.kind == "pythia8" else
               "  (separate Herwig step)" if self.external_shower else ""),
            f"detector    {c.detector.kind}" + (f"  card: {c.detector.card}" if c.detector.kind == "delphes" else ""),
            f"PDF sets    {', '.join(self.pdf_sets) or '(none)'}",
            f"stages      {' -> '.join(self.stages)}",
        ]
        saved = [k for k in ("lhe", "hepmc") if getattr(c.output, k)]
        if saved:
            lines.append(f"keep        {', '.join(saved)}" + (" (gzip)" if c.output.compress else ""))
        if c.generation.run_card:
            lines.append(f"run_card    {dict(c.generation.run_card)}")
        return "\n".join(lines)


def build_plan(config: Config) -> Plan:
    order = config.process.order
    definition = config.process.definition.strip()
    if order == "NLO" and "[" not in definition:
        definition += " [QCD]"
    shower = config.shower.kind
    switch: str | None = None
    if shower == "pythia8":
        switch = "Pythia8" if order == "LO" else "PYTHIA8"
    elif order == "NLO":                      # herwig7: MG5 must not shower, the events carry
        switch = "OFF"                        # Herwig's counterterms (parton_shower) instead
    parton_shower = None
    if order == "NLO":
        parton_shower = "HERWIGPP" if shower == "herwig7" else "PYTHIA8"
    uses_lhapdf = config.generation.pdf != "builtin"
    herwig_pdf = None
    sets: list[str] = []
    if uses_lhapdf:
        sets.append(config.generation.pdf)       # type: ignore[arg-type]
    if shower == "herwig7":
        herwig_pdf = config.generation.pdf if uses_lhapdf else BUILTIN_LO_HERWIG_PDF
        sets += [herwig_pdf, *HERWIG_DEFAULT_SETS]
    stages = ["inputs", "generate"]
    if shower == "herwig7":
        stages.append("shower")
    if config.detector.kind == "delphes":
        stages.append("detector")
    if config.output.lhe or config.output.hepmc:
        stages.append("output")
    stages.append("manifest")
    return Plan(config, definition, switch, parton_shower, uses_lhapdf, herwig_pdf,
                tuple(dict.fromkeys(sets)), tuple(stages))
