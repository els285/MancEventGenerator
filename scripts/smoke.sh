#!/usr/bin/env bash
# End-to-end smoke test, mirroring MadLAD's two detector-simulation modes:
#   lo   p p > t t~        LO, parton level  -> DelphesLHEF
#   nlo  p p > t t~ [QCD]  NLO + Pythia8     -> DelphesHepMC2
# Usage: bash scripts/smoke.sh [lo|nlo|all]
# Tunables: SEED, NB_CORE, LO_EVENTS, NLO_EVENTS, MG5_BIN, MADLAD_CACHE
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

MODE="${1:-all}"
SEED="${SEED:-1}"
NCORE="${NB_CORE:-$(nproc_safe)}"
LO_EVENTS="${LO_EVENTS:-500}"
NLO_EVENTS="${NLO_EVENTS:-200}"
LHAID=260000                     # NNPDF30_nlo_as_0118, fetched by `pixi run pdfs`
CARD="$SPIKE_ROOT/delphes/ATLAS_sim_FASTJET.tcl"
RESULTS="$SPIKE_ROOT/results/$SPIKE_ENV"

MG5_BIN="$(locate_mg5)" || die "No MG5 found (see 'pixi run check')."
export MG5_BIN
DELPHES_HEPMC="$(command -v DelphesHepMC2 || command -v DelphesHepMC || true)"
[[ -d "$MADLAD_CACHE/lhapdf/NNPDF30_nlo_as_0118" || -d "${CONDA_PREFIX:-/nonexistent}/share/LHAPDF/NNPDF30_nlo_as_0118" ]] \
  || die "PDF set NNPDF30_nlo_as_0118 missing; run 'pixi run pdfs'."

# MG5 frequently exits 0 even when a command failed, so scan the log as well.
run_mg5() {  # run_mg5 <command-file> <logfile>
  "$MG5_BIN" "$1" 2>&1 | tee "$2"
  if grep -qE "interrupted with error|Traceback \(most recent call last\)|^ERROR" "$2"; then
    die "MG5 reported an error, see $(pwd)/$2"
  fi
}

finish() {  # finish <name> <lhe-or-hepmc-label> <lhe> <root>
  python "$SPIKE_ROOT/scripts/report.py" --name "$1" --lhe "$2" --root "$3" \
    --seed "$SEED" --mg5 "$MG5_BIN" --out manifest.json
}

stage_lo() {
  log "=== LO: p p > t t~  ($LO_EVENTS events, seed $SEED, $NCORE cores) ==="
  mkdir -p "$RESULTS" && rm -rf "$RESULTS/lo" && mkdir "$RESULTS/lo" && cd "$RESULTS/lo"

  cat > proc.mg5 <<EOF
set run_mode 2
set nb_core $NCORE
import model sm
generate p p > t t~
output smoke_lo -f
EOF
  run_mg5 proc.mg5 proc.log

  python "$SPIKE_ROOT/scripts/edit_card.py" smoke_lo/Cards/run_card.dat \
    nevents="$LO_EVENTS" iseed="$SEED" "pdlabel='lhapdf'" lhaid="$LHAID"

  cat > launch.mg5 <<EOF
set run_mode 2
set nb_core $NCORE
launch smoke_lo -f
EOF
  run_mg5 launch.mg5 launch.log

  local lhe=smoke_lo/Events/run_01/unweighted_events.lhe.gz
  [[ -f "$lhe" ]] || die "no LHE file produced: $(ls smoke_lo/Events/run_01 2>&1)"
  gunzip -kf "$lhe"

  log "Delphes (LHEF) with $(basename "$CARD")"
  DelphesLHEF "$CARD" lo_delphes.root "${lhe%.gz}" 2>&1 | tee delphes.log
  finish lo "${lhe%.gz}" lo_delphes.root
}

stage_nlo() {
  log "=== NLO: p p > t t~ [QCD] + Pythia8  ($NLO_EVENTS events, seed $SEED, $NCORE cores) ==="
  [[ -n "$DELPHES_HEPMC" ]] || die "no DelphesHepMC2/DelphesHepMC in the environment"
  mkdir -p "$RESULTS" && rm -rf "$RESULTS/nlo" && mkdir "$RESULTS/nlo" && cd "$RESULTS/nlo"

  cat > proc.mg5 <<EOF
set run_mode 2
set nb_core $NCORE
import model loop_sm-no_b_mass
generate p p > t t~ [QCD]
output smoke_nlo -f
EOF
  run_mg5 proc.mg5 proc.log

  # Loose accuracy and no reweighting: this is a toolchain test, not a physics run.
  python "$SPIKE_ROOT/scripts/edit_card.py" smoke_nlo/Cards/run_card.dat \
    nevents="$NLO_EVENTS" nevt_job="$NLO_EVENTS" iseed="$SEED" req_acc=0.05 \
    "pdlabel='lhapdf'" lhaid="$LHAID" parton_shower=PYTHIA8 \
    reweight_scale=.false. reweight_pdf=.false.

  cat > launch.mg5 <<EOF
set run_mode 2
set nb_core $NCORE
launch smoke_nlo -f
EOF
  run_mg5 launch.mg5 launch.log

  local hepmc
  hepmc="$(ls smoke_nlo/Events/run_01/*.hepmc.gz 2>/dev/null | head -1 || true)"
  if [[ -z "$hepmc" ]]; then
    ls -la smoke_nlo/Events/run_01 2>&1 || true
    die "no HepMC file: the shower did not run. If MG5 launched without showering, add explicit 'shower=PYTHIA8' / 'done' lines after 'launch' in scripts/smoke.sh and keep launch.log."
  fi
  gunzip -kf "$hepmc"

  log "Delphes (HepMC) with $(basename "$CARD")"
  "$DELPHES_HEPMC" "$CARD" nlo_delphes.root "${hepmc%.gz}" 2>&1 | tee delphes.log
  finish nlo "$(ls smoke_nlo/Events/run_01/*.lhe.gz 2>/dev/null | head -1 || true)" nlo_delphes.root
}

case "$MODE" in
  lo)  stage_lo ;;
  nlo) stage_nlo ;;
  all) stage_lo; stage_nlo ;;
  *)   die "usage: smoke.sh [lo|nlo|all]" ;;
esac
log "Smoke test ($MODE) passed. Manifests are under $RESULTS/*/manifest.json"
