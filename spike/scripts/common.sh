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

# --- C++ standard library for MG5's Fortran link steps ----------------------------------------
# MG5's make_opts only sets LDFLAGS=$(STDLIB) (-lc++ on macOS, -lstdc++ on Linux) when LDFLAGS is
# undefined. conda's compiler activation always defines LDFLAGS, so MG5 silently drops the C++
# standard library, and linking its C++ LHAPDF wrapper (libpdf.a) with gfortran then fails with
# "Undefined symbols ... std::runtime_error::what()". Put it back.
case "$(uname -s)" in Darwin) _STDLIB="-lc++" ;; *) _STDLIB="-lstdc++" ;; esac
case " ${LDFLAGS:-} " in
  *" $_STDLIB "*) ;;
  *) export LDFLAGS="${LDFLAGS:+$LDFLAGS }$_STDLIB" ;;
esac

# --- C++ standard for MG5's bundled C++ -----------------------------------------------------------
# MG5's fjcore (jet clustering in the NLO subprocess builds) uses std::auto_ptr, which C++17 removed.
# conda's clang defaults to C++17+, so "no template named 'auto_ptr' in namespace 'std'". Build MG5's
# C++ as C++14 unless a standard was already chosen.
case " ${CXXFLAGS:-} " in
  *" -std="*) ;;
  *) export CXXFLAGS="${CXXFLAGS:+$CXXFLAGS }-std=c++14" ;;
esac

# Linux: MG5 copies the Pythia8 interface binary into run directories, so a relative rpath breaks;
# make the env's lib dir visible to the loader. (macOS is handled by scripts/fix_rpath.sh, because
# SIP strips DYLD_* variables when scripts run via /usr/bin/env.)
if [[ "$(uname -s)" == Linux && -n "${CONDA_PREFIX:-}" ]]; then
  case ":${LD_LIBRARY_PATH:-}:" in
    *":$CONDA_PREFIX/lib:"*) ;;
    *) export LD_LIBRARY_PATH="$CONDA_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
  esac
fi

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

nproc_safe() { nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2; }

# sha256 that works with GNU coreutils (Linux, or the conda env) and stock macOS.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1
  fi
}
