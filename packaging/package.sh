#!/usr/bin/env bash
# Makes the release files in dist/release/: livem_all.deb and SHA256SUMS (signed later, locally, with
# icenux-app-sign-upload.sh; the signing key never reaches GitHub).
#
# Usage: packaging/package.sh VERSION     (needs nfpm in PATH; VERSION must match VERSION in ./livem)
set -euo pipefail
umask 022
cd "$(dirname "$0")/.."

VERSION=${1:?usage: packaging/package.sh VERSION}
export VERSION
built=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' livem | head -1)
[ "$built" = "$VERSION" ] || { echo "Version in livem ($built) != $VERSION" >&2; exit 1; }
out=dist/release
rm -rf "$out" && mkdir -p "$out"

nfpm package --config packaging/nfpm.yaml --packager deb --target "$out/livem_all.deb"
(cd "$out" && sha256sum livem_all.deb > SHA256SUMS)
ls -l "$out"
