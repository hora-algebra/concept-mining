#!/bin/sh
# Independent recheck of a contribution, for CI on the main repository.
#
#   tools/ci_verify.sh <target> <work-dir>
#
# Run from a checkout of the pull request. It trusts nothing the contributor
# reports: it rebuilds the base (pinned upstream + the patches already on
# origin/main), applies the patches the pull request adds, and runs
# tools/verify.py itself. Exit 0 = accept (safe to merge automatically),
# 1 = reject, 75 = could not decide.
#
# The pull request may only add files under lean/patches/<target>/, add one
# verdict under data/ledger/verdicts/, a claim under data/claims/<target>/,
# data/pilot/<target>/measure_latest.json, and append rows to the two ledger
# tables; anything else is rejected before Lean runs.
set -eu
target=$1
work=$2
here=$(cd "$(dirname "$0")/.." && pwd)
cd "$here"
git fetch -q origin main
bad=$(git diff --name-only --diff-filter=MRT origin/main... -- . \
      ':!data/ledger/concepts.tsv' ':!data/ledger/history.tsv' ':!data/ledger/contributions.tsv' \
      ":!data/pilot/$target/measure_latest.json" || true)
added=$(git diff --name-only --diff-filter=A origin/main... -- . \
      ":!lean/patches/$target/*.patch" ':!data/ledger/verdicts/*.json' ":!data/claims/$target/*.json" || true)
deleted=$(git diff --name-only --diff-filter=D origin/main... -- . || true)
if [ -n "$bad$added$deleted" ]; then
  echo "reject: the pull request changes files outside a contribution:"; echo "$bad$added$deleted"; exit 1
fi
for t in concepts history contributions; do
  if ! git diff origin/main... -- "data/ledger/$t.tsv" | grep '^-[^-]' >/dev/null; then :; else
    echo "reject: ledger rows may only be appended ($t.tsv)"; exit 1; fi
done
new=$(git diff --name-only --diff-filter=A origin/main... -- "lean/patches/$target/" | sort)
[ -n "$new" ] || { echo "reject: no new patch"; exit 1; }
# base = pinned upstream + main's patches (from origin/main, not from the PR)
tmp=$(mktemp -d)
git archive origin/main lean tools data/pilot | tar -x -C "$tmp"
"$tmp/tools/apply_patches.sh" "$work" "$target"
base=$(git -C "$work" rev-parse HEAD)
(cd "$work" && lake exe cache get >/dev/null)
for p in $new; do git -C "$work" apply --index "$here/$p"; done
git -C "$work" reset -q
# the verifier and its data come from main, never from the pull request
status=0
python3 "$tmp/tools/verify.py" --root "$work" --base "$base" --target "$target" --json "$tmp/verdict.json" || status=$?
# the recorded token saving must match the recomputed one
for v in $(git diff --name-only --diff-filter=A origin/main... -- data/ledger/verdicts/); do
  python3 - "$tmp/verdict.json" "$v" <<'PY'
import json, sys
mine, theirs = (json.load(open(p)) for p in sys.argv[1:3])
if mine.get("tokens_saved") != theirs.get("tokens_saved"):
    sys.exit(f"reject: recorded tokens_saved {theirs.get('tokens_saved')} != recomputed {mine.get('tokens_saved')}")
PY
done
exit $status
