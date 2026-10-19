#!/usr/bin/env bash
# PDF sets go in the content cache, keyed by name, fetched on demand.
# Usage: bash scripts/fetch_pdfs.sh [SETNAME ...]   (default: NNPDF30_nlo_as_0118, LHAPDF ID 260000)
#
# Behind a restrictive network? Set LHAPDF_MIRRORS to space-separated base URLs that serve
# <SETNAME>.tar.gz, or download the tarball in a browser and extract it into
# $MADLAD_CACHE/lhapdf/ (default ./cache/lhapdf).
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

command -v lhapdf >/dev/null || die "lhapdf not found; run inside 'pixi run'."
SETS=("$@")
[[ ${#SETS[@]} -gt 0 ]] || SETS=(NNPDF30_nlo_as_0118)

# The first is the canonical location; the others are the older paths.
read -r -a MIRRORS <<<"${LHAPDF_MIRRORS:-https://lhapdfsets.web.cern.ch/current http://lhapdfsets.web.cern.ch/lhapdfsets/current https://lhapdfsets.web.cern.ch/lhapdfsets/current}"

fetch_one() {
  local s="$1" dest="$MADLAD_CACHE/lhapdf" tmp base url code
  log "Trying: lhapdf install $s"
  # LHAPDF 6.5's CLI takes the install location as a top-level --pdfdir option.
  if lhapdf --pdfdir="$dest" install "$s" && [[ -d "$dest/$s" ]]; then return 0; fi

  warn "lhapdf's own installer failed (its message is above). Trying direct downloads with curl."
  tmp="$(mktemp)"
  for base in "${MIRRORS[@]}"; do
    url="$base/$s.tar.gz"
    code="$(curl -sS -L -m 300 -o "$tmp" -w '%{http_code}' "$url" 2>"$tmp.err" || true)"
    log "  $url -> HTTP ${code:-none}"
    if [[ "$code" == 200 ]] && tar -tzf "$tmp" >/dev/null 2>&1; then
      tar -xzf "$tmp" -C "$dest"
      rm -f "$tmp" "$tmp.err"
      [[ -d "$dest/$s" ]] && return 0
      warn "Downloaded and unpacked, but $dest/$s does not exist (unexpected archive layout)."
      return 1
    fi
    if [[ -s "$tmp.err" ]]; then warn "    curl said: $(head -c 200 "$tmp.err")"; fi
  done
  rm -f "$tmp" "$tmp.err"
  return 1
}

for s in "${SETS[@]}"; do
  if [[ -d "$MADLAD_CACHE/lhapdf/$s" ]]; then
    log "PDF set $s already cached."
  else
    log "Fetching PDF set $s into $MADLAD_CACHE/lhapdf"
    fetch_one "$s" || die "could not fetch $s. The messages above show lhapdf's own error and the HTTP status of each URL tried. Manual fallback: download $s.tar.gz from https://lhapdfsets.web.cern.ch/current/ in a browser and extract it into $MADLAD_CACHE/lhapdf/"
  fi
done
