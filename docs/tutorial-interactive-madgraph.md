# Interactive MadGraph with MEG: ttbar at LO and NLO

A hands-on tutorial for a Masters-level reader who knows the basics of collider physics (Feynman
diagrams, PDFs, cross-sections, parton showers) but has not driven MadGraph by hand before. You will
generate top-quark pair production at **leading order (LO)** and **next-to-leading order (NLO)**, with
and without **MadSpin** decays, with and without a **parton shower**, change the **seed** and the
**number of events**, and finish by passing the events through a **Delphes** detector simulation.

MEG's job here is only to give you a working, identical MadGraph on any machine: MG5_aMC, Pythia8,
Delphes and every library they need, installed in one command. Everything you type at the MG5 prompt is
ordinary MadGraph, so what you learn applies to any installation. In section 9 you will see MEG run the
same physics from a configuration file, which is how you would produce samples at scale.

Allow a couple of hours. Several steps compile code or generate events; the times quoted are rough and
depend on your machine.

## Contents

0. [Set-up](#0-set-up)
1. [The big picture](#1-the-big-picture)
2. [Your first look at MG5](#2-your-first-look-at-mg5)
3. [ttbar at LO, parton level](#3-ttbar-at-lo-parton-level)
4. [Run parameters: events, seed and physics inputs](#4-run-parameters-events-seed-and-physics-inputs)
5. [Adding a parton shower](#5-adding-a-parton-shower)
6. [Decaying the tops with MadSpin](#6-decaying-the-tops-with-madspin)
7. [ttbar at NLO](#7-ttbar-at-nlo)
8. [Detector simulation with Delphes](#8-detector-simulation-with-delphes)
9. [The same thing, from a config file](#9-the-same-thing-from-a-config-file)
10. [Exercises](#10-exercises)
11. [When something goes wrong](#11-when-something-goes-wrong)

---

## 0. Set-up

You need [pixi](https://pixi.sh) and a clone of MEG (see the README).
To install [pixi], open a terminal and do:
```bash
curl -fsSL https://pixi.sh/install.sh | sh

```
Then install MEG via:
```bash
git clone https://github.com/els285/MancEventGenerator.git MEG
cd MEG
pixi run setup          # one-off: configures MG5, Pythia8 interface and the NLO loop library; then checks
```

Do everything in this tutorial **from the MEG directory** (the one containing `pixi.toml`), in a terminal.
Prefix commands with `pixi run`, or type `pixi shell` once and then drop the prefix.

Two conventions used below:

* Lines in a `bash` block are typed in your normal shell.
* Lines in a block headed *"at the MG5 prompt"* are typed after you start MG5 with `pixi run mg5`
  (the prompt reads `MG5_aMC>`). To leave MG5, type `exit`.

**Where files go.** `pixi run mg5` runs MG5 in a folder called `work/` inside the MEG directory
(created if needed). A process you `output ttbar_lo` appears as `work/ttbar_lo/`, and its generated
events as `work/ttbar_lo/Events/run_01/`, `run_02/`, ... (a new numbered run each time you launch).
`work/` is ignored by git and is never touched by `meg generate`.

---

## 1. The big picture

Producing simulated collider events is a chain of separate calculations, each handing a file to the next:

```
 hard process        decays          parton shower +        detector
 (matrix element)    (optional)      hadronisation          simulation
 ----------------    ----------      ---------------        ----------
   MadGraph5     ->   MadSpin    ->      Pythia8        ->    Delphes
   "LHE" file         "LHE" file         "HepMC" file         "ROOT" file
```

* **MadGraph** computes the matrix element for your process, integrates it over phase space with the
  PDFs, and writes **unweighted events**: a list of partons with four-momenta (a `.lhe` file, Les Houches
  Event format). Each event has the same weight, so a histogram of events is a histogram of the physics.
* **MadSpin** decays heavy particles (here the tops) *after* the production, but keeps the spin
  correlations between production and decay. Without it, MadGraph's `p p > t t~` leaves the tops stable.
* **Pythia8** (or Herwig) takes the partons, adds initial- and final-state radiation, hadronises, and
  decays unstable hadrons. The output is the full final-state particle record (`.hepmc` file).
* **Delphes** is a fast, parametrised detector: it clusters jets, smears momenta, applies efficiencies
  and writes reconstructed objects (jets, electrons, muons, missing energy) to a ROOT file.

You will run each link of this chain and look at what it produces.

---

## 2. Your first look at MG5

```bash
pixi run mg5
```

You get a banner and the `MG5_aMC>` prompt. Try, *at the MG5 prompt*:

```
help
help generate
display particles
display multiparticles
```

* `display multiparticles` lists the **labels** you can use in a process, and which particles each one
  stands for. `p` ("proton") and `j` ("jet") are groups of quarks and gluons; look at what yours contains
  (whether the b quark is included depends on the model and restriction you import).
* `t` is the top quark and `t~` the anti-top (a tilde means anti-particle). `l+` / `l-` are charged
  leptons, `vl` neutrinos, `w+` / `w-` the W bosons.

Models define the particles and couplings. Import the Standard Model and look at it:

```
import model sm
display particles
display interactions
```

Leave with `exit` when you are done looking around. MG5 remembers nothing between sessions except the
process directories it wrote to disk.

---

## 3. ttbar at LO, parton level

### 3.1 Define and write out the process

Start MG5 again (`pixi run mg5`) and type, *at the MG5 prompt*:

```
import model sm
generate p p > t t~
output ttbar_lo
```

* `generate p p > t t~` asks MG5 for all tree-level diagrams for proton-proton going to a top pair:
  gluon-gluon fusion and quark-antiquark annihilation. MG5 prints how many diagrams it found.
* `output ttbar_lo` writes a self-contained **process directory**, `work/ttbar_lo/`. This is where the
  matrix element code (Fortran) lives. It does not compile or run yet.

Look at the directory (in another terminal, or after `exit`):

```bash
ls work/ttbar_lo
ls work/ttbar_lo/Cards
```

The `Cards/` folder holds the inputs you will edit later: `param_card.dat` (masses, widths, couplings),
`run_card.dat` (beam energies, cuts, number of events, seed, PDFs) and, once you use MadSpin,
`madspin_card.dat`.

### 3.2 Launch a run

Back at the MG5 prompt (you are still inside the session if you did not `exit`; if you left, start MG5 and
type `launch ttbar_lo`):

```
launch ttbar_lo
```

MG5 shows a **menu of switches**. For this first run leave everything off. Type `done`. It then shows a
**menu of cards** (param, run, ...). Type `set nevents 2000`, `set iseed 11`, then `done`. (What these two
commands do is explained in section 4; for now just copy them.) MG5 compiles the process, integrates the
cross-section, generates the events, and prints something like

```
  === Results Summary for run: run_01 tag: tag_1 ===

     Cross-section :   ... +- ... pb
     Nb of events :  2000
```

The first launch compiles and can take a few minutes; later runs of the same process directory are much
faster. (If you do not type anything at a menu, MG5 carries on with the defaults after about a minute.)

Note the cross-section. At 13 TeV expect a few hundred pb at LO (the default beams are 6.5 TeV each).
Your exact value depends on the PDF set and scale choice, which is part of the physics (section 7 shows
the NLO value).

### 3.3 What did you get?

```bash
ls work/ttbar_lo/Events/run_01
```

The events are in `unweighted_events.lhe.gz`, a compressed text file. Make an uncompressed copy to read
(`-k` keeps the original; if your `gunzip` has no `-k`, use `gunzip -c file.gz > file`) and open it in an editor:

```bash
gunzip -k work/ttbar_lo/Events/run_01/unweighted_events.lhe.gz
nano work/ttbar_lo/Events/run_01/unweighted_events.lhe       # or: vim ...
```

In `nano`, `Ctrl+W` searches and `Ctrl+X` quits; in `vim`, `/text` searches (`n` for the next match),
`gg` / `G` jump to the top / bottom and `:q` quits. (`gunzip -c file.gz | less` also works if you prefer a
pager, and `gunzip -c` is the same on Linux and macOS, unlike `zcat`.) A tour, in file order:

1. **The header** (`<header>` ... `</header>`). It starts with a banner and contains a copy of the cards the
   run used. Search for `iseed`: it should show the seed you set (11). This is how every sample carries
   its own provenance.
2. **The init block** (search `<init>`). Two lines: beam particle codes (`2212` = proton), beam energies,
   PDF identifiers; then the process line, whose first number is the **cross-section in pb** and the
   second its uncertainty. Compare it with the number MG5 printed.
3. **The first event** (search `<event>`). The first line is `NUP IDPRUP XWGTUP SCALUP AQEDUP AQCDUP`: the number of
   particles, a process id, the **event weight**, the scale and the couplings. Then one line per
   particle: `IDUP ISTUP MOTHUP1 MOTHUP2 ICOLUP1 ICOLUP2 PX PY PZ E M VTIMUP SPINUP`.
   * `IDUP` is the PDG code: `21` gluon, `1..6` quarks (`-` for antiquarks), `6` the top, `11`/`13`
     electron/muon.
   * `ISTUP` is the status: `-1` incoming parton, `1` final state, `2` intermediate resonance.
   * `MOTHUP` point at the parents (line numbers in the same event, counting from 1).
   * `ICOLUP` are the colour-flow labels: matching numbers connect a colour to its anticolour.
4. **Check the physics by eye.** The two incoming partons have no transverse momentum, so the two tops'
   `PX` values must be equal and opposite, and the same for `PY`. Is this event gluon-gluon or
   quark-antiquark? Is `M` the top mass in your param card?
5. **The weights.** Look at `XWGTUP` in a few events. In an unweighted LO sample they are all the same.
6. **The end** (`G`, or `Ctrl+W` then `</LesHouchesEvents>`). Nothing special, but notice how little
   information per event there is: this is the hard process only.

Because the top quarks are not decayed here, `6` and `-6` appear with status `1`.

### 3.4 Read the events with pylhe

Reading a file by eye teaches the format; analysing thousands of events needs code. The standard Python
package for LHE files is [`pylhe`](https://github.com/scikit-hep/pylhe); MEG's environment includes it
(with `awkward`, `vector`, `uproot` and `numpy`), so there is nothing to install. If you updated an
older clone, run `pixi install` once. The examples were written for pylhe 2.x, whose interface differs
from older versions.

Save this as `lhe_peek.py` (it reads `.lhe` and `.lhe.gz`):

```python
import sys

import awkward as ak
import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import pylhe

lhe = pylhe.LHEFile.fromfile(sys.argv[1])
proc = lhe.init.procInfo[0]
print(f"cross-section in the file: {proc.xSection:.6g} +- {proc.error:.2g} pb")

events = pylhe.to_awkward(lhe.events)              # one row per event; .particles is a jagged array
p = events.particles
tops = p[(abs(p.id) == 6) & ((p.status == 1) | (p.status == 2))]       # the top and the anti-top
pt = ak.flatten(tops.vector.pt)                    # .vector gives pt, eta, phi, mass, ... for free
w = ak.flatten(ak.broadcast_arrays(events.eventinfo.weight, tops.vector.pt)[0])   # each top gets its event's weight
pt, w = np.asarray(pt), np.asarray(w)
print(f"{len(events)} events, {len(pt)} tops, weights sum to {w.sum():.4g}, negative weights: {(w < 0).sum()}")

counts, edges = np.histogram(pt, bins=np.arange(0, 600, 25), weights=w)
hep.style.use("ROOT")
fig, ax = plt.subplots()
hep.histplot(counts, edges, ax=ax, histtype="step", label=f"{len(events)} events")
ax.set_xlabel("top quark $p_T$ [GeV]")
ax.set_ylabel("sum of event weights")
ax.legend()
fig.savefig("top_pt.png", dpi=150)
print("wrote top_pt.png")
```

```bash
pixi run python lhe_peek.py work/ttbar_lo/Events/run_01/unweighted_events.lhe.gz
```

The first line should match the cross-section you found in the file and the one MG5 printed. The
script writes `top_pt.png` (open it from your file browser, or with `open top_pt.png` on a Mac or
`xdg-open top_pt.png` on Linux). The
histogram of the top transverse momentum should rise from zero, peak at about 50-100 GeV and fall steeply.
Why does it not peak at zero? (Think about the phase space and the top mass.) All LO events have weight
+1, so there are no negative weights here. That changes at NLO.

Everything in the file is available this way: `events.particles.id`, `.status`, `.mother1`, `.vector.px`,
`.vector.E`, `events.eventinfo.weight`, and so on. Try computing the invariant mass of the top pair and its
rapidity separation, and compare with the transverse-momentum shape.

---

## 4. Run parameters: events, seed and physics inputs

Everything about *how* a run behaves is in the cards. You can change them in three ways:

1. **`set` commands** in the cards menu of `launch` (what you used above),
2. editing the card file (`work/ttbar_lo/Cards/run_card.dat`) with any text editor,
3. typing the card's number in the menu to open it in your `$EDITOR`.

Method 1 is the one to prefer: it is easy to repeat and to put in a script (see 4.4).

### 4.1 Number of events and the seed

* `nevents` is the number of **unweighted events** to produce. The statistical uncertainty on any
  histogram bin scales like 1/sqrt(N), so 20 times more events is only about 4.5 times smaller errors.
  Start small (a few thousand) while you are learning.
* `iseed` is the **random-number seed**. With `iseed = 0` MG5 picks one itself (and records it);
  any other positive number fixes it. The same seed with the same settings reproduces the same events;
  a different seed gives a statistically independent sample of the same physics.

Test that claim. *At the MG5 prompt*, launch three more runs of the same process (your section 3 run used
seed 11 too, so you repeat it once, then try two new seeds):

```
launch ttbar_lo
done
set nevents 2000
set iseed 11
done
```

then again with `set iseed 12`, and a third time with `set iseed 13`. (Each `launch` of the same directory
makes a new numbered run: `run_02`, `run_03`, ... .) Compare the first event of every run:

```bash
for r in work/ttbar_lo/Events/run_0*; do
  echo -n "$r  "
  gunzip -c $r/unweighted_events.lhe.gz | sed -n '/<event>/,/<\/event>/p;/<\/event>/q' | md5sum
done
```

Runs 01 and 02 (same seed, same settings) should print the same checksum, and the runs with seeds 12 and
13 different ones. (If 01 and 02 differ, compare their cross-sections: they should still agree closely.)
Then run `lhe_peek.py` on each and note how the histograms fluctuate within the expected `1/sqrt(N)` around one common shape. This is exactly what you
exploit to split a large production into many parallel jobs with different seeds.

### 4.2 Collider and PDF inputs

Open `work/ttbar_lo/Cards/run_card.dat` and read it. Useful entries (names as in the card):

| Parameter | Meaning | Try |
|---|---|---|
| `ebeam1`, `ebeam2` | beam energies in GeV (6500 = 13 TeV collisions) | `set ebeam1 7000`, `set ebeam2 7000` for 14 TeV |
| `nevents` | events to generate | `set nevents 5000` |
| `iseed` | random seed | `set iseed 42` |
| `pdlabel`, `lhaid` | which PDF set | LO default is MG5's built-in set |
| `dynamical_scale_choice` | renormalisation / factorisation scale | `set dynamical_scale_choice 3` |

The same file holds generation **cuts** (`ptj`, `etaj`, `mmbb`, ...). They act on the particles the
process contains, so for plain `p p > t t~` (no jets at generation) they do nothing until you add more
particles to the process.

Re-launch with `set ebeam1 7000` and `set ebeam2 7000`. By what factor does the cross-section grow from
13 to 14 TeV? Does that match what you know about the gluon luminosity at the top threshold?

### 4.3 Physics parameters (the param card)

Masses, widths and couplings live in `param_card.dat`. In the cards menu you can set them by name:

```
set mt 175
set wt 1.4
```

Changing the top mass changes the cross-section a lot. The top width `wt` matters as soon as you decay tops
with MadSpin (section 6): MadSpin reads it from the same card, and the default value belongs to the default
mass. If you change `mt` and use MadSpin, also type `set wt auto`, which makes MG5 recompute the width.

### 4.4 Put it in a script

Everything you type at the prompt can be saved in a text file and replayed, which is how you make runs
reproducible. Save this as `ttbar_lo.mg5` in the MEG directory:

```
import model sm
generate p p > t t~
output ttbar_lo_scripted -f
launch ttbar_lo_scripted
done
set nevents 2000
set iseed 21
done
```

```bash
pixi run mg5 ttbar_lo.mg5
```

`-f` overwrites an existing output directory without asking. The last two `done`s answer the two menus
(switches, then cards).

---

## 5. Adding a parton shower

The LHE events have 2 final-state coloured particles, and nothing else: no radiation, no hadrons. Real
collisions have both. Pythia8 adds them. MG5 can run Pythia8 for you as part of the same launch.

Re-launch the LO process with the shower switched on. *At the MG5 prompt*:

```
launch ttbar_lo
shower=PYTHIA8
done
set nevents 2000
set iseed 11
done
```

In the first menu `shower=PYTHIA8` replaced `shower=OFF`. After the run:

```bash
ls work/ttbar_lo/Events/run_0*/       # the newest run directory now also contains a .hepmc.gz
```

The extra file `tag_1_pythia8_events.hepmc.gz` is the showered event record in **HepMC** format.
It is much bigger than the LHE (it contains every final-state hadron). To feel the size difference:

```bash
ls -lh work/ttbar_lo/Events/run_0*/*.gz
```

Questions:

* How many particles does one event have now compared with the 2 tops of section 3? (Hint:
  `gunzip -c file.hepmc.gz | grep -c '^P '` for the whole file, divided by the number of events.)
* The shower conserves the hard-process cross-section. Does the cross-section printed for this run differ
  from the unshowered one with the same seed?

The shower is where the **radiation** that gives ttbar events extra jets comes from. Without it
there is no initial-state radiation, so the only jets in a decayed event are the b-jets (and W decay
products). You will see this in the Delphes jet multiplicity in section 8.

---

## 6. Decaying the tops with MadSpin

With `p p > t t~` the tops are final-state particles. Real tops decay almost immediately, to W b, and the
W decays to leptons or quarks. **MadSpin** decays them while keeping spin correlations.
(You can also write the decay chain into the `generate` line, but that gets expensive quickly for
complicated final states; MadSpin decays the finished events instead.)

### 6.1 Write the MadSpin card

For a **dilepton** ttbar sample (both W bosons decay to an electron or a muon plus a neutrino) the card is

```
# madspin_card.dat
set seed 11
define l+ = e+ mu+
define l- = e- mu-
define vl = ve vm
define vl~ = ve~ vm~
decay t > w+ b, w+ > l+ vl
decay t~ > w- b~, w- > l- vl~
launch
```

Write it into the process directory (from your shell, MEG directory):

```bash
cat > work/ttbar_lo/Cards/madspin_card.dat <<'EOF'
set seed 11
define l+ = e+ mu+
define l- = e- mu-
define vl = ve vm
define vl~ = ve~ vm~
decay t > w+ b, w+ > l+ vl
decay t~ > w- b~, w- > l- vl~
launch
EOF
```

(You can also type `3` in the cards menu to open `madspin_card.dat` in your editor.) The final
`launch` line is part of the card: it tells MadSpin to run.

### 6.2 Launch with MadSpin on

```
launch ttbar_lo
madspin=ON
shower=PYTHIA8
done
set nevents 2000
set iseed 11
done
```

MadSpin writes the decayed events into a **second** directory, `run_NN_decayed_1/`, next to the
production run. That is the one you want from now on (it is also the one the shower acts on):

```bash
ls work/ttbar_lo/Events/
ls work/ttbar_lo/Events/run_0*_decayed_1/
```

Open the decayed LHE and look at the particles of one event: the tops are now status `2` (intermediate), and
their decay products (`W`, `b`, `e`/`mu`, neutrinos) are in the record. Run `lhe_peek.py` on it again.

**Important physics points.**

* The cross-section MG5 reports for the decayed sample **includes the branching ratio** of the decays you
  chose. Electrons and muons only (no taus) from both W bosons is about (2 x 0.108)^2 = 4.7% of the
  inclusive top-pair cross-section. This is why the number printed is far below your section 3 value.
  It is a classic source of the "my cross-section is too small" confusion.
* The decays are in the **narrow-width approximation with spin correlations**. The `BW_cut` setting
  (`set BW_cut 15` in the card, before the `decay` lines) limits how many widths away from the pole mass the
  decaying top may be.
* If you change the top mass or width in the param card, MadSpin needs the matching width (section 4.3).
* MadSpin decays `t` and `t~` independently, which is what you want for dileptons. For lepton+jets (one
  top leptonic, one hadronic) you need two samples, one for each charge assignment, added together; listing
  a leptonic and a hadronic decay for the same particle would mix the final states.

---

## 7. ttbar at NLO

At next-to-leading order the cross-section includes one-loop virtual corrections and real emission
(`p p > t t~ g`), combined so that infrared divergences cancel. In MadGraph this is **aMC@NLO**, and it is
matched to a parton shower with the **MC@NLO** method.

### 7.1 Define the NLO process

NLO needs a model that includes the loop information. The SM version without a massive b quark is
standard for top-pair work. *At the MG5 prompt*:

```
import model loop_sm-no_b_mass
generate p p > t t~ [QCD]
output ttbar_nlo
```

`[QCD]` tells MG5 to compute the QCD corrections. This step is slower than at LO because many one-loop
diagrams are generated. The first NLO run on a machine also builds the **Ninja** loop-integral library
(`pixi run setup` already does this, so you should not see it again).

### 7.2 Launch at NLO with a shower

NLO events come out as **MC@NLO events** and need a parton shower to be physical, so you almost always
switch the shower on. You also need an NLO PDF set from LHAPDF. Fetch the one MEG uses once:

```bash
pixi run meg pdf fetch NNPDF30_nlo_as_0118
```

*At the MG5 prompt:*

```
launch ttbar_nlo
order=NLO
shower=PYTHIA8
done
set nevents 2000
set iseed 11
set lhaid 260000
done
```

* `order=NLO` is the default; it is shown so you know the alternative is `LO`.
* `lhaid 260000` selects NNPDF30_nlo_as_0118 (the set MEG uses for NLO).
* After you pick a shower in the first menu, MG5 sets the card entry `parton_shower` to match
  (`grep parton_shower work/ttbar_nlo/Cards/run_card.dat` to confirm; it must name the shower you use,
  because the MC@NLO subtraction terms depend on it. If it does not, `set parton_shower PYTHIA8`).
* NLO runs are much slower than LO. Use 1000-2000 events while you learn.

The printed cross-section should be clearly higher than your LO number. The ratio NLO/LO is called the
**K-factor**; for top pairs at the LHC it is roughly 1.5 (check yours; the LO value depends strongly
on the scale and PDF choices, so the exact ratio does too).

### 7.3 Negative weights

NLO events can have **negative weights** (from the subtractions). Re-run `lhe_peek.py` on the NLO events
(`work/ttbar_nlo/Events/run_01/events.lhe.gz`); the first line it prints reports how many events have
weight < 0. Expect of order ten percent for top-pair MC@NLO. Always histogram with the weights (as the script does), never just count events: the
statistical power of a weighted sample is lower than N suggests.

### 7.4 NLO without a shower

You can ask for `shower=OFF` at NLO. This gives you events, but they are **not** physical on their own:
they are the *S-events* and *H-events* of MC@NLO, which are only meaningful once showered with the matching
subtraction. Their cross-section is still correct (and there are also fixed-order modes, `fixed_order=ON`,
for total rates and distributions without events), but do not histogram them as if they were physics.
This is why MEG refuses `order = "NLO"` with `shower.kind = "none"`.

### 7.5 NLO with MadSpin

MadSpin works at NLO too. Add `madspin=ON` in the first menu, with the same `madspin_card.dat` in
`work/ttbar_nlo/Cards/`:

```bash
cp work/ttbar_lo/Cards/madspin_card.dat work/ttbar_nlo/Cards/madspin_card.dat
```

```
launch ttbar_nlo
order=NLO
shower=PYTHIA8
madspin=ON
done
set nevents 2000
set iseed 11
set lhaid 260000
done
```

Again the decayed events live in `Events/run_NN_decayed_1/` and the cross-section includes the branching
ratio.

### 7.6 The combinations

| | no MadSpin | MadSpin |
|---|---|---|
| **LO, no shower** | `launch` with nothing switched on | `madspin=ON` |
| **LO, Pythia8** | `shower=PYTHIA8` | `shower=PYTHIA8` and `madspin=ON` |
| **NLO, no shower** | `order=NLO`, `shower=OFF`: S/H events, not physical (7.4) | same, plus `madspin=ON` |
| **NLO, Pythia8** | `order=NLO`, `shower=PYTHIA8` | `order=NLO`, `shower=PYTHIA8`, `madspin=ON` |

Generate the six physical combinations (all but the two NLO no-shower ones) and tabulate the
cross-sections. Which numbers should agree, and which should differ by exactly a branching ratio? Which
should differ by about the K-factor?

---|---|---|---|---|
| **LO** | `shower=OFF` (default) | `madspin=ON` | `shower=PYTHIA8` | both |
| **NLO** | unphysical S/H events (7.4) | unphysical, decayed | `shower=PYTHIA8` | both |

Try at least the LO column quartet and the two physical NLO ones. Fill in a table of the cross-sections you
get. Which numbers should agree, and which should differ by exactly a branching ratio?

---

## 8. Detector simulation with Delphes

The last link: run the showered (or parton-level) events through a detector simulation. MG5 can call
Delphes itself, but the result depends on where Delphes is installed; MEG gives you a command that works
on any file:

```bash
pixi run meg delphes FILE [--card ATLAS] [-o OUTPUT.root]
```

`FILE` is an `.lhe` / `.lhe.gz` file (a parton-level detector simulation) or a `.hepmc` / `.hepmc.gz`
file (the normal case). MEG picks the right Delphes reader by looking inside the file (HepMC2 and HepMC3 are
different layouts), runs it, and tells you how many events came out. The default card is the packaged
`ATLAS` card; give `-c /path/to/your_card.tcl` for your own.

Always give `-o`, because MG5's files all have similar names:

```bash
pixi run meg delphes work/ttbar_lo/Events/run_03_decayed_1/tag_1_pythia8_events.hepmc.gz \
    -o delphes_lo_dilepton.root
```

(use your own run directory and file name; `ls` shows them). It writes `delphes_lo_dilepton.root` and a
log beside it, `delphes_lo_dilepton.log`. It refuses to overwrite a file unless you add `--force`, and
`-v` / `-q` show or hide Delphes' own output.

### 8.1 Look at the result

The file is a ROOT tree called `Delphes`. You do not need ROOT: `uproot` (installed with MEG) reads it.

```python
import uproot

f = uproot.open("delphes_lo_dilepton.root")
tree = f["Delphes"]
print(tree.num_entries, "events")
print([k for k in tree.keys() if k.endswith(".PT")])          # which object collections are there
```

The reconstructed objects are branches such as `Jet.PT`, `Electron.PT`, `Muon.PT` and `MissingET.MET`.
Each event holds a variable-length list for each, so read them as awkward arrays (installed with uproot):

```python
import awkward as ak


def branch(name):
    """Delphes calls it e.g. 'Jet.PT'; uproot may list it as 'Jet/Jet.PT'."""
    for key in (name, name.split(".")[0] + "/" + name):
        if key in tree:
            return tree[key].array(library="ak")
    raise KeyError(f"{name} not found; print tree.keys() to see what is there")


jets, ele, mu = branch("Jet.PT"), branch("Electron.PT"), branch("Muon.PT")
n_jet = ak.num(jets[jets > 30])
n_lep = ak.num(ele[ele > 25]) + ak.num(mu[mu > 25])
print("mean number of jets with pT > 30 GeV:", ak.mean(n_jet))
print("fraction with exactly two leptons (pT > 25 GeV):", ak.mean(n_lep == 2))
print("electrons and muons (all pT):", ak.sum(ak.num(ele)), ak.sum(ak.num(mu)))
```

Check three things:

1. In a dilepton sample you should find electrons *and* muons in comparable numbers: W bosons decay to
   both equally, and the detector efficiencies differ only modestly. A large imbalance, above all no
   electrons at all, means a problem with the detector card, not with the physics.
2. The number of events in the ROOT file equals the number of events you generated.
3. Compare the mean jet multiplicity of the **showered** run with the **unshowered** one (run Delphes on
   the LHE file too: `pixi run meg delphes PATH/unweighted_events.lhe.gz -o parton.root`). The showered sample should have
   clearly more jets above 30 GeV. This is the effect of the parton shower from section 5.

### 8.2 What the Delphes card does

The card (`ATLAS.tcl`, packaged in MEG under `src/meg/data/delphes/`) is a pipeline of modules: particle propagation in the magnetic field, tracking and calorimeter efficiency and
resolution, isolation, jet clustering (anti-kt with R = 0.4) and b-tagging. It is a *parametrisation*,
fast but only as good as the numbers in it. Open it and find where the electron efficiency and the jet
radius are set. What would you change to study a detector with a worse jet energy resolution?

---

## 9. The same thing, from a config file

Everything above can be done in one command from a configuration file, which is what you would use for
large productions and for reproducibility (MEG also writes a manifest with the exact versions and
settings next to the output). The file `examples/ttbar_tutorial.toml` holds the physics of this tutorial,
with the switches you have been flipping:

```bash
pixi run meg plan examples/ttbar_tutorial.toml        # what it would do, without running
pixi run meg generate examples/ttbar_tutorial.toml    # LO, no MadSpin, Pythia8, Delphes
```

Flip the switches from the command line:

```bash
# LO, MadSpin dileptons, Pythia8, Delphes
pixi run meg generate examples/ttbar_tutorial.toml --set madspin.enable=true --set 'run.name="lo_ms"'

# LO, parton level only (no shower), still passed through Delphes
pixi run meg generate examples/ttbar_tutorial.toml --set shower.kind=none --set 'run.name="lo_parton"'

# NLO with Pythia8 and MadSpin, a different seed and 5000 events
pixi run meg generate examples/ttbar_tutorial.toml --set process.order=NLO --set madspin.enable=true \
    --set run.seed=12 --set generation.events=5000 --set 'run.name="nlo_ms"'
```

Everything lands in `results/<run name>/`: the Delphes file is `detector/delphes.root` and
`manifest.json` records exactly what produced it (settings, tool versions, cross-section). `--set generation.events=...` and `--set run.seed=...` are the
config-file versions of `set nevents` and `set iseed` from section 4. Compare the cross-section MEG
prints with what you got interactively for the same settings; they should agree within the
statistical uncertainties. If you run a
configuration that MEG considers inconsistent (for example NLO without a shower) it tells you why before
starting anything.

`meg generate` does *not* re-use the process directories in `work/`: it builds its own inside
`results/<name>/`. That keeps your interactive experiments and your reproducible runs apart.

---

## 10. Exercises

1. **Statistics.** Generate LO ttbar with 500, 2000 and 8000 events (same seed). Plot (or tabulate) the
   top pT histogram of each, normalised to unit area. How does the bin-to-bin noise scale?
2. **Seeds.** Run five seeds of 2000 events. The reported cross-sections differ slightly. Compute their
   mean and their standard deviation, and compare the spread to the error MG5 prints for one run.
   (With `meg submit` you can do this in parallel; see the README section on many replicas.)
3. **Scale and PDF.** Change `dynamical_scale_choice` and the PDF at LO; at NLO do the same. Which
   calculation depends less on these choices, and why? (This is the main reason to go to NLO.)
4. **Branching ratio.** Predict the ratio of the dilepton MadSpin cross-section to the inclusive one from
   the W branching fractions. Then measure it from your runs.
5. **Spin correlations.** In the decayed events, compute the angle between the two charged leptons in
   the transverse plane (`delta phi`). Compare with a sample where the tops are decayed without
   spin correlations (hint: if you shower the undecayed section 5 sample, Pythia8 decays the tops itself,
   without them; select events with two charged leptons). Do the shapes differ?
6. **Detector.** Run Delphes on the LHE and on the showered HepMC of the same events. Which
   distributions change most (jet multiplicity, missing energy, lepton isolation)? Why?
7. **Top mass.** Repeat the dilepton run with `mt = 165, 175, 185` (remember `wt`). How does the total
   cross-section change? How does the lepton pT spectrum?

---

## 11. When something goes wrong

* **`pixi run mg5` says the toolchain is missing or unconfigured.** Run `pixi run setup` once.
* **NLO complains about a missing LHAPDF set.** `pixi run meg pdf fetch NNPDF30_nlo_as_0118`.
* **MadSpin seems to be skipped, or no `_decayed_1` directory appears.** Check that
  `madspin_card.dat` exists in the process `Cards/` before you launch, ends with `launch`, and that you
  set `madspin=ON` in the first menu. The decayed events are not in `run_NN/` but in `run_NN_decayed_1/`.
* **The cross-section is much smaller than expected.** MadSpin with specific decays includes the branching
  ratio (section 6). For a total cross-section compare against the undecayed run.
* **No `.hepmc.gz` file after launching with a shower.** Read the last lines MG5 printed and the files in
  `work/<proc>/Events/run_NN/`; a failed shower usually means the Pythia8 interface is not installed
  (`pixi run setup`).
* **`meg delphes` says the file cannot be read.** HepMC2 and HepMC3 files need different readers; MEG
  chooses by the header. If the file is truncated (a run that was interrupted) re-generate it.
* **A run takes forever.** Check `nevents` (the default is 10000) and, at NLO, lower it for learning. LO
  runs finish in minutes, NLO in tens of minutes.
* **You want a clean slate.** Delete `work/` (it only contains your interactive experiments).

Next steps: the README describes running many seeds in parallel on a batch system (`meg submit`),
UFO models beyond the Standard Model (SMEFT), and Herwig7 as the shower.
