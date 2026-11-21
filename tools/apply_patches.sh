#!/bin/sh
# Rebuild the refactored Lean sources: check out the pinned upstream commit
# and apply this repository's patches on top, one commit per concept.
#
#   tools/apply_patches.sh ~/Codes/upstream/cfsg-refactored [FeitThompson]
#
# The checkout is sparse (CFSG/ only, no certificate data) and outside this
# repository. Build it afterwards with `lake exe cache get` and `lake build`.
set -eu
dest=$1
target=${2:-FeitThompson}
here=$(cd "$(dirname "$0")/.." && pwd)
. "$here/lean/UPSTREAM"
if [ ! -d "$dest/.git" ]; then
  git clone --filter=blob:none --no-checkout "$repo" "$dest"
  git -C "$dest" sparse-checkout set --no-cone '/*' '!/CFSG/Certificates/' '!/Certificates/'
fi
git -C "$dest" checkout -q "$commit"
git -C "$dest" checkout -q -B "concept-mining/$target"
for p in "$here"/lean/patches/"$target"/*.patch; do
  [ -e "$p" ] || continue
  git -C "$dest" am -q --keep-cr "$p"
  echo "applied $(basename "$p")"
done
