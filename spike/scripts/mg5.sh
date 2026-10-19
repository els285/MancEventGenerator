#!/usr/bin/env bash
# Open MG5 by hand, inside the environment, with the same settings the smoke tests use
# (LDFLAGS fix, MG5 configured for the env's Pythia8/LHAPDF/Delphes).
#
#   pixi run -e conda-mg5 mg5                 interactive mg5_aMC prompt
#   pixi run -e conda-mg5 mg5 my_cmds.mg5     run a command file (relative paths are resolved
#                                             from where you ran pixi)
# MG5 writes its output (PROC_*, py.py, ...) into ./work/ (override with MG5_WORKDIR).
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

MG5_BIN="$(locate_mg5)" || die "No MG5 found (see 'pixi run check')."
ORIG="$PWD"
WORKDIR="${MG5_WORKDIR:-$SPIKE_ROOT/work}"
mkdir -p "$WORKDIR"

args=()
for a in "$@"; do
  if [[ "$a" != -* && -e "$ORIG/$a" ]]; then args+=("$ORIG/$a"); else args+=("$a"); fi
done

cd "$WORKDIR"
log "MG5: $MG5_BIN | working directory: $WORKDIR | LDFLAGS: ${LDFLAGS:-<unset>}"
exec "$MG5_BIN" "${args[@]}"
