#!/usr/bin/env python3
"""Points of contributions, as defined in docs/scoring.md (version scoring/v2).

This file is the only place where the formula lives. It is used in two ways:

    # decide on one pull request from the checker's verdict (CI)
    python3 tools/site/scoring.py verdict verdict.json

    # print the scoreboard of all accepted contributions
    python3 tools/site/scoring.py board data/ledger/contributions.tsv

`verdict` prints a JSON decision {"accepted", "points", "reasons", ...} and
exits 0 when accepted, 2 when rejected. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

VERSION = "scoring/v2"
TOKENS_PER_POINT = 100
CLEANUP_TOKENS_PER_POINT = 400
POINTS_PER_USE = 0.5
POINTS_PER_REUSE = 1.0
# the gate's checks (tools/gate/build_check.py, then the AI review), in the
# order they run; a contribution is accepted only if every one is true
CHECKS = ["paths_allowed", "applies", "no_metaprogramming", "no_shortcuts", "saves_tokens", "build",
          "protected_unchanged", "axioms_unchanged", "value_review"]
CONTRIB_COLS = ["date", "pr", "contributor", "agent", "target", "candidate", "tokens_before", "tokens_after",
                "cleanup_tokens", "lines_saved", "concepts", "reused", "upstream_commit", "head_sha"]


def parse_list(s: str) -> list[tuple[str, int]]:
    """'A:3;B:1' -> [('A', 3), ('B', 1)]. A missing count means 0."""
    out = []
    for item in (s or "").split(";"):
        item = item.strip()
        if not item:
            continue
        name, _, n = item.rpartition(":")
        if not name:
            name, n = n, "0"
        out.append((name.strip(), int(n) if n.strip().isdigit() else 0))
    return out


def shrink_points(tokens_before: int, tokens_after: int, cleanup_tokens: int) -> float:
    saved = tokens_before - tokens_after - cleanup_tokens
    return saved / TOKENS_PER_POINT + cleanup_tokens / CLEANUP_TOKENS_PER_POINT


def contribution_points(tokens_before: int, tokens_after: int, cleanup_tokens: int,
                        uses: list[int]) -> tuple[float, float]:
    """(shrink points S, concept points C) of one contribution."""
    s = shrink_points(tokens_before, tokens_after, cleanup_tokens)
    c = min(POINTS_PER_USE * sum(uses), max(s, 0.0))
    return s, c


def decide(verdict: dict) -> dict:
    reasons = list(verdict.get("reasons", []))
    checks = verdict.get("checks", {})
    failed = [c for c in CHECKS if checks.get(c) is not True]
    for c in failed:
        if not any(r.startswith(c) for r in reasons):
            reasons.append(f"{c}: check failed or missing")
    try:
        tb, ta, cl = int(verdict["tokens_before"]), int(verdict["tokens_after"]), int(verdict.get("cleanup_tokens", 0))
    except (KeyError, TypeError, ValueError):
        tb = ta = cl = 0
        reasons.append("saves_tokens: token counts missing from the verdict")
        failed.append("saves_tokens")
    uses = [int(c.get("uses", 0)) for c in verdict.get("concepts", [])]
    s, c = contribution_points(tb, ta, cl, uses)
    if s <= 0:
        reasons.append(f"positive_score: shrink points are {s:.2f}; the change must remove tokens")
    accepted = not failed and s > 0
    return {"schema": "concept-mining-decision/v1", "scoring": VERSION, "accepted": accepted,
            "pr": verdict.get("pr"), "head_sha": verdict.get("head_sha"),
            "shrink_points": round(s, 1), "concept_points": round(c, 1),
            "points": round(s + c, 1) if accepted else 0.0,
            "tokens_saved": tb - ta - cl, "cleanup_tokens": cl, "reasons": reasons}


def read_contributions(path: str) -> tuple[list[dict], list[str]]:
    """Rows of contributions.tsv and a list of problems (empty if fine)."""
    if not os.path.exists(path):
        return [], []
    rows, problems = [], []
    with open(path, newline="", encoding="utf-8") as fh:
        r = list(csv.reader(fh, delimiter="\t"))
    r = [x for x in r if any(c.strip() for c in x)]
    if not r:
        return [], []
    if [c.strip() for c in r[0]] != CONTRIB_COLS:
        return [], [f"{path}: header must be {CONTRIB_COLS}"]
    for i, x in enumerate(r[1:], start=2):
        if len(x) != len(CONTRIB_COLS):
            problems.append(f"{path}:{i}: {len(x)} fields, expected {len(CONTRIB_COLS)}")
            continue
        d = dict(zip(CONTRIB_COLS, (v.strip() for v in x)))
        try:
            for k in ("tokens_before", "tokens_after", "cleanup_tokens", "lines_saved"):
                d[k] = int(d[k])
            d["pr"] = int(d["pr"]) if d["pr"] else None   # empty for rows recorded before a pull request
            d["concepts"] = parse_list(d["concepts"])
            d["reused"] = parse_list(d["reused"])
        except ValueError:
            problems.append(f"{path}:{i}: a number column is not an integer")
            continue
        if d["tokens_before"] - d["tokens_after"] - d["cleanup_tokens"] <= 0:
            problems.append(f"{path}:{i}: tokens_saved is not positive, so this row cannot be accepted")
        d["_where"] = f"{path}:{i}"
        rows.append(d)
    return rows, problems


def board(rows: list[dict]) -> dict:
    """Scores per contribution, contributor and concept."""
    rows = sorted(rows, key=lambda d: (d["date"], d["pr"] or 0))
    author: dict[str, str] = {}
    concept = defaultdict(lambda: {"author": "", "agent": "", "first_pr": None, "uses": 0, "tokens_saved": 0,
                                   "reuse_points": 0.0, "reused_by": set()})
    person = defaultdict(lambda: {"points": 0.0, "contributions": 0, "tokens_saved": 0, "reuse_points": 0.0,
                                  "agents": set(), "concepts": set()})
    contribs = []
    for d in rows:
        uses = [n for _, n in d["concepts"]]
        s, c = contribution_points(d["tokens_before"], d["tokens_after"], d["cleanup_tokens"], uses)
        saved = d["tokens_before"] - d["tokens_after"] - d["cleanup_tokens"]
        p = person[d["contributor"]]
        p["points"] += s + c; p["contributions"] += 1; p["tokens_saved"] += saved
        p["agents"].add(d["agent"])
        total_uses = sum(uses) or 1
        for name, n in d["concepts"]:
            if name not in author:
                author[name] = d["contributor"]
                k = concept[name]
                k.update(author=d["contributor"], agent=d["agent"], first_pr=d["pr"])
                p["concepts"].add(name)
            concept[name]["uses"] += n
            concept[name]["tokens_saved"] += round(saved * n / total_uses) if sum(uses) else 0
        # reuse points: capped by this contribution's shrink points
        budget = max(s, 0.0)
        for name, n in d["reused"]:
            owner = author.get(name)
            if not owner or owner == d["contributor"] or budget <= 0:
                continue
            r = min(POINTS_PER_REUSE * n, budget)
            budget -= r
            concept[name]["reuse_points"] += r
            concept[name]["reused_by"].add(d["contributor"])
            person[owner]["reuse_points"] += r
            person[owner]["points"] += r
        contribs.append({"date": d["date"], "pr": d["pr"], "contributor": d["contributor"], "agent": d["agent"],
                         "target": d["target"], "candidate": d["candidate"], "tokens_saved": saved,
                         "lines_saved": d["lines_saved"], "points": round(s + c, 1),
                         "concepts": [n for n, _ in d["concepts"]]})
    people = sorted(({"contributor": k, "points": round(v["points"], 1), "contributions": v["contributions"],
                      "tokens_saved": v["tokens_saved"], "reuse_points": round(v["reuse_points"], 1),
                      "agents": sorted(v["agents"]), "concepts": sorted(v["concepts"])}
                     for k, v in person.items()), key=lambda x: -x["points"])
    concepts = sorted(({"concept": k, "author": v["author"], "agent": v["agent"], "first_pr": v["first_pr"],
                        "uses": v["uses"], "tokens_saved": v["tokens_saved"],
                        "reuse_points": round(v["reuse_points"], 1), "reused_by": sorted(v["reused_by"])}
                       for k, v in concept.items()), key=lambda x: (-x["tokens_saved"], -x["uses"]))
    return {"scoring": VERSION, "contributors": people, "concepts": concepts, "contributions": contribs}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verdict"); v.add_argument("file")
    b = sub.add_parser("board"); b.add_argument("file")
    a = ap.parse_args()
    if a.cmd == "verdict":
        with open(a.file, encoding="utf-8") as fh:
            dec = decide(json.load(fh))
        print(json.dumps(dec, ensure_ascii=False, indent=1))
        sys.exit(0 if dec["accepted"] else 2)
    rows, problems = read_contributions(a.file)
    for p in problems:
        print("error:", p, file=sys.stderr)
    print(json.dumps(board(rows), ensure_ascii=False, indent=1))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
