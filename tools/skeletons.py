#!/usr/bin/env python3
"""Proofs with the same shape, across all of CFSG (source level, no build).

For every top-level declaration it computes two fingerprints of its token
sequence (tools/size.py tokenizer, comments removed):

  copy   local names (binders, hypotheses, `have` names) renamed by position,
         global names kept: two declarations with the same `copy` print are
         the same proof under another name
  shape  every identifier and number abstracted, Lean keywords and tactic
         names kept: the same argument run on different objects (another
         group, another prime, another case of a classification)

and writes, per region (the first two folders under CFSG/), how many lines
sit in groups of copies and in families of the same shape, with an estimate
of what an ideal abstraction could remove (see docs/compression-map.md).

    python3 tools/skeletons.py --root ~/Codes/upstream/cfsg --out data/map/skeletons
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from size import TOKEN, strip_comments  # noqa: E402

DECL = re.compile(
    r"^(?:@\[[^\n]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec|partial|unsafe)\s+)*"
    r"(theorem|lemma|def|abbrev|instance|structure|class|inductive)\b", re.M)
KEYWORDS = set("""
theorem lemma def abbrev instance structure class inductive where extends deriving
by fun λ have show from at with in let if then else match do return
intro intros rintro exact apply refine refine' rw rwa erw simp simp_all simpa dsimp norm_num
omega decide linarith nlinarith positivity ring ring_nf field_simp gcongr calc obtain rcases cases
induction constructor use exists left right exfalso contradiction absurd trivial rfl assumption
subst ext funext congr convert unfold specialize generalize by_contra by_cases push_neg push
choose lift norm_cast exact_mod_cast push_cast aesop tauto infer_instance haveI letI suffices
all_goals any_goals first try repeat iterate fin_cases interval_cases nth_rw conv lhs rhs
on_goal case next skip native_decide sorry Type Prop Sort fun_prop bound
""".split())


def split_decls(src: str):
    src = strip_comments(src)
    starts = [m.start() for m in DECL.finditer(src)]
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(src)
        # stop at the next column-0 command that is not a continuation
        m = re.compile(r"\n(?=(?:end|namespace|section|open|variable|universe|set_option|attribute|#)\b)").search(src, s, e)
        yield src[s:m.start() if m else e]


def fingerprint(text: str):
    toks = TOKEN.findall(text)
    if len(toks) < 25:
        return None
    lines = sum(1 for l in text.splitlines() if l.strip())
    # local names: identifiers introduced as binders or by have/obtain/intro
    local = {}
    for m in re.finditer(r"[\(\{⦃\[]\s*((?:[^\s:()\[\]{}⦃⦄]+\s+)*[^\s:()\[\]{}⦃⦄]+)\s*:", text):
        for n in m.group(1).split():
            local.setdefault(n, f"v{len(local)}")
    for m in re.finditer(r"\b(?:have|obtain|intro|rintro|fun|set)\s+([\w'₀-₉]+)", text):
        local.setdefault(m.group(1), f"v{len(local)}")
    m = re.search(r"\b(?:theorem|lemma|def|abbrev|instance|structure|class|inductive)\s+([^\s:(\[{]+)", text)
    first = m.group(1) if m else ""
    k = next((i for i, t in enumerate(toks) if t == first), 1)
    body = toks[k + 1:]  # drop modifiers, keyword and the declaration's own name
    copy = " ".join(local.get(t, t) for t in body)
    shape = " ".join(t if (t in KEYWORDS or not (t[0].isalpha() or t[0] == "_" or t[0].isdigit())) else
                     ("n" if t[0].isdigit() else "x") for t in body)
    # loose: only the sequence of tactic names, i.e. the outline of the argument
    tactics = [t for t in body if t in KEYWORDS and t not in ("Type", "Prop", "Sort", "fun", "λ", "in", "at", "with", "from")]
    loose = " ".join(tactics) if len(tactics) >= 8 else None
    # statement: tokens before the first top-level `:=`, local names renamed
    depth, cut = 0, len(body)
    for i, t in enumerate(body):
        if t in "([{⦃⟨":
            depth += 1
        elif t in ")]}⦄⟩":
            depth -= 1
        elif t == ":=" and depth == 0:
            cut = i
            break
    stmt_toks = [local.get(t, t) for t in body[:cut]]
    stmt = " ".join(stmt_toks) if len(stmt_toks) >= 15 and re.search(r"\b(theorem|lemma)\b", text[:200]) else None
    proof = text.split(":=", 1)[1] if ":=" in text else ""
    plines = sum(1 for l in proof.splitlines() if l.strip())
    h = lambda s: hashlib.blake2b(s.encode(), digest_size=10).hexdigest()
    return dict(name=first, lines=lines, proof_lines=plines, tokens=len(toks), copy=h(copy), shape=h(shape),
                loose=h(loose) if loose else None, stmt=h(stmt) if stmt else None)


def scan_file(args):
    root, path = args
    rel = os.path.relpath(path, os.path.join(root, "CFSG"))
    parts = rel.split(os.sep)
    region = ".".join(parts[:2]).removesuffix(".lean") if len(parts) > 2 else parts[0].removesuffix(".lean")
    out = []
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for text in split_decls(src):
        f = fingerprint(text)
        if f:
            f["region"] = region
            f["file"] = rel
            out.append(f)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--decls-out", default="out/skeleton_decls.tsv.gz", help="per-declaration table (large)")
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    files = []
    for d, _, fs in os.walk(os.path.join(root, "CFSG")):
        if "/Certificates" in d:
            continue
        files += [(root, os.path.join(d, f)) for f in fs if f.endswith(".lean")]
    decls = []
    with Pool(a.jobs) as p:
        for i, r in enumerate(p.imap_unordered(scan_file, files, chunksize=200)):
            decls += r
            if i % 20000 == 0:
                print(f"{i}/{len(files)} files", file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    import gzip
    with gzip.open(a.decls_out, "wt", encoding="utf-8") as w:
        w.write("region\tfile\tname\tlines\tproof_lines\ttokens\tcopy\tshape\tloose\tstmt\n")
        for d in decls:
            w.write(f"{d['region']}\t{d['file']}\t{d['name']}\t{d['lines']}\t{d['proof_lines']}\t{d['tokens']}\t"
                    f"{d['copy']}\t{d['shape']}\t{d['loose'] or ''}\t{d['stmt'] or ''}\n")
    R = defaultdict(lambda: defaultdict(int))
    by_copy, by_shape, by_loose = defaultdict(list), defaultdict(list), defaultdict(list)
    for i, d in enumerate(decls):
        by_copy[d["copy"]].append(i)
        by_shape[d["shape"]].append(i)
        if d["loose"]:
            by_loose[d["loose"]].append(i)
    # loose families: same outline of tactics; an upper bound, since the same
    # outline can hide different mathematics
    for g in by_loose.values():
        if len(g) < 3:
            continue
        L = sorted(decls[i]["proof_lines"] for i in g)[len(g) // 2]
        save = sum(max(0, decls[i]["proof_lines"] - 1) for i in g) - L
        for i in g:
            R[decls[i]["region"]]["loose_removable"] += save / len(g)
    for d in decls:
        R[d["region"]]["decls"] += 1
        R[d["region"]]["lines"] += d["lines"]
    # copies: all but one member of each group is removable
    for g in by_copy.values():
        if len(g) > 1:
            keep = max(g, key=lambda i: 0)
            for i in g:
                if i != keep:
                    R[decls[i]["region"]]["copy_removable"] += decls[i]["lines"]
    # shape families (>= 2 members): one general theorem keeps one proof; each
    # member keeps its statement and a one-line instantiation
    fam_rows = []
    for key, g in by_shape.items():
        if len(g) < 2:
            continue
        L = sorted(decls[i]["proof_lines"] for i in g)[len(g) // 2]
        save = sum(max(0, decls[i]["proof_lines"] - 1) for i in g) - L
        regions = defaultdict(int)
        for i in g:
            regions[decls[i]["region"]] += 1
            R[decls[i]["region"]]["shape_lines"] += decls[i]["lines"]
        for r, k in regions.items():
            R[r]["shape_removable"] += save * k / len(g)
        ex = decls[g[0]]
        fam_rows.append((save, len(g), len(regions), L, ex["name"], ex["file"], key,
                         " ; ".join(sorted({decls[i]["name"] for i in g})[:8])))
    fam_rows.sort(key=lambda r: -r[0])
    with open(os.path.join(a.out, "families.tsv"), "w") as w:
        w.write("removable_lines\tmembers\tregions\tmedian_proof_lines\texample\tfile\tshape\tnames\n")
        for r in fam_rows[:3000]:
            w.write("\t".join(str(x) for x in r) + "\n")
    with open(os.path.join(a.out, "regions.tsv"), "w") as w:
        w.write("region\tdecls\tlines\tcopy_removable\tshape_lines\tshape_removable\tshape_share\tloose_removable\tloose_share\n")
        for r, c in sorted(R.items(), key=lambda x: -x[1]["lines"]):
            ub = c["shape_removable"] / max(1, c["lines"])  # copies are same-shape families too
            lb = c["loose_removable"] / max(1, c["lines"])
            w.write(f"{r}\t{c['decls']}\t{c['lines']}\t{c['copy_removable']}\t{c['shape_lines']}\t"
                    f"{int(c['shape_removable'])}\t{ub:.3f}\t{int(c['loose_removable'])}\t{lb:.3f}\n")
    tot = defaultdict(float)
    for c in R.values():
        for k, v in c.items():
            tot[k] += v
    json.dump({k: int(v) for k, v in tot.items()} | {"families": len(fam_rows)},
              open(os.path.join(a.out, "summary.json"), "w"), indent=2)
    print(json.dumps({k: int(v) for k, v in tot.items()}))


if __name__ == "__main__":
    main()
