#!/usr/bin/env bash
# Fallback path: put a pinned MG5_aMC tarball in the content cache (not in the environment).
# Usage: MG5_VERSION=3.5.3 bash scripts/fetch_mg5_tarball.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

VERSION="${MG5_VERSION:-3.5.3}"      # 3.5.3 is what MadLAD defaults to
IFS=. read -r MAJ MIN _PATCH <<<"$VERSION"
[[ -n "${MAJ:-}" && -n "${MIN:-}" ]] || die "MG5_VERSION must look like 3.5.3"

# Same URL pattern MadLAD's container/commands.py uses.
URL="https://launchpad.net/mg5amcnlo/${MAJ}.0/${MAJ}.${MIN}.x/+download/MG5_aMC_v${VERSION}.tar.gz"
DEST="$MADLAD_CACHE/mg5"
TARBALL="$DEST/MG5_aMC_v${VERSION}.tar.gz"
SHAFILE="$SPIKE_ROOT/mg5-${VERSION}.sha256"   # commit this file once you have checked the hash

if [[ -x "$DEST/MG5_aMC_v${VERSION}/bin/mg5_aMC" ]]; then
  log "MG5 ${VERSION} already in cache."; exit 0
fi

log "Downloading $URL"
wget -q --show-progress -O "$TARBALL" "$URL" || die "download failed (is launchpad reachable from here?)"

actual="$(sha256sum "$TARBALL" | cut -d' ' -f1)"
if [[ -f "$SHAFILE" ]]; then
  expected="$(cut -d' ' -f1 "$SHAFILE")"
  [[ "$actual" == "$expected" ]] || die "sha256 mismatch for MG5 ${VERSION}: got $actual, pinned $expected"
  log "sha256 verified against $(basename "$SHAFILE")"
else
  echo "$actual  MG5_aMC_v${VERSION}.tar.gz" > "$SHAFILE"
  warn "No pinned hash existed; recorded $actual in $(basename "$SHAFILE")."
  warn "Trust-on-first-use: verify it against Launchpad, then commit the file."
fi

mkdir -p "$DEST/MG5_aMC_v${VERSION}"
tar -xzf "$TARBALL" -C "$DEST/MG5_aMC_v${VERSION}" --strip-components 1
log "Unpacked to $DEST/MG5_aMC_v${VERSION}"
