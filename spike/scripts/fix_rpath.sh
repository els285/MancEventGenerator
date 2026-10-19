#!/usr/bin/env bash
# MG5 copies MG5aMC_PY8_interface into every run directory. The conda-packaged binary finds
# libpythia8 / libHepMC through a *relative* rpath (@loader_path/../../../lib), which only works
# from its install location, so every copy aborts with "Library not loaded: @rpath/libpythia8.dylib".
# Give the installed binary an absolute rpath to $CONDA_PREFIX/lib (macOS) so copies work anywhere.
# Idempotent. Linux does not need this; common.sh puts the env's lib dir on LD_LIBRARY_PATH.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

[[ "$(uname -s)" == Darwin ]] || exit 0
: "${CONDA_PREFIX:?run inside 'pixi run'}"
MG5_BIN="$(locate_mg5)" || exit 0
MG5_DIR="$(cd "$(dirname "$(readlink -f "$MG5_BIN")")/.." && pwd)"
BIN="$MG5_DIR/HEPTools/MG5aMC_PY8_interface/MG5aMC_PY8_interface"
[[ -f "$BIN" ]] || { log "No Pythia8 interface binary at $BIN; nothing to patch."; exit 0; }

find_tool() {  # first that exists: bare name, conda-prefixed name, then /usr/bin
  local t
  for t in "$1" "arm64-apple-darwin20.0.0-$1" "/usr/bin/$1"; do
    if command -v "$t" >/dev/null 2>&1; then command -v "$t"; return 0; fi
  done
  return 1
}
OTOOL="$(find_tool otool || true)"
INT="$(find_tool install_name_tool)" || die "install_name_tool not found (install Xcode command line tools: xcode-select --install)"

WANT="$CONDA_PREFIX/lib"
if [[ -n "$OTOOL" ]] && "$OTOOL" -l "$BIN" | grep -q "path $WANT "; then
  log "Pythia8 interface already has rpath $WANT"
  exit 0
fi

log "Adding rpath $WANT to $BIN"
out="$("$INT" -add_rpath "$WANT" "$BIN" 2>&1)" || {
  if grep -q "would duplicate" <<<"$out"; then log "rpath already present."; exit 0; fi
  die "install_name_tool failed: $out"
}
# arm64 macOS kills binaries whose signature no longer matches; re-sign ad hoc.
CODESIGN="$(find_tool codesign)" || die "codesign not found (needed after editing a binary on Apple Silicon)"
"$CODESIGN" -f -s - "$BIN" >/dev/null 2>&1 || die "codesign failed for $BIN"
log "Patched and re-signed $BIN"
