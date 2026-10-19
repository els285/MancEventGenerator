"""The `meg` command line. Thin: every command is a few lines over the library."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from . import __version__
from .config import json_schema, load_config
from .plan import build_plan
from .util import MegError, StageError

EXAMPLE = """\
# MEG run configuration. Every key is optional; these are the defaults for a LO ttbar run.
# See `meg schema` for the full list with descriptions.

[run]
name = "ttbar_lo"
seed = 1
output_dir = "results"

[process]
definition = "p p > t t~"      # for NLO set order = "NLO" ([QCD] is added for you)
order = "LO"                   # "LO" | "NLO"

[model]
# name = "sm"                  # default: sm (LO) / loop_sm-no_b_mass (NLO)

[generation]
events = 500
# pdf = "builtin"              # LO default. Or an LHAPDF set, e.g. "NNPDF30_nlo_as_0118"

[shower]
kind = "pythia8"               # "pythia8" | "herwig7" | "none"

[detector]
kind = "delphes"               # "delphes" | "none"
card = "ATLAS"                 # packaged card name, or a path to your own .tcl

[output]
lhe = false                    # true: keep the LHE file in <run>/output/
hepmc = false                  # true: keep the showered HepMC file (large; needs a shower)
compress = true                # gzip the kept files
"""


def _on_sigterm(signum, frame) -> None:
    raise KeyboardInterrupt


def _setup_logging() -> None:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("\033[1;34m[meg]\033[0m %(message)s" if sys.stderr.isatty()
                                     else "[meg] %(message)s"))
    root = logging.getLogger("meg")
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)


def _add_config_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("config", nargs="?", help="TOML configuration file (default: built-in defaults)")
    p.add_argument("--set", "-s", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
                   help="override a setting, e.g. --set generation.events=2000 --set shower.kind=herwig7")


def _cmd_generate(a: argparse.Namespace) -> int:
    from .runner import run
    cfg = load_config(a.config, a.overrides)
    echo = "none" if a.quiet else "all" if a.verbose else "filtered"
    res = run(cfg, echo=echo, force=a.force)
    print()
    print(f"run directory : {res.run_dir}")
    if res.cross_section_pb is not None:
        xs = res.manifest["lhe"]
        print(f"cross-section : {xs['xsec_pb']:.6g} +- {xs['xsec_err_pb']:.2g} pb  ({xs['events']} events)")
    if res.delphes_root:
        d = res.manifest["delphes"]
        print(f"Delphes ROOT  : {res.delphes_root}  ({d['entries']} entries)")
    for label, path in (("LHE", res.saved_lhe), ("HepMC", res.saved_hepmc)):
        if path:
            print(f"{label:<13} : {path}")
    print(f"manifest      : {res.manifest_path}")
    return 0


def _cmd_plan(a: argparse.Namespace) -> int:
    print(build_plan(load_config(a.config, a.overrides)).describe())
    return 0


def _cmd_doctor(a: argparse.Namespace) -> int:
    from . import doctor
    return doctor.run()


def _cmd_setup(a: argparse.Namespace) -> int:
    from . import doctor, sysenv, toolchain
    env = sysenv.build_env()
    mg5 = toolchain.locate_mg5(env)
    toolchain.configure_mg5(mg5, env)
    toolchain.ensure_py8_interface(mg5, env)
    toolchain.ensure_loop_tools(mg5, env)
    print(f"MG5 ready: {mg5.launcher} (version {mg5.version()})")
    return doctor.run()            # finish with the environment check, so one command is enough


def _cmd_model(a: argparse.Namespace) -> int:
    from . import models
    if a.action == "list":
        for n, s in sorted(models.registry().items()):
            print(f"{n:42} {s.get('git') or s.get('url')} @ {(s.get('rev') or s.get('sha256') or '')[:10]}")
        return 0
    spec = None
    if a.git or a.url:
        spec = {"git": a.git, "rev": a.rev, "url": a.url, "sha256": a.sha256, "subdir": a.subdir}
    m = models.fetch(a.name, spec, a.restriction)
    print(f"restrictions: {', '.join(m.restrictions) or '(none)'}", file=sys.stderr)
    print(m.path)
    return 0


def _cmd_pdf(a: argparse.Namespace) -> int:
    from . import pdf, sysenv
    env = sysenv.build_env()
    for s in a.sets:
        print(pdf.ensure(s, env))
    return 0


def _cmd_mg5(a: argparse.Namespace) -> int:
    """Interactive MG5 with the same environment fixes MEG uses."""
    from . import sysenv, toolchain
    env = sysenv.build_env()
    sysenv.raise_open_file_limit()
    mg5 = toolchain.locate_mg5(env)
    toolchain.configure_mg5(mg5, env)
    orig = Path.cwd()
    args = [str(orig / x) if not x.startswith("-") and (orig / x).exists() else x for x in a.args]
    work = Path(a.workdir or os.environ.get("MEG_MG5_WORKDIR", "work")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    os.chdir(work)
    print(f"[meg] MG5: {mg5.launcher} | working directory: {work}", file=sys.stderr)
    os.execve(str(mg5.launcher), [str(mg5.launcher), *args], env)
    return 0   # not reached


def _campaign(a: argparse.Namespace):
    from .batch.campaign import Campaign
    return Campaign.load(a.campaign)


def _cmd_submit(a: argparse.Namespace) -> int:
    from .batch import submit as sub
    overrides = list(a.overrides)
    if a.replicas is not None:
        overrides.append(f"execution.replicas={a.replicas}")
    if a.seed_start is not None:
        overrides.append(f"execution.seed_start={a.seed_start}")
    if a.executor:
        overrides.append(f'execution.executor="{a.executor}"')
    cfg = load_config(a.config, overrides)
    c = sub.submit(cfg, dry_run=a.dry_run)
    print()
    print(f"campaign directory: {c.dir}")
    if cfg.execution.executor == "local" and not a.dry_run:
        print(sub.status_text(c)[0])
        print(f"collect the results with: meg collect {c.dir}")
    elif not a.dry_run:
        print(f"check progress with: meg status {c.dir}")
    return 0


def _cmd_status(a: argparse.Namespace) -> int:
    from .batch import submit as sub
    print(sub.status_text(_campaign(a))[0])
    return 0


def _cmd_collect(a: argparse.Namespace) -> int:
    from .batch import collect as col
    s = col.collect(_campaign(a), verify=a.verify)
    print(col.summary_text(s))
    print(f"files are in {_campaign(a).outputs}")
    return 0 if not s["failed"] else 1


def _cmd_resubmit(a: argparse.Namespace) -> int:
    from .batch import submit as sub
    todo = sub.resubmit(_campaign(a), dry_run=a.dry_run)
    print(f"{len(todo)} replicas resubmitted" if not a.dry_run else f"{len(todo)} replicas would be resubmitted")
    return 0


def _cmd_cancel(a: argparse.Namespace) -> int:
    from .batch import submit as sub
    done = sub.cancel(_campaign(a))
    print(f"asked HTCondor to remove cluster(s): {', '.join(map(str, done)) or 'none'}")
    return 0


def _cmd_job(a: argparse.Namespace) -> int:
    """Internal: run one replica. Called by the job script and by the local executor."""
    from .batch import job
    return job.run_replica(Path(a.meta), Path(a.config), a.seed, Path(a.outbox),
                           Path(a.prebuilt) if a.prebuilt else None)


def _cmd_prepare(a: argparse.Namespace) -> int:
    """Internal: build the campaign's MG5 process once and pack it."""
    from .batch import prepare
    return prepare.run_prepare(Path(a.meta), Path(a.config), Path(a.outbox))


def _cmd_schema(a: argparse.Namespace) -> int:
    print(json_schema())
    return 0


def _cmd_init(a: argparse.Namespace) -> int:
    dest = Path(a.path)
    if dest.exists() and not a.force:
        raise MegError(f"{dest} already exists (use --force to overwrite)")
    dest.write_text(EXAMPLE)
    print(f"wrote {dest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meg", description="MEG: MadGraph Event Generator "
                                "(MG5_aMC + Pythia8/Herwig7 + Delphes), driven by a TOML file.")
    p.add_argument("--version", action="version", version=f"meg {__version__}")
    sub = p.add_subparsers(
        dest="cmd", required=True,           # `_job` is internal: left out of the visible command list
        metavar="{generate,plan,doctor,setup,submit,status,collect,resubmit,cancel,model,pdf,mg5,schema,init}")

    r = sub.add_parser("generate", aliases=["run"], help="generate events: run the whole pipeline")
    _add_config_args(r)
    g = r.add_mutually_exclusive_group()
    g.add_argument("-v", "--verbose", action="store_true",
                   help="show ALL of the tools' output (default: MG5/Herwig/Delphes output minus known noise)")
    g.add_argument("-q", "--quiet", action="store_true",
                   help="hide the tools' output; show only stage progress and the summary")
    r.add_argument("--force", action="store_true", help="discard an earlier run in the same directory")
    r.set_defaults(fn=_cmd_generate)

    s = sub.add_parser("plan", help="show what a run would do, without running it")
    _add_config_args(s)
    s.set_defaults(fn=_cmd_plan)

    sub.add_parser("doctor", help="check the environment").set_defaults(fn=_cmd_doctor)
    sub.add_parser("setup", help="one-time setup (MG5, Pythia8, Ninja), then check").set_defaults(fn=_cmd_setup)

    m = sub.add_parser("model", help="UFO models: list the registry or fetch one into the cache")
    m.add_argument("action", choices=["list", "fetch"])
    m.add_argument("name", nargs="?")
    for opt in ("--git", "--rev", "--url", "--sha256"):
        m.add_argument(opt)
    m.add_argument("--subdir", default="")
    m.add_argument("--restriction")
    m.set_defaults(fn=_cmd_model)

    d = sub.add_parser("pdf", help="fetch LHAPDF sets into the cache")
    d.add_argument("action", choices=["fetch"])
    d.add_argument("sets", nargs="+")
    d.set_defaults(fn=_cmd_pdf)

    g5 = sub.add_parser("mg5", help="open MG5 interactively (or run a command file)")
    g5.add_argument("--workdir", help="where MG5 writes its output (default ./work)")
    g5.add_argument("args", nargs=argparse.REMAINDER)
    g5.set_defaults(fn=_cmd_mg5)

    b = sub.add_parser("submit", help="run N replicas (different seeds) locally or on HTCondor")
    _add_config_args(b)
    b.add_argument("--replicas", "-n", type=int, help="number of replicas (execution.replicas)")
    b.add_argument("--seed-start", type=int, help="seed of the first replica (default: run.seed)")
    b.add_argument("--executor", choices=["local", "htcondor"], help="override execution.executor")
    b.add_argument("--dry-run", action="store_true", help="write the campaign directory and scripts, submit nothing")
    b.set_defaults(fn=_cmd_submit)

    for name, fn, helptext in (("status", _cmd_status, "show how far a campaign is"),
                               ("collect", _cmd_collect, "gather finished results under their unique names"),
                               ("resubmit", _cmd_resubmit, "run the failed or lost replicas again"),
                               ("cancel", _cmd_cancel, "remove a campaign's jobs from the HTCondor queue")):
        q = sub.add_parser(name, help=helptext)
        q.add_argument("campaign", help="campaign directory (as printed by `meg submit`)")
        if name == "collect":
            q.add_argument("--verify", action="store_true", help="re-check every file's checksum")
        if name == "resubmit":
            q.add_argument("--dry-run", action="store_true")
        q.set_defaults(fn=fn)

    j = sub.add_parser("_job")      # no help= : argparse then leaves it out of the command list
    j.add_argument("--meta", required=True)
    j.add_argument("--config", required=True)
    j.add_argument("--seed", type=int, required=True)
    j.add_argument("--outbox", required=True)
    j.add_argument("--prebuilt", help="process archive made by _prepare")
    j.set_defaults(fn=_cmd_job)

    pp = sub.add_parser("_prepare")
    pp.add_argument("--meta", required=True)
    pp.add_argument("--config", required=True)
    pp.add_argument("--outbox", required=True)
    pp.set_defaults(fn=_cmd_prepare)

    sub.add_parser("schema", help="print the JSON Schema of the configuration").set_defaults(fn=_cmd_schema)

    i = sub.add_parser("init", help="write an example configuration file")
    i.add_argument("path", nargs="?", default="meg.toml")
    i.add_argument("--force", action="store_true")
    i.set_defaults(fn=_cmd_init)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # `kill <pid>` (HTCondor's eviction) should stop the tools too, not orphan them
    if args.fn in (_cmd_generate, _cmd_job, _cmd_prepare):
        signal.signal(signal.SIGTERM, _on_sigterm)
    _setup_logging()
    try:
        if args.cmd == "model" and args.action == "fetch" and not args.name:
            raise MegError("meg model fetch needs a NAME")
        return args.fn(args)
    except StageError as e:
        print(f"\nmeg: {e}", file=sys.stderr)
        if e.diag:
            print(f"meg: diagnostics written to {e.diag} - please attach this file when asking for help",
                  file=sys.stderr)
        return 1
    except MegError as e:
        print(f"meg: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nmeg: interrupted. Finished stages are kept: run the same command again to resume.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
