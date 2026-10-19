#!/usr/bin/env bash
# Point MG5 at the environment's Pythia8 / LHAPDF / FastJet / Delphes and build the
# Pythia8 interface. Equivalent to the sed + `install mg5amc_py8_interface` block in
# MadLAD's mg5_build(), but against $CONDA_PREFIX instead of /usr/local.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

: "${CONDA_PREFIX:?run inside 'pixi run' / 'pixi shell'}"
MG5_BIN="$(locate_mg5)" || die "No MG5 found. Default env: 'pixi run fetch-mg5'. conda-mg5 env: is mg5_aMC on PATH?"
export MG5_BIN
log "MG5 launcher: $MG5_BIN"

MG5_DIR="$(cd "$(dirname "$(readlink -f "$MG5_BIN")")/.." && pwd)"
CFG="$MG5_DIR/input/mg5_configuration.txt"

OPTS=(
  "pythia8_path=$CONDA_PREFIX"
  "lhapdf_py3=$CONDA_PREFIX/bin/lhapdf-config"
  "fastjet=$CONDA_PREFIX/bin/fastjet-config"
  "delphes_path=$CONDA_PREFIX"
  "automatic_html_opening=False"
  "auto_update=0"
)

if [[ -w "$CFG" ]]; then
  log "Editing $CFG"
  python "$SPIKE_ROOT/scripts/set_mg5_config.py" "$CFG" "${OPTS[@]}"
else
  # Package layouts without a writable tree: let MG5 write its per-user config instead.
  warn "No writable $CFG; falling back to MG5's 'save options' (writes ~/.mg5/)."
  cmds="$(mktemp)"
  for o in "${OPTS[@]}"; do echo "set ${o%%=*} ${o#*=}"; done > "$cmds"
  echo "save options" >> "$cmds"
  "$MG5_BIN" "$cmds"
  rm -f "$cmds"
fi

if [[ -d "$MG5_DIR/HEPTools/MG5aMC_PY8_interface" ]]; then
  log "Pythia8 interface already installed."
else
  log "Installing mg5amc_py8_interface (needs network access to Launchpad)"
  cmds="$(mktemp)"; echo "install mg5amc_py8_interface" > "$cmds"
  "$MG5_BIN" "$cmds" || die "mg5amc_py8_interface install failed - this is a key spike finding, keep the log."
  rm -f "$cmds"
fi
log "MG5 configured."
