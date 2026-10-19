"""Run a plan: prepare the toolchain, fetch inputs, then run the stages, skipping any whose inputs
are unchanged since the last run in the same directory."""
from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import (
    __version__,
    delphes,
    diagnostics,
    generate,
    herwig,
    manifest,
    models,
    outputs,
    pdf,
    sysenv,
    toolchain,
)
from .config import Config
from .context import RunContext
from .plan import build_plan
from .util import MegError, StageError, log, sha256_file, sha256_json

STATE_DIR = ".meg"


@dataclass
class RunResult:
    run_dir: Path
    manifest_path: Path
    manifest: dict

    @property
    def cross_section_pb(self) -> float | None:
        return self.manifest.get("lhe", {}).get("xsec_pb")

    @property
    def lhe(self) -> Path | None:
        f = self.manifest.get("lhe", {}).get("file")
        return self._find(f)

    @property
    def saved_lhe(self) -> Path | None:
        f = self.manifest.get("saved", {}).get("lhe")
        return self.run_dir / f if f else None

    @property
    def saved_hepmc(self) -> Path | None:
        f = self.manifest.get("saved", {}).get("hepmc")
        return self.run_dir / f if f else None

    @property
    def delphes_root(self) -> Path | None:
        f = self.manifest.get("delphes", {}).get("file")
        return self._find(f)

    def _find(self, name: str | None) -> Path | None:
        if not name:
            return None
        hits = sorted(self.run_dir.rglob(name))
        return hits[0] if hits else None


def _prepare_run_dir(cfg: Config, force: bool) -> Path:
    run_dir = (cfg.run.output_dir / cfg.run.name).resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        if not (run_dir / STATE_DIR).is_dir():
            raise MegError(f"{run_dir} exists and is not a MEG run directory; refusing to use it. "
                           "Choose another run.name or run.output_dir.")
        if force:
            shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / STATE_DIR).mkdir(exist_ok=True)
    return run_dir


def _stage(ctx: RunContext, name: str, inputs_hash: str, fn: Callable[[], dict],
           timings: dict) -> str:
    """Run stage `name` unless a previous run recorded the same inputs hash and its outputs exist."""
    rec_path = ctx.run_dir / STATE_DIR / f"{name}.json"
    if rec_path.is_file():
        rec = json.loads(rec_path.read_text())
        outs = [v for v in rec.get("outputs", {}).values() if v]
        if rec.get("hash") == inputs_hash and all((ctx.run_dir / o).exists() for o in outs):
            log.info("stage %-9s up to date, skipping", name)
            ctx.state[name] = rec
            timings[name] = "cached"
            return inputs_hash
        rec_path.unlink()
    sdir = ctx.run_dir / name
    shutil.rmtree(sdir, ignore_errors=True)       # no stale files from an earlier attempt
    log.info("stage %-9s running", name)
    t0 = time.time()
    try:
        outputs = fn()
    except StageError as e:
        e.diag = diagnostics.collect(ctx, name, str(e))
        raise
    secs = round(time.time() - t0, 1)
    rec = {"hash": inputs_hash, "outputs": outputs, "seconds": secs}
    rec_path.write_text(json.dumps(rec, indent=2) + "\n")
    ctx.state[name] = rec
    timings[name] = secs
    took = f"{int(secs // 60)}m{int(secs % 60):02d}s" if secs >= 60 else f"{secs:.0f}s"
    log.info("stage %-9s done in %s", name, took)
    return inputs_hash


def _resolve_model(config: Config, mg5: toolchain.MG5) -> models.FetchedModel | None:
    """Built-in MG5 models are used as they are; anything else is fetched and pinned."""
    m = config.model
    inline = {k: getattr(m, k) for k in ("git", "rev", "url", "sha256", "subdir") if getattr(m, k)}
    if not inline and mg5.is_builtin_model(m.name):
        return None
    fetched = models.fetch(m.name, inline or None, m.restriction)        # type: ignore[arg-type]
    log.warning("model %s is Python code that MG5 will execute; only use sources you trust",
                fetched.name)
    return fetched


def _toolchain_ready(config: Config, env, mg5: toolchain.MG5) -> None:
    toolchain.configure_mg5(mg5, env)
    if config.shower.kind == "pythia8":
        toolchain.ensure_py8_interface(mg5, env)
    if config.process.order == "NLO":
        toolchain.ensure_loop_tools(mg5, env)


def prepare(config: Config) -> None:
    """Do every one-time, possibly networked step a run needs (MG5 configuration, Pythia8 interface,
    Ninja, UFO model, PDF sets) without starting a run. `meg submit` calls this on the submit host so
    that the jobs can run offline and never race each other to install things."""
    env = sysenv.build_env()
    plan = build_plan(config)
    mg5 = toolchain.locate_mg5(env)
    _toolchain_ready(config, env, mg5)
    _resolve_model(config, mg5)
    for s in plan.pdf_sets:
        pdf.ensure(s, env)


def build_process(config: Config, out_dir: Path, *, echo: str = "none") -> Path:
    """Build only the MG5 process directory (model import, diagrams, `output`) under `out_dir` and return
    it. This is the seed-independent, expensive-to-repeat part of a run; `meg _prepare` packs it so a
    campaign's replicas can start from it."""
    env = sysenv.build_env()
    sysenv.raise_open_file_limit()
    plan = build_plan(config)
    mg5 = toolchain.locate_mg5(env)
    _toolchain_ready(config, env, mg5)
    fetched = _resolve_model(config, mg5)
    for s in plan.pdf_sets:
        pdf.ensure(s, env)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = RunContext(plan=plan, run_dir=out_dir, env=env, mg5=mg5,
                     cores=config.execution.cores or sysenv.default_cores(), echo=echo)
    return generate.build_process(ctx, fetched, ctx.stage_dir("generate"))


def run(config: Config, *, echo: str = "none", force: bool = False, prebuilt: Path | None = None) -> RunResult:
    """Run the whole pipeline for `config`. `echo`: none | filtered | all (how much of the tools' own
    output is shown; the log files always have everything). `force` discards an earlier run in the same directory.
    `prebuilt` is a process archive from `meg _prepare`: the run then skips building the MG5 process."""
    env = sysenv.build_env()
    sysenv.raise_open_file_limit()
    plan = build_plan(config)
    mg5 = toolchain.locate_mg5(env)
    cores = config.execution.cores or sysenv.default_cores()
    run_dir = _prepare_run_dir(config, force)
    ctx = RunContext(plan=plan, run_dir=run_dir, env=env, mg5=mg5, cores=cores, echo=echo)
    (run_dir / "config.resolved.json").write_text(config.model_dump_json(indent=2) + "\n")
    for line in plan.describe().splitlines():
        log.info(line)

    timings: dict = {}
    _toolchain_ready(config, env, mg5)

    # inputs: always checked, cheap when cached
    t0 = time.time()
    fetched = _resolve_model(config, mg5)
    for s in plan.pdf_sets:
        pdf.ensure(s, env)
    timings["inputs"] = round(time.time() - t0, 1)

    c = config
    gen_hash = sha256_json({
        "v": __version__, "mg5": mg5.version(), "model": c.model.model_dump(mode="json"),
        "model_tree": fetched.tree_sha256 if fetched else None,
        "process": c.process.model_dump(mode="json"),
        "madspin": c.madspin.model_dump(mode="json"), "gen": c.generation.model_dump(mode="json"),
        "seed": c.run.seed, "switch": plan.mg5_shower_switch, "parton_shower": plan.parton_shower,
        "py8": c.shower.kind == "pythia8", "prebuilt": prebuilt is not None})
    _stage(ctx, "generate", gen_hash, lambda: generate.run(ctx, fetched, prebuilt), timings)
    lhe = ctx.out("generate", "lhe")
    events = ctx.out("generate", "hepmc") or lhe
    upstream = gen_hash

    if c.shower.kind == "herwig7":
        sh_hash = sha256_json({"up": gen_hash, "seed": c.run.seed, "n": c.generation.events,
                               "pdf": plan.herwig_pdf, "order": plan.order})

        def do_shower() -> dict:
            sdir = ctx.stage_dir("shower")
            hep = herwig.run(plan.order, lhe, plan.herwig_pdf, c.generation.events,     # type: ignore[arg-type]
                             c.run.seed, sdir, env, echo)
            return {"hepmc": ctx.rel(hep)}

        upstream = _stage(ctx, "shower", sh_hash, do_shower, timings)
        events = ctx.out("shower", "hepmc")

    if c.detector.kind == "delphes":
        card = delphes.resolve_card(c.detector.card)
        det_hash = sha256_json({"up": upstream, "card": sha256_file(card)})

        def do_detector() -> dict:
            sdir = ctx.stage_dir("detector")
            delphes.run(events, card, sdir / "delphes.root", sdir, env, echo)    # type: ignore[arg-type]
            return {"root": ctx.rel(sdir / "delphes.root")}

        upstream = _stage(ctx, "detector", det_hash, do_detector, timings)

    if "output" in plan.stages:
        out_hash = sha256_json({"up": upstream, "out": c.output.model_dump(mode="json"), "name": c.run.name,
                                "events": [str(events), str(lhe)]})
        _stage(ctx, "output", out_hash, lambda: outputs.run(ctx), timings)

    m = manifest.build(ctx, fetched, timings)
    path = manifest.write(ctx, m)
    problems = manifest.check(m)
    if problems:
        raise StageError("empty or inconsistent result: " + "; ".join(problems) +
                         f" (manifest: {path})")
    return RunResult(run_dir, path, m)
