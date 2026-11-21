#!/usr/bin/env python3
"""Repeated hypothesis bundles in theorem statements (from scan_sources.py output).

A statement is split into its top-level binders: (x : T), {x : T}, [T], ⦃x : T⦄.
Two kinds of repetition are counted over all theorems:

    binder_types.tsv   a binder type T (variable names removed) and how many
                       theorems assume it
    hyp_windows.tsv    k consecutive hypotheses (explicit binders whose type
                       is a proposition, by a syntactic test; k = 3, 5),
                       compared as sets; the closest syntactic proxy for a
                       "bundle of assumptions" that keeps being restated
    prefixes.tsv       the same first k binders, verbatim up to whitespace
                       (k = 4, 6, 8), and how many theorems start with them;
                       a long prefix shared by many theorems is a context that
                       could be packaged as one structure or `variable` block

    python3 tools/bundles.py --scan out/full --out data/bundles
"""

from __future__ import annotations

import argparse
import os
import re
from collections import Counter, defaultdict

OPEN, CLOSE = "([{⦃", ")]}⦄"


def binders(stmt: str) -> list[str]:
    out, depth, start = [], 0, None
    for i, ch in enumerate(stmt):
        if ch in OPEN:
            if depth == 0:
                start = i
            depth += 1
        elif ch in CLOSE:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(stmt[start:i + 1])
                start = None
            if depth < 0:
                break
        elif depth == 0 and ch == ":" and not stmt.startswith(":=", i):
            break  # start of the conclusion
    return out


def binder_type(b: str) -> str:
    inner = b[1:-1]
    if ":" in inner and b[0] != "[":
        inner = inner.split(":", 1)[1]
    return " ".join(inner.split())


PROP_HINT = re.compile(r"[≤<≥>∈∉=≠→¬∀∃∣⊆⊂↔∧∨]|^(Is|Has|Odd|Even|Nat\.Prime|Maximal|Minimal|Nonempty)|\.(Prime|Normal|IsCyclic)")


def is_hyp(b: str) -> bool:
    if b[0] != "(" or ":" not in b:
        return False
    name, typ = b[1:-1].split(":", 1)
    typ = typ.strip()
    return name.strip().startswith("h") or bool(PROP_HINT.search(typ))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=300)
    a = ap.parse_args()
    types = Counter()
    prefixes = {k: Counter() for k in (4, 6, 8)}
    windows = {k: Counter() for k in (3, 5)}
    wex, wfold = {}, defaultdict(set)
    example = {}
    folders = defaultdict(set)
    n = 0
    with open(os.path.join(a.scan, "decls.tsv")) as f:
        next(f)
        for row in f:
            c = row.rstrip("\n").split("\t")
            if len(c) < 8 or c[2] != "theorem":
                continue
            n += 1
            bs = [" ".join(b.split()) for b in binders(c[7])]
            folder = "/".join(c[3].split("/")[:2])
            for t in {binder_type(b) for b in bs}:
                if not re.fullmatch(r"\S+ : Type\S*|Type\S*", t):
                    types[t] += 1
            hyps = [binder_type(b) for b in bs if is_hyp(b)]
            for k in windows:
                for i in range(len(hyps) - k + 1):
                    key = " ∧ ".join(sorted(set(hyps[i:i + k])))
                    if key.count(" ∧ ") == k - 1:
                        windows[k][key] += 1
                        wex.setdefault(key, c[1])
                        wfold[key].add(folder)
            for k in prefixes:
                if len(bs) >= k:
                    key = " ".join(bs[:k])
                    prefixes[k][key] += 1
                    example.setdefault(key, c[1])
                    folders[key].add(folder)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "binder_types.tsv"), "w") as w:
        w.write(f"theorems_assuming\tbinder_type\t(of {n} theorems)\n")
        for t, k in types.most_common(a.top):
            w.write(f"{k}\t{t}\n")
    with open(os.path.join(a.out, "prefixes.tsv"), "w") as w:
        w.write("k\ttheorems\tfolders\tprefix\texample\n")
        for k, cnt in prefixes.items():
            for key, m in cnt.most_common(a.top // 3):
                w.write(f"{k}\t{m}\t{len(folders[key])}\t{key[:600]}\t{example[key]}\n")
    with open(os.path.join(a.out, "hyp_windows.tsv"), "w") as w:
        w.write("k\toccurrences\tfolders\thypotheses\texample\n")
        for k, cnt in windows.items():
            for key, m in cnt.most_common(a.top // 2):
                w.write(f"{k}\t{m}\t{len(wfold[key])}\t{key[:600]}\t{wex[key]}\n")
    print(f"{n} theorems")


if __name__ == "__main__":
    main()
