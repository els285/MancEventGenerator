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

Needs [pixi](https://pixi.sh) and network access to conda-forge, Launchpad (MG5, py8
interface) and `lhapdfsets.web.cern.ch` (PDF set).

Platforms declared in `pixi.toml`: `linux-64` and `osx-arm64` (Apple Silicon). Windows is
supported through WSL2, which is just `linux-64`. Intel Macs (`osx-64`) and `linux-aarch64`
are not declared yet; add them one at a time with `pixi workspace platform add <platform>`,
because pixi solves every listed platform at once and one missing package fails the lot.

**macOS:** install the Xcode command line tools first (`xcode-select --install`). The conda
compilers still link against the Apple SDK. The scripts use GNU coreutils and bash 5 from the
conda environment, so they behave the same as on Linux. For serious production runs use Linux
or your cluster; the Mac route is for development and testing.

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

- **Not yet run end to end.** The `linux-64` environment solve has succeeded for both
  environments (see `pixi.lock`: pythia8 8.312, lhapdf 6.5.6, delphes 3.5.1,
  hepmc2 2.06.11, mg5amcnlo 3.5.7, gcc/gfortran 15.3), but the MG5/Pythia8/Delphes runs have
  not been executed. Shell and Python syntax and the card and manifest helpers were tested
  offline.
- Package availability on `osx-arm64` is unconfirmed (`delphes` is known to list it). The
  `mg5amcnlo` package solves on linux-64, but its contents (NLO, bundled models, py8
  interface) are unverified until the smoke test runs.
- `osx-arm64` is the least tested route: MG5 NLO compiling Fortran with conda's gfortran on
  Apple Silicon is the most likely thing to need adjustment.
- The `conda-mg5` environment also installs the conda package `mg5amcnlo-pythia8-interface`
  (seen in `pixi.lock`), so the source `install mg5amc_py8_interface` step in
  `scripts/setup_mg5.sh` may be redundant there. If `setup-mg5` is slow or fails in that
  environment, try skipping the install and see whether the NLO stage finds the interface.
- **FastJet.** conda-forge's `fastjet` is the Python bindings, and the `fastjet-cxx` 3.5.2
  build ships only three runtime libraries (no headers, no `fastjet-config`), so the C++
  FastJet that MadLAD builds from source is not available from conda-forge in a usable form.
  This spike does not require it: MG5 should fall back to its bundled fjcore, and the Delphes
  card in the smoke test is the real check on jet finding. If a later feature needs full
  FastJet (FxFx merging, Delphes with external FastJet), build a small conda recipe for it.
- The MG5 command sequence (`launch <dir> -f` taking the shower from `run_card.dat`) follows
  MadLAD's approach but has not been exercised here; `scripts/smoke.sh` fails loudly with a hint
  if the shower does not run.
- Out of scope for this spike: custom models/plugins in the content cache, MadSpin, custom
  scales, HTCondor/Slurm runners.
