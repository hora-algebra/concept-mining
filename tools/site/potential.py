#!/usr/bin/env python3
"""Read and check the upper-bound map and the two-layer search results.

Formats are described in docs/potential-and-search.md:

    data/potential/blocks.tsv     folder part method lines tokens evidence
    data/search/hypotheses.jsonl  one JSON object per hypothesis (schema concept-mining-hypothesis/v1)

Used by build_site.py; also runnable to check the files:

    python3 tools/site/potential.py check
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys

POT_COLS = ["folder", "part", "method", "lines", "tokens", "evidence"]
STATUSES = ["proposed", "duplicate", "selected", "verifying", "accepted", "rejected"]
METHOD_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def read_potential(path: str) -> tuple[list[dict], list[str]]:
    if not os.path.exists(path):
        return [], []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh, delimiter="\t") if any(c.strip() for c in r)]
    if not rows:
        return [], []
    if [c.strip() for c in rows[0]] != POT_COLS:
        return [], [f"{path}: header must be {POT_COLS}"]
    out, problems = [], []
    seen = set()
    for i, r in enumerate(rows[1:], start=2):
        where = f"{path}:{i}"
        if len(r) != len(POT_COLS):
            problems.append(f"{where}: {len(r)} fields, expected {len(POT_COLS)}")
            continue
        d = dict(zip(POT_COLS, (c.strip() for c in r)))
        if not METHOD_RE.match(d["method"]):
            problems.append(f"{where}: method {d['method']!r} must be lowercase letters, digits and '-'")
            continue
        try:
            d["lines"] = int(d["lines"])
            d["tokens"] = int(d["tokens"]) if d["tokens"] else None
        except ValueError:
            problems.append(f"{where}: lines/tokens must be integers")
            continue
        if d["lines"] < 0:
            problems.append(f"{where}: negative lines")
            continue
        key = (d["folder"], d["part"], d["method"])
        if key in seen:
            problems.append(f"{where}: duplicate row for {key}")
            continue
        seen.add(key)
        d["_where"] = where
        out.append(d)
    return out, problems


def replace_method(path: str, method: str, rows: list[dict]) -> None:
    """Rewrite path with all rows of other methods kept and `method` replaced by rows."""
    old, problems = read_potential(path)
    if problems:
        raise SystemExit("\n".join(problems))
    keep = [r for r in old if r["method"] != method]
    allrows = sorted(keep + rows, key=lambda r: (r["method"], r["folder"], r["part"]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(POT_COLS) + "\n")
        for r in allrows:
            tok = "" if r.get("tokens") in (None, "") else str(r["tokens"])
            fh.write("\t".join([r["folder"], r["part"], r["method"], str(r["lines"]), tok,
                                str(r.get("evidence", "")).replace("\t", " ")]) + "\n")


def read_hypotheses(path: str) -> tuple[list[dict], list[str]]:
    if not os.path.exists(path):
        return [], []
    out, problems, ids = [], [], set()
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            where = f"{path}:{i}"
            try:
                h = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"{where}: not JSON ({e.msg})")
                continue
            if not isinstance(h, dict):
                problems.append(f"{where}: not an object")
                continue
            missing = [k for k in ("id", "concept", "status") if not h.get(k)]
            if missing:
                problems.append(f"{where}: missing {missing}")
                continue
            if h["status"] not in STATUSES:
                problems.append(f"{where}: status {h['status']!r} is not one of {STATUSES}")
                continue
            if h["id"] in ids:
                problems.append(f"{where}: duplicate id {h['id']!r}")
                continue
            ids.add(h["id"])
            prop = h.get("proposer") or {}
            pot = h.get("potential") or {}
            ver = h.get("verdict") or {}
            out.append({
                "id": str(h["id"]), "date": str(h.get("date", "")), "concept": str(h["concept"]),
                "meaning": str(h.get("meaning", "")), "status": h["status"],
                "provider": str(prop.get("provider", "")), "model": str(prop.get("model", "")),
                "viewpoint": str(prop.get("viewpoint", "")),
                "regions": [str(x) for x in h.get("regions", []) if x][:20],
                "statements": int(pot.get("statements") or 0), "tokens_est": int(pot.get("tokens") or 0),
                "candidate": str(h.get("candidate", "")), "duplicate_of": str(h.get("duplicate_of", "")),
                "accepted": ver.get("accepted"), "tokens_saved": int(ver.get("tokens_saved") or 0),
                "reasons": [str(x) for x in ver.get("reasons", [])][:5],
            })
    return out, problems


def main() -> None:
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    _, p1 = read_potential(os.path.join(root, "data/potential/blocks.tsv"))
    _, p2 = read_hypotheses(os.path.join(root, "data/search/hypotheses.jsonl"))
    for p in p1 + p2:
        print("error:", p)
    sys.exit(1 if p1 or p2 else 0)


if __name__ == "__main__":
    main()
