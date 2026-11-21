#!/usr/bin/env python3
"""Append rows to the ledger read by the public page.

    # measure the current checkout (exports declarations with Lean, ~5 min)
    python3 tools/ledger.py measure --root ~/Codes/upstream/cfsg --prefix CFSG.FeitThompson \
        --protected data/pilot/FeitThompson/protected.txt --out out/measure.json

    python3 tools/ledger.py history --target FeitThompson --measure out/measure.json --note "baseline"
    python3 tools/ledger.py concept --target FeitThompson --concept hallCoreIn \
        --meaning "..." --before out/m0.json --after out/m1.json --uses 1234 --commit abc123

Line counts are the code lines (non-blank, outside comments) of the
declarations that the protected theorems need, as computed by tools/mine.py;
`declarations` counts those declarations.

    data/ledger/concepts.tsv  date, target, concept, meaning, lines_before,
                              lines_after, lines_saved, uses, commit
    data/ledger/history.tsv   date, target, lines_total, declarations, note
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "..", "data", "ledger")
COLS = {
    "concepts.tsv": ["date", "target", "concept", "meaning", "lines_before", "lines_after", "lines_saved", "uses", "commit"],
    "history.tsv": ["date", "target", "lines_total", "declarations", "note"],
}


def append(name: str, row: dict) -> None:
    os.makedirs(LEDGER, exist_ok=True)
    path = os.path.join(LEDGER, name)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write("\t".join(COLS[name]) + "\n")
        f.write("\t".join(str(row[c]).replace("\t", " ").replace("\n", " ") for c in COLS[name]) + "\n")


def count_uses(decls: str, name: str) -> int:
    """Number of non-auxiliary declarations whose type or value refers to the
    constant `name` (matched as a full name or a dot-suffix)."""
    import re
    aux = re.compile(r"\._|\.(match_|proof_|eq_\d|eq_def)")
    rows = [l.rstrip("\n").split("\t") for l in open(decls, encoding="utf-8")]
    targets = {r[0] for r in rows if r[0] == name or r[0].endswith("." + name)}
    n = 0
    for r in rows:
        if r[0] in targets or aux.search(r[0].replace("_private.", "", 1)) or r[3] == "0":
            continue
        if targets & set(r[8].split()):
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--root", required=True)
    m.add_argument("--prefix", required=True)
    m.add_argument("--protected", required=True)
    m.add_argument("--out", required=True)
    h = sub.add_parser("history")
    h.add_argument("--target", required=True)
    h.add_argument("--measure", required=True)
    h.add_argument("--note", default="")
    c = sub.add_parser("concept")
    for k in ("target", "concept", "meaning", "before", "after", "commit"):
        c.add_argument("--" + k, required=True)
    c.add_argument("--uses", type=int, required=True)
    u = sub.add_parser("uses", help="declarations that refer to a concept directly")
    u.add_argument("--decls", required=True)
    u.add_argument("--name", required=True)
    a = ap.parse_args()
    today = datetime.date.today().isoformat()
    if a.cmd == "measure":
        with tempfile.TemporaryDirectory() as tmp:
            decls = os.path.join(tmp, "decls.tsv")
            subprocess.run([sys.executable, os.path.join(HERE, "export_decls.py"), "--root", a.root,
                            "--prefix", a.prefix, "--out", decls], check=True)
            subprocess.run([sys.executable, os.path.join(HERE, "mine.py"), "--decls", decls, "--root", a.root,
                            "--protected", a.protected, "--out", tmp], check=True, stdout=subprocess.DEVNULL)
            base = json.load(open(os.path.join(tmp, "baseline.json")))
            os.replace(decls, a.out + ".decls.tsv")  # kept for counting uses
        json.dump(base, open(a.out, "w"), indent=2)
        print(json.dumps({k: base[k] for k in ("code_lines", "needed_code_lines", "needed_declarations")}))
    elif a.cmd == "history":
        b = json.load(open(a.measure))
        append("history.tsv", dict(date=today, target=a.target, lines_total=b["needed_code_lines"],
                                   declarations=b["needed_declarations"], note=a.note))
    elif a.cmd == "uses":
        print(count_uses(a.decls, a.name))
    else:
        b0, b1 = json.load(open(a.before)), json.load(open(a.after))
        x0, x1 = b0["needed_code_lines"], b1["needed_code_lines"]
        append("concepts.tsv", dict(date=today, target=a.target, concept=a.concept, meaning=a.meaning,
                                    lines_before=x0, lines_after=x1, lines_saved=x0 - x1, uses=a.uses,
                                    commit=a.commit))


if __name__ == "__main__":
    main()
