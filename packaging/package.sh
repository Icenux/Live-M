#!/usr/bin/env bash
# Makes the release files in dist/release/: livem_all.deb, the Arch package livem-VERSION-1-any.pkg.tar.zst and SHA256SUMS (signed later, locally, with
# icenux-app-sign-upload.sh; the signing key never reaches GitHub).
#
# Usage: packaging/package.sh VERSION     (needs nfpm in PATH; VERSION must match __version__ in src/livem/__init__.py)
set -euo pipefail
umask 022
cd "$(dirname "$0")/.."

VERSION=${1:?usage: packaging/package.sh VERSION}
export VERSION
built=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/livem/__init__.py | head -1)
[ "$built" = "$VERSION" ] || { echo "Version in src/livem/__init__.py ($built) != $VERSION" >&2; exit 1; }
out=dist/release
rm -rf "$out" && mkdir -p "$out"

nfpm package --config packaging/nfpm.yaml --packager deb --target "$out/livem_all.deb"
nfpm package --config packaging/nfpm.yaml --packager archlinux --target "$out/"
(cd "$out" && sha256sum livem_all.deb livem-*.pkg.tar.zst > SHA256SUMS)
ls -l "$out"
