# madlad-conda-spike

A small experiment to answer one question before designing the new pipeline:

> Can a locked conda-forge environment replace the source-built Singularity image, and can
> MG5 run NLO + Pythia8 + Delphes inside it?

It builds the toolchain MadLAD's image builds (MG5, Pythia8, LHAPDF, FastJet, Delphes), then runs
the same two detector-simulation paths MadLAD uses.

| Stage | Process | Exercises | Delphes mode |
|---|---|---|---|
| `lo`  | `p p > t t~`        | MG5, LHAPDF, run-card editing | `DelphesLHEF` |
| `nlo` | `p p > t t~ [QCD]`  | MG5 NLO run-time Fortran build, Pythia8 interface, HepMC2, shower | `DelphesHepMC2` |

The Delphes card is MadLAD's `ATLAS_sim_FASTJET.tcl` (MIT licence), so the Delphes FastJet module
is exercised too.

## Run it

Needs [pixi](https://pixi.sh), a Linux machine (x86_64) and network access to conda-forge,
Launchpad (MG5, py8 interface) and `lhapdfsets.web.cern.ch` (PDF set).

```bash
# Path A (fallback, most likely to work): conda-forge toolchain + pinned MG5 tarball
pixi run fetch-mg5          # MG5 into ./cache/mg5 (sha256 recorded on first use; commit it)
pixi run check              # what got installed, Pythia8 build options, models present
pixi run smoke-lo           # fast: minutes
pixi run smoke-nlo          # slow: NLO grid setup, tens of minutes on a few cores

# Path B (the experiment): conda `mg5amcnlo` package instead of the tarball
pixi run -e conda-mg5 check
pixi run -e conda-mg5 smoke-lo
pixi run -e conda-mg5 smoke-nlo
```

`pixi run smoke` does check + MG5 setup + PDFs + both stages. Commit the generated `pixi.lock`;
the lockfile is the thing that makes the environment reproducible.

Tunables (environment variables): `SEED`, `NB_CORE`, `LO_EVENTS`, `NLO_EVENTS`, `MG5_VERSION`,
`MG5_BIN`, `MADLAD_CACHE`.

## What you get back

- `results/<env>/{lo,nlo}/*.log`: MG5 and Delphes logs. **Keep these if anything fails.**
- `results/<env>/{lo,nlo}/manifest.json`: package builds, lockfile hash, MG5 version, seed,
  event count, cross-section, Delphes entry count. A preview of the per-run manifest the new
  pipeline would write.

## Reading the outcome

| Result | Meaning | Next step |
|---|---|---|
| Both paths pass | Fully conda-based stack is viable | Build the pipeline core on `conda-mg5` |
| Path A passes, B fails | Toolchain is fine, the `mg5amcnlo` conda package is not (missing NLO, models, or py8 interface) | Keep MG5 as a pinned tarball in the content cache |
| `solve` fails on a package | Not available for your platform or channel | Add its channel under `[feature.condamg]`, or build a conda recipe |
| `setup-mg5` fails at `install mg5amc_py8_interface` | Pythia8 ABI or path mismatch with conda's build | Check `pythia8-config --config` output in `pixi run check` |
| NLO fails at "no HepMC file" | Shower did not run | See the comment in `scripts/smoke.sh`; `launch.log` shows the switches MG5 chose |
| NLO fails during compilation | Compiler/ABI mismatch with the conda libraries | This is the main risk identified for the conda route; keep the log |

## Layout

```
pixi.toml                    toolchain, two environments, tasks
scripts/common.sh            cache dirs, MG5 discovery
scripts/fetch_mg5_tarball.sh pinned MG5 in ./cache/mg5, hash-checked
scripts/setup_mg5.sh         point MG5 at $CONDA_PREFIX, install the py8 interface
scripts/fetch_pdfs.sh        PDF sets into ./cache/lhapdf
scripts/edit_card.py         strict run-card editor (unknown key = error)
scripts/set_mg5_config.py    mg5_configuration.txt editor
scripts/smoke.sh             the LO and NLO stages
scripts/report.py            sanity checks + manifest.json
scripts/check_env.py         environment inspection
delphes/ATLAS_sim_FASTJET.tcl   from tzuhanchang/MadLAD
.github/workflows/spike.yml  same thing in CI, weekly
```

## Status and known gaps

- **Not yet run end to end.** It was written in a sandbox with no route to conda-forge, so the
  environment solve and the MG5/Pythia8/Delphes runs have not been executed. Shell and Python
  syntax and the card and manifest helpers were tested offline; see the commit notes.
- Package availability on conda-forge was not confirmed for `pythia8`, `lhapdf`, `fastjet`
  and `hepmc2` (assumed from memory). The `mg5amcnlo` package's contents are unverified.
- The MG5 command sequence (`launch <dir> -f` taking the shower from `run_card.dat`) follows
  MadLAD's approach but has not been exercised here; `scripts/smoke.sh` fails loudly with a hint
  if the shower does not run.
- Out of scope for this spike: custom models/plugins in the content cache, MadSpin, custom
  scales, HTCondor/Slurm runners.
