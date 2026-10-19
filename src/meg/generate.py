"""The MG5 stage: build the process, edit the cards, launch (with Pythia8 inside MG5 if asked)."""
from __future__ import annotations

import re
import shutil

from . import cards, madspin, pdf, proc
from .context import RunContext
from .models import FetchedModel
from .util import StageError, gunzip, log

PROC = "mg5_proc"
MG5_FAIL = re.compile(r"interrupted with error|^ERROR")


def header(ctx: RunContext) -> list[str]:
    # DEBUG so the log has what is needed to diagnose a failure; the console is filtered.
    lines = ["set stdout_level DEBUG", "set run_mode 2", f"set nb_core {ctx.cores}"]
    if not ctx.plan.uses_lhapdf:
        lines.append("set lhapdf_py3 None")          # builtin PDFs: switch LHAPDF off for MG5
    return lines


def import_line(ctx: RunContext, fetched: FetchedModel | None) -> str:
    m = ctx.plan.config.model
    target = str(fetched.path) if fetched else m.name
    return f"import model {target}" + (f"-{m.restriction}" if m.restriction else "")


def process_commands(ctx: RunContext, fetched: FetchedModel | None) -> list[str]:
    return [*header(ctx), import_line(ctx, fetched), *ctx.plan.config.process.extra_commands,
            f"generate {ctx.plan.mg5_process}", f"output {PROC} -f"]


def launch_commands(ctx: RunContext) -> list[str]:
    switches = []
    if ctx.plan.mg5_shower_switch is not None:
        switches.append(f"shower={ctx.plan.mg5_shower_switch}")
    if ctx.plan.madspin:
        switches.append("madspin=ON")
    if not switches:
        return [*header(ctx), f"launch {PROC} -f"]
    # No -f: answer MG5's two menus ourselves (switches, then cards). The cards were already
    # edited on disk, so both menus just get `done`.
    return [*header(ctx), f"launch {PROC}", *switches, "done", "done"]


def run_card_edits(ctx: RunContext) -> dict:
    c = ctx.plan.config
    g = c.generation
    seed = c.run.seed
    edits: dict = {"nevents": g.events, "iseed": seed}
    if ctx.plan.uses_lhapdf:
        edits["pdlabel"] = "'lhapdf'"
        edits["lhaid"] = pdf.lhaid(g.pdf, ctx.env)         # type: ignore[arg-type]
    if ctx.plan.order == "NLO":
        edits.update(nevt_job=g.events, req_acc=g.nlo_accuracy, parton_shower=ctx.plan.parton_shower,
                     reweight_scale=False, reweight_pdf=False)
    edits.update(g.run_card)                                # the user has the last word
    return edits


def run(ctx: RunContext, fetched: FetchedModel | None) -> dict[str, str | None]:
    d = ctx.stage_dir("generate")
    shutil.rmtree(d / PROC, ignore_errors=True)
    echo = ctx.echo

    (d / "proc.mg5").write_text("\n".join(process_commands(ctx, fetched)) + "\n")
    proc.run([ctx.mg5.launcher, "proc.mg5"], log_file=d / "proc.log", cwd=d, env=ctx.env,
             echo=echo, noise=proc.MG5_NOISE, fail_re=MG5_FAIL)
    if not (d / PROC / "Cards").is_dir():
        raise StageError(f"MG5 did not create the process directory {PROC} (see generate/proc.log)")

    if not ctx.plan.uses_lhapdf:
        mk = d / PROC / "Source" / "make_opts"
        if mk.exists() and re.search(r"^lhapdf=.", mk.read_text(), re.MULTILINE):
            log.warning("generation.pdf is builtin, but MG5 still enabled LHAPDF (Source/make_opts)")

    cfg = ctx.plan.config
    if cfg.model.params:
        cards.edit_param_card(d / PROC / "Cards" / "param_card.dat", cfg.model.params)
    used = cards.edit_run_card(d / PROC / "Cards" / "run_card.dat", run_card_edits(ctx))
    log.debug("run_card: %s", ", ".join(f"{k}={v}" for k, v in used.items()))

    if ctx.plan.madspin:
        card = madspin.write_card(d / PROC, cfg.madspin, cfg.run.seed)
        log.debug("madspin: %s", " | ".join(x for x in card.read_text().splitlines() if x.startswith("decay")))

    (d / "launch.mg5").write_text("\n".join(launch_commands(ctx)) + "\n")
    proc.run([ctx.mg5.launcher, "launch.mg5"], log_file=d / "launch.log", cwd=d, env=ctx.env,
             echo=echo, noise=proc.MG5_NOISE, fail_re=MG5_FAIL)

    run_dir = madspin.events_dir(d / PROC) if ctx.plan.madspin else d / PROC / "Events" / "run_01"
    lhe_gz = (sorted(run_dir.glob("unweighted_events.lhe*"))      # LO
              or sorted(run_dir.glob("*.lhe.gz")) or sorted(run_dir.glob("*.lhe")))   # NLO names vary
    if not lhe_gz:
        listing = sorted(p.name for p in run_dir.glob("*")) if run_dir.is_dir() else "(no run_01)"
        raise StageError(f"MG5 produced no LHE file in {run_dir}: {listing}")
    lhe = lhe_gz[0]
    lhe = gunzip(lhe, d / "events.lhe") if lhe.suffix == ".gz" else lhe

    hepmc = None
    if cfg.shower.kind == "pythia8":
        found = sorted(run_dir.glob("*.hepmc.gz")) or sorted(run_dir.glob("*.hepmc"))
        if not found:
            raise StageError("the Pythia8 shower did not run: no HepMC file in " + str(run_dir) +
                             ". Look in generate/launch.log for 'shower'/'pythia8' lines and for a "
                             "failed `install mg5amc_py8_interface` (run `meg setup`).")
        hepmc = found[0]
        if hepmc.suffix == ".gz":
            hepmc = gunzip(hepmc, d / "events.hepmc")
    return {"lhe": ctx.rel(lhe), "hepmc": ctx.rel(hepmc) if hepmc else None,
            "process_dir": ctx.rel(d / PROC)}
