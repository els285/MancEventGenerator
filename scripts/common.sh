#!/usr/bin/env bash
# Shared helpers. Source this; do not execute it.
set -euo pipefail

SPIKE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SPIKE_ROOT

# Content cache: mutable, hash-keyed things live here, never in the environment.
export MADLAD_CACHE="${MADLAD_CACHE:-$SPIKE_ROOT/cache}"
mkdir -p "$MADLAD_CACHE"/{lhapdf,mg5,models}

# PDF sets: our cache first, then whatever the conda lhapdf package ships.
_conda_lhapdf="${CONDA_PREFIX:-}/share/LHAPDF"
export LHAPDF_DATA_PATH="$MADLAD_CACHE/lhapdf:${_conda_lhapdf}"

# Which environment are we in? (for results/ naming)
SPIKE_ENV="${PIXI_ENVIRONMENT_NAME:-default}"
export SPIKE_ENV

log()  { printf '\033[1;34m[spike]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[spike:warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[spike:error]\033[0m %s\n' "$*" >&2; exit 1; }

# Locate the MG5 launcher. Order: $MG5_BIN, newest tarball in the cache, mg5_aMC on PATH.
locate_mg5() {
  if [[ -n "${MG5_BIN:-}" ]]; then echo "$MG5_BIN"; return; fi
  local cached
  cached="$(ls -d "$MADLAD_CACHE"/mg5/MG5_aMC_v*/bin/mg5_aMC 2>/dev/null | sort -V | tail -1 || true)"
  if [[ -n "$cached" ]]; then echo "$cached"; return; fi
  if command -v mg5_aMC >/dev/null 2>&1; then command -v mg5_aMC; return; fi
  return 1
}

nproc_safe() { nproc 2>/dev/null || echo 2; }
