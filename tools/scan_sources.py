#!/usr/bin/env python3
"""Approximate declaration graph from Lean sources, without building anything.

This is the fallback extractor for any commit of AxiomMath/CFSG (the proof-map
data from fetch_proofmap.py is exact but tied to one commit). It reads .lean
files as text and records, for every declaration:

    name, kind, file, line, source lines, statement (binders + type)

and, for every identifier token in a declaration body that resolves to a
declaration of the scanned tree, a reference edge. Resolution is by name only
(fully qualified, or by namespace suffix under the open namespaces of the
file), so it misses references introduced by elaboration (instances, coercions,
`simp` lemmas found by the simplifier, tactic-generated terms) and may merge
overloaded short names. See docs/method.md for a comparison with the exact
data.

    python3 tools/scan_sources.py --root ~/Codes/upstream/cfsg --dir CFSG/Dihedral --out out/dihedral

Outputs (in --out): decls.tsv, edges.tsv, stats.json. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

DECL_KW = ("theorem", "lemma", "def", "abbrev", "instance", "structure", "class",
           "inductive", "opaque", "axiom", "example")
MODIFIERS = r"(?:(?:private|protected|noncomputable|partial|unsafe|nonrec|public|scoped|local)\s+)*"
ATTR = r"(?:@\[[^\]]*\]\s*)*"
DECL_RE = re.compile(rf"^{ATTR}{MODIFIERS}(?P<kw>{'|'.join(DECL_KW)})\b\s*(?P<name>[^\s:({{\[⦃]*)", re.M)
NS_RE = re.compile(r"^(namespace|section|end)\b[ \t]*([^\s]*)", re.M)
OPEN_RE = re.compile(r"^open\s+(?:scoped\s+)?([^\n]*)", re.M)
IDENT_RE = re.compile(r"[A-Za-z_Ͱ-Ͽᴀ-ᶿ℀-⅏][A-Za-z0-9_'!?Ͱ-Ͽ₀-ₜᴀ-ᶿ℀-⅏]*(?:\.[A-Za-z_Ͱ-Ͽ][A-Za-z0-9_'!?Ͱ-Ͽ₀-ₜ]*)*")
COMMENT_RE = re.compile(r"/-.*?-/|--[^\n]*", re.S)
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')


def strip_comments(src: str) -> str:
    # keep line structure so that line numbers stay valid
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    src = STRING_RE.sub(blank, src)
    return COMMENT_RE.sub(blank, src)


def statement_of(body: str) -> str:
    """Text between the declared name and `:=` / `where` / `|` at depth 0."""
    depth = 0
    for i, ch in enumerate(body):
        if ch in "([{⦃⟨":
            depth += 1
        elif ch in ")]}⦄⟩":
            depth -= 1
        elif depth == 0 and body.startswith(":=", i):
            return body[:i]
        elif depth == 0 and (body.startswith(" where", i) or body.startswith("\n  |", i)):
            return body[:i]
    return body


def parse_file(path: str, rel: str):
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    src = strip_comments(raw)
    events = []  # (offset, type, payload)
    for m in NS_RE.finditer(src):
        events.append((m.start(), m.group(1), m.group(2)))
    for m in OPEN_RE.finditer(src):
        events.append((m.start(), "open", m.group(1).split()))
    decl_ms = list(DECL_RE.finditer(src))
    for i, m in enumerate(decl_ms):
        events.append((m.start(), "decl", i))
    events.sort(key=lambda e: e[0])

    stack: list[tuple[str, str]] = []  # (kind, name)
    opens: list[str] = []
    decls = []
    line_starts = [0]
    for i, ch in enumerate(src):
        if ch == "\n":
            line_starts.append(i + 1)

    def line_of(off: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for off, typ, payload in events:
        if typ in ("namespace", "section"):
            stack.append((typ, payload))
        elif typ == "end":
            if stack:
                stack.pop()
        elif typ == "open":
            opens.extend(payload)
        else:
            m = decl_ms[payload]
            end = decl_ms[payload + 1].start() if payload + 1 < len(decl_ms) else len(src)
            # stop the body at the next namespace/section/end at column 0
            nxt = NS_RE.search(src, m.end(), end)
            if nxt:
                end = nxt.start()
            ns = ".".join(n for k, n in stack if k == "namespace" and n)
            name = m.group("name").lstrip("«").rstrip("»") if m.group("name") else ""
            kw = m.group("kw")
            if kw == "lemma":
                kw = "theorem"
            if name.startswith("_root_."):
                full = name[len("_root_."):]
            elif name:
                full = f"{ns}.{name}" if ns else name
            else:
                full = ""
            body = src[m.end():end]
            stmt = statement_of(body)
            decls.append({
                "name": full, "kind": kw, "file": rel,
                "line": line_of(m.start()), "lines": src.count("\n", m.start(), end) or 1,
                "ns": ns, "opens": list(opens), "body": body, "stmt": " ".join(stmt.split()),
            })
    return decls


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="checkout of AxiomMath/CFSG")
    ap.add_argument("--dir", action="append", required=True, help="subdirectory to scan (repeatable)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    t0 = time.time()
    files = []
    for d in a.dir:
        for dp, _, fns in os.walk(os.path.join(root, d)):
            files += [os.path.join(dp, fn) for fn in fns if fn.endswith(".lean")]
    files.sort()
    # pass 1: declarations only (bodies are dropped to keep memory small)
    decls = []
    file_span = []
    nbytes = 0
    for p in files:
        nbytes += os.path.getsize(p)
        ds = parse_file(p, os.path.relpath(p, root))
        file_span.append((p, len(decls), len(decls) + len(ds)))
        for d in ds:
            del d["body"]
        decls += ds
    t_parse = time.time() - t0

    by_full: dict[str, int] = {}
    by_last: dict[str, list[int]] = defaultdict(list)
    for i, d in enumerate(decls):
        if d["name"]:
            by_full.setdefault(d["name"], i)
            by_last[d["name"].rsplit(".", 1)[-1]].append(i)

    def resolve(tok: str, d) -> int | None:
        prefixes = []
        parts = d["ns"].split(".") if d["ns"] else []
        for k in range(len(parts), -1, -1):
            prefixes.append(".".join(parts[:k]))
        prefixes += d["opens"]
        for pre in prefixes:
            cand = f"{pre}.{tok}" if pre else tok
            if cand in by_full:
                return by_full[cand]
        # dotted access on a variable (h.foo): try the last component when unique
        last = tok.rsplit(".", 1)[-1]
        c = by_last.get(last)
        if c and len(c) == 1 and len(last) > 3:
            return c[0]
        return None

    # pass 2: re-read each file and resolve the identifiers of every body
    edges = Counter()
    for p, lo, hi in file_span:
        for i, d in zip(range(lo, hi), parse_file(p, os.path.relpath(p, root))):
            seen = set()
            for tok in IDENT_RE.findall(d["body"]):
                j = resolve(tok, decls[i])
                if j is not None and j != i and j not in seen:
                    seen.add(j)
                    edges[(i, j)] += 1
    t_total = time.time() - t0

    os.makedirs(a.out, exist_ok=True)
    indeg = Counter(j for (_, j) in edges)
    with open(os.path.join(a.out, "decls.tsv"), "w") as f:
        f.write("id\tname\tkind\tfile\tline\tlines\tin_degree\tstatement\n")
        for i, d in enumerate(decls):
            f.write(f"{i}\t{d['name']}\t{d['kind']}\t{d['file']}\t{d['line']}\t{d['lines']}\t{indeg[i]}\t{d['stmt'][:2000]}\n")
    with open(os.path.join(a.out, "edges.tsv"), "w") as f:
        f.write("src\tdst\n")
        for (i, j) in sorted(edges):
            f.write(f"{i}\t{j}\n")
    stats = {"files": len(files), "bytes": nbytes, "declarations": len(decls),
             "edges": len(edges), "seconds_parse": round(t_parse, 2), "seconds_total": round(t_total, 2)}
    with open(os.path.join(a.out, "stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats), file=sys.stderr)


if __name__ == "__main__":
    main()
