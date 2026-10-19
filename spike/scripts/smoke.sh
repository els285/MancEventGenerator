#!/usr/bin/env bash
# End-to-end smoke test, mirroring MadLAD's two detector-simulation modes:
#   lo   p p > t t~        LO, parton level  -> DelphesLHEF
#   lo-py8  same process, LO + Pythia8 shower via MG5's interface -> DelphesHepMC2
#   lo-hw7  same process, LO events showered by Herwig 7 (separate step) -> DelphesHepMC3
#   nlo-hw7 NLO MC@NLO events showered by Herwig 7 (separate step)      -> DelphesHepMC3
#           (the hw7 stages need the conda-herwig environment)
#   nlo  p p > t t~ [QCD]  NLO + Pythia8     -> DelphesHepMC2
# Usage: bash scripts/smoke.sh [lo|lo-py8|lo-hw7|nlo|nlo-hw7|all]
#
# Tunables (environment variables):
#   PDF_MODE     builtin (default) | lhapdf.  LO only. 'builtin' switches LHAPDF off for MG5 so the
#                run uses MG5's own PDF (nn23lo1). The NLO stage always needs LHAPDF.
#   MG5_VERBOSE  1 (default) | 0.  1 sets MG5's stdout_level to DEBUG.
#   MG5_FILTER   1 (default) | 0.  1 hides known-harmless MG5 chatter ("run_card missed argument",
#                DEBUG parameter bookkeeping) on screen only; the log files always keep everything.
#   SEED, NB_CORE, LO_EVENTS, NLO_EVENTS, MG5_BIN, MADLAD_CACHE
#
# On any failure a diag.txt is written next to the logs. Paste that file when asking for help.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

MODE="${1:-all}"
SEED="${SEED:-1}"
NCORE="${NB_CORE:-$(nproc_safe)}"
LO_EVENTS="${LO_EVENTS:-500}"
NLO_EVENTS="${NLO_EVENTS:-200}"
PDF_MODE="${PDF_MODE:-builtin}"
MG5_VERBOSE="${MG5_VERBOSE:-1}"
MG5_FILTER="${MG5_FILTER:-1}"
# Console-only filter; matches are still written to the log files.
NOISE_RE='run_card missed argument|DEBUG: (remove parameters|fix parameter value)|^$'
LHAID=260000                     # NNPDF30_nlo_as_0118, fetched by `pixi run pdfs`
CARD="$SPIKE_ROOT/delphes/ATLAS_sim_FASTJET.tcl"
RESULTS="$SPIKE_ROOT/results/$SPIKE_ENV"

[[ "$PDF_MODE" == builtin || "$PDF_MODE" == lhapdf ]] || die "PDF_MODE must be 'builtin' or 'lhapdf'"

MG5_BIN="$(locate_mg5)" || die "No MG5 found (see 'pixi run check')."
export MG5_BIN
DELPHES_HEPMC="$(command -v DelphesHepMC2 || command -v DelphesHepMC || true)"
log "MG5: $MG5_BIN | LDFLAGS for MG5 builds: ${LDFLAGS:-<unset>}"

require_pdf() {
  [[ -d "$MADLAD_CACHE/lhapdf/NNPDF30_nlo_as_0118" || -d "${CONDA_PREFIX:-/nonexistent}/share/LHAPDF/NNPDF30_nlo_as_0118" ]] \
    || die "PDF set NNPDF30_nlo_as_0118 missing; run 'pixi run pdfs'."
}

# Gather everything needed to debug a failure into <stage-dir>/diag.txt and print its path.
collect_diag() {  # collect_diag <stage-dir>
  local d="$1" out="$1/diag.txt" f t lg
  {
    echo "### diag for $(basename "$d") ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
    echo "### platform"; uname -a
    echo; echo "### environment variables that affect the build"
    env | grep -E '^(FC|F77|CC|CXX|FFLAGS|FORTRANFLAGS|CFLAGS|CXXFLAGS|CPPFLAGS|LDFLAGS|SDKROOT|CONDA_BUILD_SYSROOT|MACOSX_DEPLOYMENT_TARGET|DEVELOPER_DIR|LHAPDF_DATA_PATH|CONDA_PREFIX|PIXI_ENVIRONMENT_NAME|PDF_MODE|MG5_VERBOSE)=' | sort || true
    echo; echo "### compilers"
    for t in "${FC:-gfortran}" "${CXX:-c++}"; do
      echo "--- $t"; "$t" --version 2>&1 | head -2 || true
    done
    echo; echo "### make_opts (PDF / compiler / link settings)"
    for f in "$d"/smoke_*/Source/make_opts; do
      if [[ -f "$f" ]]; then grep -E '^(lhapdf|lhapdf_config|STDLIB|DEFAULT_|FFLAGS|CXXFLAGS|LDFLAGS)' "$f" || true; fi
    done
    for lg in proc.log launch.log herwig_read.log herwig_run.log delphes.log; do
      if [[ -f "$d/$lg" ]]; then echo; echo "### last 80 lines of $lg"; tail -80 "$d/$lg"; fi
    done
    if [[ -f "$d/hw7.in" ]]; then echo; echo "### hw7.in (the Herwig input generated from the package template)"; grep -v -E '^\s*(#|$)' "$d/hw7.in" | head -80; fi
    echo; echo "### MG5 debug log(s), first 200 lines each (the compile or link error is in here)"
    for f in "$d"/MG5_debug "$d"/smoke_*/run_*_debug.log "$d"/smoke_*/*/ME5_debug; do
      if [[ -f "$f" ]]; then echo "--- $f"; head -200 "$f"; fi
    done
    # MG5 hides the compiler output of subprocess builds. Re-run make in the first MadLoop directories
    # whose library never got built, so the real compiler/linker message ends up in this file.
    # MG5's NLO compile step (compile_dir in amcatnlo_run_interface.py) builds these targets in order
    # in each P* directory and hides the compiler output. Repeat them here and stop at the first failure.
    echo; echo "### re-running MG5's own build targets in the first process directory"
    local p t rc
    for p in "$d"/smoke_*/SubProcesses/P*/; do
      [[ -f "$p/makefile" ]] || continue
      for t in test_soft_col_limits gensym madevent_mintMC reweight_xsec_events; do
        echo "--- make $t in $p"
        rc=0; ( cd "$p" && make "$t" 2>&1 | tail -80 ; exit "${PIPESTATUS[0]}" ) || rc=$?
        if (( rc != 0 )); then echo ">>> make $t FAILED (exit $rc)"; break; fi
      done
      break
    done
    echo; echo "### re-running make where a library is missing (the compiler error, hidden by MG5, is here)"
    local v n=0
    for v in "$d"/smoke_*/SubProcesses/P*/V*/; do
      [[ -f "$v/makefile" ]] || continue
      if ls "$v"/*.a >/dev/null 2>&1; then continue; fi
      (( n++ < 2 )) || break
      echo "--- make in $v"
      ( cd "$v" && make 2>&1 | tail -80 ) || true
    done
    echo; echo "### other logs under SubProcesses that mention errors (first 5)"
    grep -l -i -E "error|undefined symbol" "$d"/smoke_*/SubProcesses/P*/*.log 2>/dev/null | head -5 || true
  } > "$out" 2>&1
  echo "$out"
}

# MG5 frequently exits 0 even when a command failed, so scan the log as well.
run_mg5() {  # run_mg5 <command-file> <logfile>   (cwd = stage dir)
  local rc=0 diag
  if [[ "$MG5_FILTER" == 1 ]]; then
    "$MG5_BIN" "$1" 2>&1 | tee "$2" | { grep --line-buffered -v -E "$NOISE_RE" || true; } || rc=$?
  else
    "$MG5_BIN" "$1" 2>&1 | tee "$2" || rc=$?
  fi
  if (( rc != 0 )) || grep -qE "interrupted with error|^ERROR" "$2"; then
    diag="$(collect_diag "$(pwd)")"
    echo >&2; warn "---- last 40 lines of $2 ----"; tail -40 "$2" >&2
    die "MG5 failed (exit status $rc). Full diagnostics, please paste this file: $diag"
  fi
}

run_logged() {  # run_logged <logfile> <command...>
  local lg="$1" rc=0 diag; shift
  "$@" 2>&1 | tee "$lg" || rc=$?
  if (( rc != 0 )); then
    diag="$(collect_diag "$(pwd)")"
    die "'$1' failed (exit status $rc). Full diagnostics, please paste this file: $diag"
  fi
  # Delphes reports parse errors as "** ERROR: ..." but still exits 0 and writes an empty tree.
  if grep -q '\*\* ERROR' "$lg"; then
    diag="$(collect_diag "$(pwd)")"
    die "'$1' exited 0 but reported: $(grep -o '\*\* ERROR.*' "$lg" | head -1). Full diagnostics: $diag"
  fi
}

mg5_header() {  # mg5_header <lhapdf|nolhapdf>: first lines of an MG5 command file
  if [[ "$MG5_VERBOSE" == 1 ]]; then echo "set stdout_level DEBUG"; fi
  echo "set run_mode 2"
  echo "set nb_core $NCORE"
  if [[ "$1" == nolhapdf ]]; then echo "set lhapdf_py3 None"; fi
}

pdf_present() {  # pdf_present <LHAPDF set name>
  [[ -d "$MADLAD_CACHE/lhapdf/$1" || -d "${CONDA_PREFIX:-/nonexistent}/share/LHAPDF/$1" ]]
}

# Shower an LHE file with Herwig 7 and write HepMC. Needs the conda-herwig environment.
#   run_herwig <package-template> <lhe-relative-to-cwd> <LHAPDF-set-of-the-events> <n-events>
# cwd = stage dir. Sets HW_HEPMC to the HepMC file it produced.
# Herwig is a two-step program: `Herwig read` turns the .in file into a .run file, `Herwig run` runs it.
run_herwig() {
  local tmpl="${CONDA_PREFIX:-}/share/Herwig/$1" lhe="$PWD/$2" pdf="$3" n="$4" runname s
  command -v Herwig >/dev/null 2>&1 || die "Herwig not found. Use the conda-herwig environment, e.g. 'pixi run -e conda-herwig smoke-lo-hw7'."
  [[ -f "$tmpl" ]] || die "Herwig template not found: $tmpl"
  [[ -f "$lhe" ]] || die "LHE file for Herwig not found: $lhe"
  for s in "$pdf" CT14lo CT14nlo; do   # CT14lo/CT14nlo are Herwig 7.3's own default PDFs
    pdf_present "$s" || die "PDF set $s is missing; run 'pixi run -e conda-herwig pdfs-hw7'."
  done

  # Build the input from Herwig's own template. Every substitution must match exactly once, so a
  # changed template fails here with a clear message instead of silently running with defaults.
  runname="$(python -I - "$tmpl" "$lhe" "$pdf" "$n" "$SEED" <<'PY'
import re, sys
tmpl, lhe, pdf, n, seed = sys.argv[1:6]
s = open(tmpl).read()
def sub(pattern, text):
    global s
    s, k = re.subn(pattern, lambda m: text, s, flags=re.M)
    if k != 1:
        sys.exit("hw7.in: %r matched %d times (expected 1); has the Herwig template changed?" % (pattern, k))
sub(r"^set LesHouchesReader:FileName .*$", "set LesHouchesReader:FileName " + lhe)
sub(r"^set /Herwig/Partons/LHAPDF:PDFName .*$", "set /Herwig/Partons/LHAPDF:PDFName " + pdf)
sub(r"^set EventGenerator:NumberOfEvents .*$", "set EventGenerator:NumberOfEvents " + n)
sub(r"^set EventGenerator:RandomNumberGenerator:Seed .*$", "set EventGenerator:RandomNumberGenerator:Seed " + seed)
m = re.search(r"^saverun (\S+) EventGenerator\s*$", s, flags=re.M)
if not m:
    sys.exit("hw7.in: no 'saverun <name> EventGenerator' line in the template")
s = s[:m.start()] + "read snippets/HepMC.in\n" + s[m.start():]   # HepMC output, before the run is saved
open("hw7.in", "w").write(s)
print(m.group(1))
PY
)" || die "could not build hw7.in from $tmpl"
  log "Herwig input hw7.in built from $(basename "$tmpl") (run name: $runname, PDF of the events: $pdf)"

  run_logged herwig_read.log Herwig read hw7.in
  [[ -f "$runname.run" ]] || die "Herwig read did not write $runname.run; see herwig_read.log"
  run_logged herwig_run.log Herwig run "$runname.run" -N "$n"

  HW_HEPMC="$(ls ./*.hepmc* 2>/dev/null | head -1 || true)"
  if [[ -z "$HW_HEPMC" ]]; then
    ls -la . >&2 || true
    die "Herwig finished but wrote no HepMC file (looked for ./*.hepmc*); see herwig_run.log"
  fi
  log "Herwig wrote $HW_HEPMC"
}

# Delphes on Herwig's HepMC. Delphes has two separate parsers: DelphesHepMC2 reads the legacy
# "IO_GenEvent" layout, DelphesHepMC3 reads HepMC3's own "Asciiv3" layout. The conda ThePEG is built
# against HepMC3 but its default output format (Format GenEvent) is the legacy layout, so choose the
# reader from the file header instead of assuming.
delphes_herwig() {  # delphes_herwig <hepmc> <root>
  local exe
  if head -5 "$1" | grep -q 'Asciiv3'; then exe=DelphesHepMC3; else exe=DelphesHepMC2; fi
  command -v "$exe" >/dev/null 2>&1 || die "$exe not found (needed for $(head -2 "$1" | tail -1))"
  log "HepMC header: $(head -2 "$1" | tail -1) -> using $exe"
  run_logged delphes.log "$(command -v "$exe")" "$CARD" "$2" "$1"
}

finish() {  # finish <name> <lhe-or-hepmc-label> <lhe> <root>
  python "$SPIKE_ROOT/scripts/report.py" --name "$1" --lhe "$2" --root "$3" \
    --seed "$SEED" --mg5 "$MG5_BIN" --out manifest.json
  python -I - manifest.json <<'PY' || die "empty or inconsistent result (see manifest.json and delphes.log)"
import json, sys
m = json.load(open(sys.argv[1]))
n = (m.get("delphes") or {}).get("entries") or 0
e = (m.get("lhe") or {}).get("events") or 0
if n <= 0:
    sys.exit("Delphes output has %s entries" % n)
if e and n != e:
    print("note: Delphes entries (%d) differ from LHE events (%d)" % (n, e))
PY
  log "Delphes ROOT file : $PWD/$3"
  log "Manifest          : $PWD/manifest.json"
}

stage_lo() {  # stage_lo [none|pythia8|herwig7]
  local shower="${1:-none}" stage=lo
  [[ "$shower" == pythia8 ]] && stage=lo_py8
  [[ "$shower" == herwig7 ]] && stage=lo_hw7
  log "=== LO: p p > t t~  shower: $shower  ($LO_EVENTS events, seed $SEED, $NCORE cores, PDFs: $PDF_MODE, verbose: $MG5_VERBOSE) ==="
  local flavour=nolhapdf
  if [[ "$PDF_MODE" == lhapdf ]]; then flavour=lhapdf; require_pdf; fi
  mkdir -p "$RESULTS" && rm -rf "$RESULTS/$stage" && mkdir "$RESULTS/$stage" && cd "$RESULTS/$stage"

  { mg5_header "$flavour"
    echo "import model sm"
    echo "generate p p > t t~"
    echo "output smoke_lo -f"
  } > proc.mg5
  run_mg5 proc.mg5 proc.log

  if [[ "$PDF_MODE" == builtin ]]; then
    if grep -qE '^lhapdf=.' smoke_lo/Source/make_opts; then
      warn "PDF_MODE=builtin, but MG5 still enabled LHAPDF (see lhapdf= in smoke_lo/Source/make_opts)."
    else
      log "LHAPDF is off for this process; MG5's built-in PDF will be used."
    fi
  fi

  local card_args=(nevents="$LO_EVENTS" iseed="$SEED")
  if [[ "$PDF_MODE" == lhapdf ]]; then card_args+=("pdlabel='lhapdf'" "lhaid=$LHAID"); fi
  python "$SPIKE_ROOT/scripts/edit_card.py" smoke_lo/Cards/run_card.dat "${card_args[@]}"

  if [[ "$shower" == pythia8 ]]; then
    # No -f: answer MG5's two menus ourselves. First menu = switches (shower on), second = cards.
    # The run card was already edited above, so both menus just get 'done'.
    { mg5_header "$flavour"; echo "launch smoke_lo"; echo "shower=Pythia8"; echo "done"; echo "done"; } > launch.mg5
  else
    { mg5_header "$flavour"; echo "launch smoke_lo -f"; } > launch.mg5
  fi
  run_mg5 launch.mg5 launch.log

  local lhe=smoke_lo/Events/run_01/unweighted_events.lhe.gz
  [[ -f "$lhe" ]] || die "no LHE file produced: $(ls smoke_lo/Events/run_01 2>&1)"
  gunzip -kf "$lhe"

  if [[ "$shower" == herwig7 ]]; then
    # The events were made with MG5's own nn23lo1 (builtin) or LHAPDF set $LHAID (lhapdf mode);
    # tell Herwig the matching LHAPDF set.
    local hwpdf=NNPDF23_lo_as_0130_qed
    if [[ "$PDF_MODE" == lhapdf ]]; then hwpdf=NNPDF30_nlo_as_0118; fi
    run_herwig LHE.in "$lhe" "$hwpdf" "$LO_EVENTS"
    log "Delphes (HepMC from Herwig) with $(basename "$CARD")"
    delphes_herwig "$HW_HEPMC" "${stage}_delphes.root"
  elif [[ "$shower" == pythia8 ]]; then
    [[ -n "$DELPHES_HEPMC" ]] || die "no DelphesHepMC2/DelphesHepMC in the environment"
    local hepmc
    hepmc="$(ls smoke_lo/Events/run_01/*.hepmc.gz 2>/dev/null | head -1 || true)"
    if [[ -z "$hepmc" ]]; then
      ls -la smoke_lo/Events/run_01 2>&1 || true
      die "no HepMC file: the Pythia8 shower did not run. Look in launch.log for 'shower' / 'pythia8' lines and for a failed 'install mg5amc_py8_interface'; smoke_lo/Events/run_01/ has the logs MG5 left."
    fi
    gunzip -kf "$hepmc"
    log "Delphes (HepMC) with $(basename "$CARD")"
    run_logged delphes.log "$DELPHES_HEPMC" "$CARD" "${stage}_delphes.root" "${hepmc%.gz}"
  else
    log "Delphes (LHEF) with $(basename "$CARD")"
    run_logged delphes.log DelphesLHEF "$CARD" "${stage}_delphes.root" "${lhe%.gz}"
  fi
  finish "$stage" "${lhe%.gz}" "${stage}_delphes.root"
}

stage_nlo() {  # stage_nlo [pythia8|herwig7]
  local shower="${1:-pythia8}" stage=nlo ps=PYTHIA8
  if [[ "$shower" == herwig7 ]]; then stage=nlo_hw7; ps=HERWIGPP; fi   # run-card name for Herwig 7's MC counterterms
  log "=== NLO: p p > t t~ [QCD] + $shower  ($NLO_EVENTS events, seed $SEED, $NCORE cores, verbose: $MG5_VERBOSE) ==="
  if [[ "$shower" == pythia8 ]]; then [[ -n "$DELPHES_HEPMC" ]] || die "no DelphesHepMC2/DelphesHepMC in the environment"; fi
  require_pdf    # NLO always needs LHAPDF; PDF_MODE only applies to the LO stage
  mkdir -p "$RESULTS" && rm -rf "$RESULTS/$stage" && mkdir "$RESULTS/$stage" && cd "$RESULTS/$stage"

  { mg5_header lhapdf
    echo "import model loop_sm-no_b_mass"
    echo "generate p p > t t~ [QCD]"
    echo "output smoke_nlo -f"
  } > proc.mg5
  run_mg5 proc.mg5 proc.log

  # Loose accuracy and no reweighting: this is a toolchain test, not a physics run.
  # parton_shower selects which shower's MC counterterms are in the events, so for an external
  # Herwig 7 shower it must be HERWIGPP even though MG5 itself does not run the shower.
  python "$SPIKE_ROOT/scripts/edit_card.py" smoke_nlo/Cards/run_card.dat \
    nevents="$NLO_EVENTS" nevt_job="$NLO_EVENTS" iseed="$SEED" req_acc=0.05 \
    "pdlabel='lhapdf'" lhaid="$LHAID" parton_shower="$ps" \
    reweight_scale=.false. reweight_pdf=.false.

  # No -f: answer MG5's menus explicitly (switches, then cards).
  if [[ "$shower" == herwig7 ]]; then
    { mg5_header lhapdf; echo "launch smoke_nlo"; echo "shower=OFF"; echo "done"; echo "done"; } > launch.mg5
  else
    { mg5_header lhapdf; echo "launch smoke_nlo"; echo "shower=PYTHIA8"; echo "done"; echo "done"; } > launch.mg5
  fi
  run_mg5 launch.mg5 launch.log

  if [[ "$shower" == herwig7 ]]; then
    local lhe
    lhe="$(ls smoke_nlo/Events/run_01/*.lhe.gz 2>/dev/null | head -1 || true)"
    if [[ -z "$lhe" ]]; then
      ls -la smoke_nlo/Events/run_01 2>&1 || true
      die "no LHE file from the NLO run (looked for smoke_nlo/Events/run_01/*.lhe.gz)."
    fi
    run_herwig LHE-MCatNLO.in "$lhe" NNPDF30_nlo_as_0118 "$NLO_EVENTS"
    log "Delphes (HepMC from Herwig) with $(basename "$CARD")"
    delphes_herwig "$HW_HEPMC" "${stage}_delphes.root"
    finish "$stage" "$lhe" "${stage}_delphes.root"
    return
  fi

  local hepmc
  hepmc="$(ls smoke_nlo/Events/run_01/*.hepmc.gz 2>/dev/null | head -1 || true)"
  if [[ -z "$hepmc" ]]; then
    ls -la smoke_nlo/Events/run_01 2>&1 || true
    die "no HepMC file: the shower did not run. If MG5 launched without showering, add explicit 'shower=PYTHIA8' / 'done' lines after 'launch' in scripts/smoke.sh and keep launch.log."
  fi
  gunzip -kf "$hepmc"

  log "Delphes (HepMC) with $(basename "$CARD")"
  run_logged delphes.log "$DELPHES_HEPMC" "$CARD" nlo_delphes.root "${hepmc%.gz}"
  finish nlo "$(ls smoke_nlo/Events/run_01/*.lhe.gz 2>/dev/null | head -1 || true)" nlo_delphes.root
}

case "$MODE" in
  lo)  stage_lo none ;;
  lo-py8) stage_lo pythia8 ;;
  lo-hw7) stage_lo herwig7 ;;
  nlo) stage_nlo pythia8 ;;
  nlo-hw7) stage_nlo herwig7 ;;
  all) stage_lo none; stage_nlo pythia8 ;;
  *)   die "usage: smoke.sh [lo|lo-py8|lo-hw7|nlo|nlo-hw7|all]" ;;
esac
log "Smoke test ($MODE) passed. Manifests are under $RESULTS/*/manifest.json"
