#!/usr/bin/env bash
# PDF sets go in the content cache, keyed by name, fetched on demand.
# Usage: bash scripts/fetch_pdfs.sh [SETNAME ...]   (default: NNPDF30_nlo_as_0118, LHAPDF ID 260000)
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

command -v lhapdf >/dev/null || die "lhapdf not found; run inside 'pixi run'."
SETS=("$@")
[[ ${#SETS[@]} -gt 0 ]] || SETS=(NNPDF30_nlo_as_0118)

for s in "${SETS[@]}"; do
  if [[ -d "$MADLAD_CACHE/lhapdf/$s" ]]; then
    log "PDF set $s already cached."
  else
    log "Fetching PDF set $s into $MADLAD_CACHE/lhapdf"
    lhapdf --dest="$MADLAD_CACHE/lhapdf" install "$s" \
      || die "could not fetch $s (needs network access to lhapdfsets.web.cern.ch)"
  fi
done
