#!/usr/bin/env python3
"""Concept candidates for one target, as work items an AI can pick up.

    python3 tools/candidates.py --decls out/ft_decls.tsv --root ~/Codes/upstream/cfsg \
        --target FeitThompson --out data/pilot/FeitThompson/candidates.jsonl

Two kinds, found mechanically on the elaborated declarations
(tools/export_decls.py) and the source:

  copies     definitions that are equal after identifying copies (same type
             and body up to renaming), with the lemmas whose statements then
             coincide
  bundle     a multi-line hypothesis restated verbatim (up to its name) in
             many statements: a predicate or structure waiting to be named

Each line: id, target, kind, title, summary, names, files, estimate (tokens
the change is expected to save; only used for ordering), instructions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundles import binders  # noqa: E402
from size import tokens  # noqa: E402

AUX = re.compile(r"\._|\.(match_|proof_|eq_\d|eq_def)")


def short(n):
    m = re.match(r"_private\.[\w.]+?\.0\.(.*)", n)
    n = m.group(1) if m else n
    return n.replace("CFSG.FeitThompson.", "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decls", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    D = {}
    for row in open(a.decls, encoding="utf-8"):
        c = row.rstrip("\n").split("\t")
        D[c[0]] = dict(mod=c[1], kind=c[2], s=int(c[3]), e=int(c[4]), th=c[5], uses=c[8].split(),
                       nth=c[9], canon=c[10] if c[10] not in ("", "[anonymous]") else None)
    src = {}

    def text(n):
        d = D[n]
        if d["mod"] not in src:
            p = os.path.join(root, *d["mod"].split(".")) + ".lean"
            src[d["mod"]] = open(p, encoding="utf-8").read().splitlines() if os.path.exists(p) else []
        return "\n".join(src[d["mod"]][d["s"] - 1:d["e"]])

    def path(n):
        return D[n]["mod"].replace(".", "/") + ".lean"

    user = [n for n, d in D.items() if d["s"] > 0 and not AUX.search(n.replace("_private.", "", 1))]
    users = Counter(v for n in user for v in set(D[n]["uses"]))
    out = []

    groups = defaultdict(list)
    for n in user:
        if D[n]["canon"]:
            groups[D[n]["canon"]].append(n)
    th_by = defaultdict(list)
    for n in user:
        if D[n]["kind"] == "theorem":
            th_by[D[n]["nth"]].append(n)
    for rep, copies in groups.items():
        members = [rep] + sorted(copies)
        mset = set(members)
        dup = []
        for g in th_by.values():
            if len(g) > 1 and len({D[x]["th"] for x in g}) > 1 and any(mset & set(D[x]["uses"]) for x in g):
                dup.append(sorted(g, key=lambda x: tokens(text(x))))
        est = sum(tokens(text(x)) for x in copies) + sum(tokens(text(x)) for g in dup for x in g[1:])
        uses = sum(users[x] for x in members)
        files = sorted({path(x) for x in members} | {path(x) for g in dup for x in g})
        out.append(dict(
            id=f"copies-{short(rep).replace('.', '-')}", target=a.target, kind="copies",
            title=f"One definition for {short(rep)}",
            summary=f"{len(members)} definitions with the same type and body: " + ", ".join(short(x) for x in members)
                    + f"; {len(dup)} groups of lemmas coincide once they are identified; {uses} uses.",
            names=[short(x) for x in members], files=files, estimate=est,
            instructions=(
                "Keep a single definition (in a module that every user imports; move it down the import graph "
                "if needed), delete the other copies, and make every use refer to it. Then delete lemmas that "
                "have become duplicates or trivial (`x = x`) and redirect their uses. Coinciding lemma groups: "
                + "; ".join(" = ".join(short(x) for x in g) for g in dup[:30]))))

    occ = defaultdict(list)
    for n in user:
        if D[n]["kind"] != "theorem":
            continue
        t = text(n)
        depth, end = 0, len(t)
        for i, ch in enumerate(t):
            if ch in "([{⦃⟨":
                depth += 1
            elif ch in ")]}⦄⟩":
                depth -= 1
            elif depth == 0 and t.startswith(":=", i):
                end = i
                break
        stmt = t[:end]
        if not re.match(r"\s*(@\[.*?\]\s*)?(private |protected |nonrec )*(theorem|lemma)", stmt, re.S):
            continue
        for b in binders(stmt):
            if b.startswith("(") and b.count("\n") >= 1:
                key = re.sub(r"\s+", " ", re.sub(r"^\(\s*[^:]*?:\s*", "", b, count=1)).rstrip(")")
                occ[key].append((n, tokens(b)))
    # hypotheses that occur in the same statements are one bundle
    by_set = defaultdict(list)
    for key, v in occ.items():
        if len(v) >= 5:
            by_set[frozenset(x[0] for x in v)].append(key)
    merged = {}
    for ns, keys in by_set.items():
        v = [x for k in keys for x in occ[k]]
        merged[" ; ".join(keys)] = v
    for key, v in merged.items():
        names = sorted({x[0] for x in v})
        est = sum(x[1] for x in v) - max(x[1] for x in v) - 8 * len(names)
        if est < 200:
            continue
        h = hashlib.sha1(key.encode()).hexdigest()[:8]
        out.append(dict(
            id=f"bundle-{h}", target=a.target, kind="bundle",
            title=f"Name a hypothesis restated in {len(names)} statements",
            summary=f"The hypotheses `{key[:600]}` appear together in {len(names)} statements across "
                    f"{len({D[x]['mod'] for x in names})} modules.",
            names=[short(x) for x in names], files=sorted({path(x) for x in names}), estimate=est,
            instructions=(
                "Introduce one definition or structure (with a docstring stating its mathematical meaning) that "
                "expresses this hypothesis, possibly together with hypotheses that always accompany it, state the "
                "listed theorems with it, and update their proofs and callers. If an existing structure already "
                "contains this hypothesis, reuse it instead of adding a new one.")))

    out.sort(key=lambda c: -c["estimate"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as w:
        for c in out:
            w.write(json.dumps(c, ensure_ascii=False) + "\n")
    for c in out[:15]:
        print(c["estimate"], c["kind"], c["id"], c["title"])
    print(len(out), "candidates")


if __name__ == "__main__":
    main()
