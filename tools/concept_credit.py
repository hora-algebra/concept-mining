#!/usr/bin/env python3
"""Cumulative credit for concepts that pay off only after they spread.

A concept may cost tokens when it is introduced (its definition and basic
lemmas) and save them later, when other contributions rewrite proofs to use
it. This computes, for every concept in the ledger, its account across all
later patches:

    introduced   tokens saved by the patch that introduced it (may be negative)
    later        tokens saved by later patches whose added lines mention the
                 concept, shared equally among the concepts such a patch mentions
    balance      introduced + later
    status       paid (balance > 0), open (negative but still within the
                 allowance and the window), or due (negative after the window:
                 the investment rule asks for a revert)

Rule this supports (docs/two-layer-search.md, "Budgeted investment"): a
contribution may grow the target by at most --allowance tokens if it declares
a concept; it must be paid back within --window later accepted patches.

    python3 tools/concept_credit.py --target FeitThompson [--allowance 2000 --window 10]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--allowance", type=int, default=2000)
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    patches = sorted(glob.glob(os.path.join(REPO, "lean", "patches", a.target, "*.patch")))
    verdicts = {}
    for f in glob.glob(os.path.join(REPO, "data", "ledger", "verdicts", "*.json")):
        v = json.load(open(f))
        verdicts[v.get("candidate") or os.path.basename(f)[:-5]] = v
    concepts = []  # (index, name, introduced tokens)
    saved = []
    added_text = []
    for i, p in enumerate(patches):
        cand = re.sub(r"^\d+-", "", os.path.basename(p)[:-6])
        v = verdicts.get(cand, {})
        saved.append(v.get("tokens_saved", 0) or 0)
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        added_text.append(("\n".join(l[1:] for l in lines if l.startswith("+") and not l.startswith("+++")),
                           "\n".join(l[1:] for l in lines if l.startswith("-") and not l.startswith("---"))))
        if v.get("concept"):
            concepts.append((i, v["concept"], saved[-1]))
    acct = {name: {"introduced": t, "later": 0.0, "patch": i, "users": 0} for i, name, t in concepts}
    for j in range(len(patches)):
        # a later patch uses a concept when it adds more mentions than it removes
        # (moved code mentions the name on both sides and does not count)
        def net(n):
            leaf = re.escape(n.split(".")[-1].split(" ")[0])
            add, rem = added_text[j]
            return len(re.findall(rf"\b{leaf}\b", add)) - len(re.findall(rf"\b{leaf}\b", rem))
        mentioned = [n for i, n, _ in concepts if i < j and net(n) > 0]
        for n in mentioned:
            acct[n]["later"] += saved[j] / len(mentioned)
            acct[n]["users"] += 1
    rows = []
    for n, c in acct.items():
        bal = c["introduced"] + c["later"]
        age = len(patches) - 1 - c["patch"]
        status = "paid" if bal > 0 else ("open" if age < a.window and -bal <= a.allowance else "due")
        rows.append(dict(concept=n, introduced=c["introduced"], later=round(c["later"]), later_patches=c["users"],
                         balance=round(bal), patches_since=age, status=status))
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    print("concept\tintroduced\tlater\tlater_patches\tbalance\tpatches_since\tstatus")
    for r in rows:
        print("\t".join(str(r[k]) for k in ("concept", "introduced", "later", "later_patches", "balance",
                                             "patches_since", "status")))


if __name__ == "__main__":
    main()
