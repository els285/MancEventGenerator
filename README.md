# MEG 🦈: — MadGraph Event Generator

One TOML file in, a Delphes ROOT file and a provenance manifest out.

MEG drives **MadGraph5_aMC@NLO** (LO and NLO), **Pythia8** or **Herwig7** showering, and **Delphes**
from a locked conda-forge toolchain, on **macOS (Apple Silicon)** and **Linux**. It is the packaged
successor of the `madlad-conda-spike` prototype.

```toml
# ttbar.toml
[run]
name = "ttbar_nlo"

[process]
order = "NLO"            # p p > t t~ [QCD]

[shower]
kind = "herwig7"         # "pythia8" | "herwig7" | "none"
```
```
pixi run meg generate ttbar.toml
```

## Install

MEG needs [pixi](https://pixi.sh). It installs every tool from conda-forge and locks them
(`pixi.lock`, for `linux-64` and `osx-arm64`), so everyone gets the same MG5, Pythia8, Herwig7 and
Delphes builds.

If you do not have pixi yet, install it first (macOS and Linux), then open a new terminal:

```
curl -fsSL https://pixi.sh/install.sh | sh
```

Then install MEG:

```
git clone https://github.com/els285/MancEventGenerator.git MEG
cd MEG
pixi run setup
```

The last line installs the locked environment (`pixi run` does it when it is missing), then runs the
one-time setup: it configures MG5, installs MG5's Pythia8 interface and, for NLO, the Ninja loop
library (compiled from source, once; needs network), and finishes with `meg doctor`, which checks every
tool and prints versions. Safe to run again.

Then use `pixi run meg ...`, or `pixi shell` and plain `meg ...`.

## Running MG5 interactively

To try things by hand, open the MG5 prompt with the same environment fixes MEG uses (compilers, library
paths, Pythia8 interface, PDFs, open-file limit):

```
pixi run mg5                  # the MG5 prompt
pixi run mg5 my_commands.mg5  # or run a command file (looked up relative to where you ran it)
```

(`pixi run meg mg5` is the same thing.) At the prompt, `import model sm`, `generate p p > t t~`,
`output ttbar`, `launch` and so on work as usual.

**Where things are saved:** MG5 runs in `./work`, that is a `work/` folder in the directory you run it from (created if needed;
run it from the repository root to keep everything together), so a process you create with `output ttbar` ends up in `work/ttbar/`, with its events in `work/ttbar/Events/run_01/`.
Use `--workdir DIR` (`pixi run meg mg5 --workdir DIR`) or `MEG_MG5_WORKDIR=DIR` to work somewhere else.
`work/` is git-ignored and is separate from `results/`: interactive sessions never touch the runs made by
`meg generate`, and `meg generate` never reads from `work/`.

**Detector simulation on an existing file.** `pixi run meg delphes FILE.lhe.gz -o out.root` (or a
`.hepmc`/`.hepmc.gz` file) applies the Delphes simulation to events you made by hand, choosing the right
reader from the file; `--card` picks the card (default `ATLAS`). A step-by-step walkthrough of
interactive MG5 (LO and NLO, MadSpin, showering, seeds, Delphes) is in
[docs/tutorial-interactive-madgraph.md](docs/tutorial-interactive-madgraph.md).

## Many replicas on HTCondor

To make N statistically independent copies of one run, each with its own random seed, use `meg submit`
instead of `meg generate`. Each replica is an ordinary MEG run; only the seed (and the run name) differ.

```
pixi run meg submit examples/htcondor_campaign.toml            # submits the whole campaign
pixi run meg status campaigns/ttbar_dilepton-3fa9c1d2          # what is running / done / failed
pixi run meg collect campaigns/ttbar_dilepton-3fa9c1d2         # gather results, print combined cross-section
pixi run meg resubmit campaigns/ttbar_dilepton-3fa9c1d2        # rerun only the failed or lost replicas
```

Try it small and locally first: `meg submit CONFIG --executor local -n 3` runs three replicas here with
exactly the same job code the cluster runs. `--dry-run` writes the campaign directory and the HTCondor
files (`submit.sub`, `job.sh`, `env.sh`) without submitting, so you can read them.

**What you set** (all in `[execution]`, see `examples/htcondor_campaign.toml`): `executor`, `replicas`,
`cores`, `memory`, `disk`, `walltime`, `max_running`, and `retrieve`. Settings that belong to your site
rather than your project (accounting group, requirements, site-specific lines) go once into
`~/.config/meg/site.toml` (or the file named by `MEG_SITE`); project configs win over it:

```toml
[execution.htcondor]
accounting_group = "group_hep.user"
extra = ["+JobFlavour = 'workday'"]
```

**What comes back.** Every job leaves an `outbox/` of final, uniquely named files, which HTCondor
transfers back (also when the job failed), so `<campaign>/replicas/s0007/outbox/` holds replica 7's files.
`meg collect` links them all into `<campaign>/outputs/` as
`<run name>-<process id>_s<seed>.<kind>` (for example `ttbar_dilepton-3fa9c1d2_s0007.delphes.root`).
The process id is a short hash of the physics settings, so two different configurations never share
names. What is retrieved is your choice: `retrieve = ["delphes", "lhe", "hepmc"]` picks files, and
`retrieve = "all"` brings the whole run directory home as one `.run.tar.gz` per replica (the full MG5
directory has thousands of files, hence one archive). Each replica always also returns its
`manifest.json`, a small bundle of logs/cards (`.logs.tar.gz`) and a `status.json` with checksums.
`meg collect` prints the combined cross-section (inverse-variance weighted over replicas) with a
chi2/ndf consistency check.

**Results on another disk (e.g. EOS).** If the campaign directory sits on a small disk (AFS, say), add
`output_dir = "/eos/user/e/ethan/meg"` under `[execution]` (an absolute path the *nodes* can write to).
Each job then copies its files to `<output_dir>/<campaign id>/` itself and only a small `status.json`
comes back through HTCondor. `meg collect` checks the files there (size, and checksum with `--verify`)
and does not copy them. A failed copy makes that replica fail (its logs stay in the campaign directory),
so `meg resubmit` redoes it. The nodes need credentials for that filesystem; at sites that need them, add
the right line to `execution.htcondor.extra` (for example `MY.SendCredential = True` for Kerberos at
CERN, check your site's documentation). Without `output_dir`, nothing changes.

**How a job runs.** `meg submit` first does every one-time, possibly networked step on the submit host
(MG5 configuration, Pythia8 interface, Ninja, UFO models, PDF sets), then the jobs run with
`MEG_OFFLINE=1`, so nodes need no internet and jobs cannot race each other to install things. Each job
works in the node's scratch directory (MG5 writes thousands of small files; shared filesystems are slow
at that), loads the MEG environment from `env.sh` (generated from `pixi shell-hook`) and runs one replica.

**Assumptions.** The repository (with its `.pixi` environment) and the MEG cache (`MEG_CACHE`, default
`~/.cache/meg`) must be readable from the worker nodes, e.g. on a shared filesystem. The campaign directory
itself does not need to be visible to the nodes: the three small files a job needs are transferred.
A custom Delphes card is referenced by absolute path and must be readable from the nodes as well.
Each campaign name+physics combination is a directory; submitting it again refuses, so change `run.name`
for a new campaign. Stop a campaign with `meg cancel`.

## Commands

| command | what it does |
|---|---|
| `meg generate CONFIG [--set k=v ...] [-v\|-q] [--force]` | generate events (`meg run` also works). By default you see MG5's, Herwig's and Delphes' own output (minus known MG5 noise) plus one line per stage. `-v` shows all of it, `-q` hides the tools' output and keeps the stage lines. Everything is always in the log files. |
| `meg submit CONFIG [-n N] [--seed-start S] [--executor local\|htcondor] [--dry-run]` | N replicas with seeds S..S+N-1, locally or on HTCondor (see above) |
| `meg status\|collect\|resubmit\|cancel CAMPAIGN` | follow, gather, rerun or stop a campaign |
| `meg plan CONFIG [--set k=v ...]` | show what a run would do, without running |
| `meg init [FILE]` | write an example config |
| `meg schema` | JSON Schema of the config (for editor completion) |
| `meg doctor` | check the environment |
| `meg setup` | configure MG5, install its Pythia8 interface and Ninja |
| `meg model list` / `meg model fetch NAME` | UFO models: registry / fetch into the cache |
| `meg pdf fetch SET...` | fetch LHAPDF sets into the cache |
| `meg mg5 [file.mg5]` (or `pixi run mg5`) | open MG5 by hand, with the same environment fixes MEG uses; it works in `./work` (`--workdir DIR` to change) and finds command files relative to where you ran it |

`--set` overrides any config key, so one file serves many runs:
`meg generate ttbar.toml --set 'run.name="ttbar_s2"' --set run.seed=2 --set 'shower.kind="pythia8"'`.
Values are TOML (`"text"` is quoted, numbers and booleans are not).

## Configuration

Every key is optional. Unknown keys are errors, so a typo cannot silently run with a default.
`meg schema` prints the full list with descriptions; the sections are:

| section | key | default | meaning |
|---|---|---|---|
| `[run]` | `name`, `seed`, `output_dir` | `meg_run`, `1`, `results` | output goes to `<output_dir>/<name>/` |
| `[process]` | `definition` | `p p > t t~` | MG5 process (the baseline is always ttbar) |
| | `order` | `LO` | `LO` or `NLO` (`[QCD]` is appended if you wrote no brackets) |
| | `extra_commands` | `[]` | raw MG5 commands before `generate`, e.g. `define p = p b b~` |
| `[model]` | `name` | `sm` (LO) / `loop_sm-no_b_mass` (NLO) | MG5 built-in, registered UFO, or name for an inline UFO |
| | `restriction` | – | e.g. `massless` |
| | `params` | `{}` | param_card edits by name or `BLOCK:id`; unknown names are errors |
| | `git`+`rev` / `url`+`sha256`, `subdir` | – | a UFO not in the registry (pinned) |
| `[generation]` | `events` | `500` | |
| | `pdf` | `builtin` (LO) / `NNPDF30_nlo_as_0118` (NLO) | `builtin` or an LHAPDF set name |
| | `nlo_accuracy` | `0.01` | NLO `req_acc` |
| | `run_card` | `{}` | strict run_card edits, e.g. `ptj = 30.0` |
| `[madspin]` | `enable` | `false` | decay particles with MadSpin |
| | `decays` | `[]` | your MadSpin decay statements, required when enabled |
| | `define`, `options` | `[]`, `{}` | MadSpin `define` lines; `set` options (e.g. `BW_cut`) |
| `[shower]` | `kind` | `pythia8` | `pythia8`, `herwig7`, `none` |
| `[detector]` | `kind`, `card` | `delphes`, `ATLAS` | packaged card name, or path to a `.tcl` |
| `[output]` | `lhe`, `hepmc`, `compress` | `false`, `false`, `true` | keep the LHE / showered HepMC file in `<run>/output/` (gzip by default) |
| `[execution]` | `cores` | `0` (all) | |

NLO needs a shower, and an LHAPDF set (not `builtin`); both are checked when the config is loaded.
See `examples/` for LO, NLO, custom cuts and a SMEFTsim model.

### What each shower choice does

| order | shower | MG5 is told | then |
|---|---|---|---|
| LO | `none` | `launch -f` | Delphes reads the LHE file |
| LO | `pythia8` | `shower=Pythia8` | Delphes reads the HepMC from MG5's interface |
| LO | `herwig7` | `launch -f` | Herwig showers the LHE file → Delphes |
| NLO | `pythia8` | `shower=PYTHIA8`, `parton_shower=PYTHIA8` | Delphes reads the HepMC |
| NLO | `herwig7` | `shower=OFF`, `parton_shower=HERWIGPP` | Herwig showers the MC@NLO events → Delphes |

Delphes' two HepMC readers accept different layouts; MEG picks the reader from the file header.

### Decays (MadSpin)

`p p > t t~` produces undecayed tops, so the jets, leptons and MET in Delphes only look like a ttbar
event once the tops decay. `madspin.enable = true` decays them with MadSpin (spin correlations kept).
You write the decay syntax yourself, exactly as in a `madspin_card.dat` but without the leading word:

```toml
[madspin]
enable = true
define = ["l+ = e+ mu+", "l- = e- mu-", "vl = ve vm", "vl~ = ve~ vm~"]
decays = ["t > w+ b, w+ > l+ vl", "t~ > w- b~, w- > l- vl~"]
options = { BW_cut = 15 }                 # optional MadSpin 'set' lines
```
MEG writes the card in this order: `set seed` (from `run.seed`), your `options`, your `define`s, your
`decay`s, `launch`. A leading `decay `/`define ` you typed anyway is accepted. Any particle can be
decayed, not only tops. See `examples/` for dileptonic and inclusive top decays. Things to know:

* MadSpin writes the decayed events to a second run, `Events/run_01_decayed_1/`; MEG uses that one
  and fails if it is missing, so a silently skipped MadSpin cannot pass as a decayed sample.
* The shower and Delphes run on the decayed events.
* The LHE cross-section after MadSpin **includes the branching ratio** of the decays you chose
  (e.g. e/mu dileptons are about 5% of the inclusive value).
* Lepton+jets takes two runs, one per charge assignment (`t` leptonic with `t~` hadronic, then swapped):
  MadSpin decays `t` and `t~` independently, so listing both a leptonic and a hadronic decay for the
  same particle mixes all the final states.
* MadSpin needs the width of each decaying particle in the `param_card`; set it with `model.params`
  (e.g. `"DECAY:6" = 1.4`) if you change the model parameters.
* Works at LO and NLO, with either shower or none. `decays` listed with `enable = false` do nothing, so
  `--set madspin.enable=true` switches a config on.

### UFO models (e.g. SMEFTsim)

A model is an input, not part of the environment. It is fetched from a **pinned** source (a full git
commit SHA, or an archive sha256) into an immutable cache directory keyed by its content hash, and
that hash is recorded in `./models.lock`. If the source ever yields different bytes, MEG stops.
SMEFTsim 3.0.2 is registered; add your own in a `./models.toml` (same format as
`src/meg/data/models.toml`), or give `git`/`rev` or `url`/`sha256` inline in the config.
`MEG_OFFLINE=1` forbids network access (cluster nodes). **UFO models are Python code that MG5
executes; only use sources you trust.** SMEFTsim is tree-level, so use it with `order = "LO"`.

## Stopping a run

Press **Ctrl+C** (the Control key; on a Mac keyboard that is `ctrl`, not `cmd`). MEG stops MG5 and
everything it started (compilers, `make`, worker processes): politely first, then forcibly after a few
seconds; a second Ctrl+C kills immediately. Stages that had finished are kept, so running the same
command again resumes. `kill <pid of meg>` does the same. Ctrl+Z only *suspends* a run (`fg` resumes
it); don't use it to stop one.

## What a run produces

```
results/<name>/
  manifest.json          what produced the sample: resolved config, tool versions, model hash,
                         cross-section, event counts, ROOT file hash, timings
  config.resolved.json
  generate/              MG5 process dir, proc.mg5 / launch.mg5 command files, logs, events.lhe[, events.hepmc]
  shower/                (Herwig only) hw7.in, logs, the HepMC file
  detector/delphes.root  the Delphes output (tree "Delphes")
  output/<name>.lhe.gz   only if output.lhe = true; <name>.hepmc.gz if output.hepmc = true
  .meg/                  stage records used for resuming
```

By default the LHE and HepMC files stay in `generate/` and `shower/` as intermediates (that is what makes
resuming work) and are not copied anywhere. Ask for them with `output.lhe = true` / `output.hepmc = true`
(or `--set output.hepmc=true`); you can add this to a finished run and only that step runs. Uncompressed
copies (`compress = false`) are hard links, so they take no extra disk. HepMC files are large: expect
gigabytes per ten thousand events.

Re-running the same config in the same directory skips stages whose inputs are unchanged (a new
Delphes card re-runs only Delphes; a new seed re-runs everything). `--force` starts over. MEG refuses
to use a directory that is not one of its run directories.

An empty result is a failure: MG5 often exits 0 after an error and Delphes prints `** ERROR` yet
writes an empty tree, so MEG scans the logs, and checks the ROOT file has entries. On any failure it
writes `<stage>/diag.txt` (platform, build flags, log tails, MG5's hidden compile errors re-run);
attach that file when asking for help.

## Python API

```python
import meg

cfg = meg.load_config("ttbar.toml", overrides=['generation.events=2000', 'shower.kind="pythia8"'])
print(meg.build_plan(cfg).describe())
res = meg.generate(cfg)          # meg.run is the same function
res.cross_section_pb, res.delphes_root, res.manifest["toolchain"]
```
Or build a `meg.Config(...)` directly. Errors are `meg.MegError` / `meg.StageError` (the latter has `.diag`).

## Where things live

| | |
|---|---|
| environment (immutable) | `.pixi/`, locked by `pixi.lock` |
| cache (content-keyed) | `$MEG_CACHE`, default `~/.cache/meg`: `models/`, `lhapdf/` |
| MG5 configuration | written into the MG5 install in the environment by `meg setup` |
| runs | `<output_dir>/<name>/` |

PDF sets are fetched on first use. Behind a restrictive network, set `LHAPDF_MIRRORS` (space-separated
base URLs serving `<SET>.tar.gz`) or extract a downloaded set into `$MEG_CACHE/lhapdf/`.

## Platform notes (handled for you)

MEG applies, to the programs it launches, the fixes the conda-forge toolchain needs: re-adds the C++
standard library to MG5's link line, builds MG5's C++ as C++14, puts the environment's `lib` on
`LD_LIBRARY_PATH` on Linux, patches and re-signs MG5's Pythia8 interface binary on macOS, and raises
the open-file limit. `meg doctor` shows them. NLO runs compile process-specific code, which takes minutes.

## Development

```
pixi run -e dev pytest                # fast: fake MG5/Delphes/Herwig that reproduce the real tools' quirks
pixi run -e dev pytest -m integration # real tools, minutes (also a manual CI job)
pixi run -e dev ruff check src tests
```
Layout: `config.py` (schema) → `plan.py` (pure) → `runner.py` (stages) using `generate.py`, `herwig.py`,
`delphes.py`; support in `toolchain.py`, `sysenv.py`, `models.py`, `pdf.py`, `cards.py`, `diagnostics.py`,
`manifest.py`. A new shower or detector is a module like `herwig.py` plus a branch in `plan.py`/`runner.py`.

## v0.1 scope and what is not here yet

* Local execution only (`execution.executor = "local"`). The plan is deliberately pure so job-array
  executors (Slurm/HTCondor) and seed sharding can be added without changing the config.
* No MadSpin / top decays: with `p p > t t~` the tops are undecayed, so Delphes jet multiplicities are
  low. Decays are the next physics feature.
* Parameter scans, and merging shards, are not implemented.
* MG5's `systematics` weights make HepMC files large; set the relevant `run_card` key to disable them
  once you know its name in your MG5 version.

## Licence

Not chosen yet. MEG drives third-party programs with their own licences (MadGraph5_aMC@NLO, Pythia8,
Herwig7, Delphes, LHAPDF, FastJet); MEG does not redistribute them, they come from conda-forge.
Choose a licence compatible with the tools you intend to distribute alongside it.
