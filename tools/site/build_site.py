#!/usr/bin/env python3
"""Check the ledger and regenerate the data of the progress page.

Reads
    data/map/blocks.json, data/map/summary.json      (stage 1 map)
    data/ledger/concepts.tsv, data/ledger/history.tsv (refactoring ledger; may be absent)
    data/site/*.tsv, data/candidates/first_issues.tsv (page text and work board)
and writes docs/site/data/site.json.

    python3 tools/site/build_site.py            # check, then write
    python3 tools/site/build_site.py --check    # check, and fail if site.json is stale

Errors (exit status 1) are problems that make the numbers wrong: malformed
rows, lines_saved != lines_before - lines_after, unknown targets, dates in the
future. Warnings point at things worth a second look but that can be correct.
No Lean build is needed. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scoring  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

CONCEPT_COLS = ["date", "target", "concept", "meaning", "lines_before", "lines_after",
                "lines_saved", "uses", "commit"]
HISTORY_COLS = ["date", "target", "lines_total", "declarations", "note"]
WORK_STATUSES = {"open", "claimed", "in-progress", "done"}
FIELDS = [
    ("classification", "Classification proper (case analysis)"),
    ("groups", "Known simple groups"),
    ("tools", "General tools"),
    ("vocabulary", "Shared vocabulary and assembly"),
    ("certificates", "Machine-checked computations"),
    ("imported", "Imported formalizations"),
]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX_RE = re.compile(r"^[0-9a-f]{7,40}$")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def read_tsv(path: str, cols: list[str] | None, rep: Report, required: bool = True) -> list[dict]:
    rel = os.path.relpath(path, ROOT)
    if not os.path.exists(path):
        if required:
            rep.err(rel, "file is missing")
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        rep.err(rel, "no header")
        return []
    head = [c.strip() for c in rows[0]]
    if cols is not None and head != cols:
        rep.err(rel, f"header is {head}, expected {cols}")
        return []
    out = []
    for i, r in enumerate(rows[1:], start=2):
        if len(r) != len(head):
            rep.err(f"{rel}:{i}", f"{len(r)} fields, expected {len(head)}")
            continue
        d = {k: v.strip() for k, v in zip(head, r)}
        d["_where"] = f"{rel}:{i}"
        out.append(d)
    return out


def to_int(row: dict, key: str, rep: Report) -> int | None:
    v = row[key].replace(",", "")
    if not re.fullmatch(r"\d+", v):
        rep.err(row["_where"], f"{key} = {row[key]!r} is not a non-negative integer")
        return None
    return int(v)


def check_date(row: dict, rep: Report, today: dt.date) -> bool:
    d = row["date"]
    if not DATE_RE.match(d):
        rep.err(row["_where"], f"date {d!r} is not YYYY-MM-DD")
        return False
    try:
        day = dt.date.fromisoformat(d)
    except ValueError:
        rep.err(row["_where"], f"date {d!r} does not exist")
        return False
    if day > today + dt.timedelta(days=1):
        rep.err(row["_where"], f"date {d} is in the future")
        return False
    return True


def normalize_target(t: str) -> list[str]:
    """'CFSG/FeitThompson/Local', 'CFSG.FeitThompson.Local' -> ['FeitThompson', 'Local']."""
    t = t.strip().strip("/").replace("/", ".")
    if t.endswith(".lean"):
        t = t[:-5]
    parts = [p for p in t.split(".") if p]
    if parts and parts[0] == "CFSG":
        parts = parts[1:]
    return parts


def resolve(target: str, folders: dict[str, dict]) -> tuple[str, str | None] | None:
    """(folder, part or None) on the map, or None if the folder is unknown."""
    p = normalize_target(target)
    if not p:
        return None
    if p[0] == "Certificates" and target.strip().startswith("Certificates"):
        p[0] = "Certificates(top)"
    if p[0] not in folders:
        return None
    if len(p) == 1:
        return p[0], None
    names = {c["part"] for c in folders[p[0]]["parts"]}
    if p[1] in names:
        return p[0], p[1]
    merged = [c["part"] for c in folders[p[0]]["parts"] if c["part"].endswith("other parts)")]
    return p[0], (merged[0] if merged else None)


def read_json(path: str | None, rep: Report) -> list:
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, list) else []
    except (OSError, json.JSONDecodeError) as e:
        rep.warn(path, f"could not read ({e}); shown as empty")
        return []


def in_flight(claims: list, prs: list, now: float) -> list[dict]:
    """Work in progress: live claims and open pull requests that carry a target marker."""
    out = []
    for c in claims:
        if c.get("expires_at", 0) > now:
            out.append({"key": c.get("key", ""), "who": c.get("login") or c.get("owner", ""),
                        "agent": c.get("agent", ""), "kind": "claim", "until": int(c.get("expires_at", 0)),
                        "link": ""})
    marker = re.compile(r"<!--concept-mining-target:v1 (\{.*?\})-->", re.S)
    for p in prs:
        m = marker.search(p.get("body") or "")
        meta = {}
        if m:
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError:
                meta = {}
        if not m:
            continue
        out.append({"key": meta.get("candidate") or meta.get("target", ""), "who": (p.get("author") or {}).get("login", ""),
                    "agent": meta.get("agent", ""), "kind": "draft PR" if p.get("isDraft") else "PR",
                    "until": 0, "link": p.get("url", ""), "number": p.get("number")})
    return out


def build(ledger_dir: str, rep: Report, today: dt.date, claims_file: str | None = None,
          prs_file: str | None = None) -> dict:
    with open(os.path.join(ROOT, "data/map/blocks.json"), encoding="utf-8") as fh:
        blocks = json.load(fh)
    with open(os.path.join(ROOT, "data/map/summary.json"), encoding="utf-8") as fh:
        summary = json.load(fh)
    folders = {f["folder"]: f for f in blocks["folders"]}
    total_map = sum(c["lines"] for f in blocks["folders"] for c in f["parts"])
    if total_map != summary["lines_in_declarations"]:
        rep.err("data/map/blocks.json", f"total {total_map} differs from summary.json "
                f"{summary['lines_in_declarations']}")

    meta = {r["folder"]: r for r in read_tsv(os.path.join(ROOT, "data/site/folders.tsv"),
                                            ["folder", "field", "gloss"], rep)}
    field_keys = {k for k, _ in FIELDS}
    for f in folders:
        if f not in meta:
            rep.warn("data/site/folders.tsv", f"folder {f} has no field; shown as 'tools'")
        elif meta[f]["field"] not in field_keys:
            rep.err(meta[f]["_where"], f"unknown field {meta[f]['field']!r}")

    concepts = read_tsv(os.path.join(ledger_dir, "concepts.tsv"), CONCEPT_COLS, rep, required=False)
    history = read_tsv(os.path.join(ledger_dir, "history.tsv"), HISTORY_COLS, rep, required=False)

    # --- concepts -------------------------------------------------------
    good_c = []
    for r in concepts:
        ok = check_date(r, rep, today)
        nums = {k: to_int(r, k, rep) for k in ("lines_before", "lines_after", "lines_saved", "uses")}
        if any(v is None for v in nums.values()):
            ok = False
        else:
            if nums["lines_before"] - nums["lines_after"] != nums["lines_saved"]:
                rep.err(r["_where"], f"lines_saved = {nums['lines_saved']} but lines_before - lines_after = "
                        f"{nums['lines_before'] - nums['lines_after']}")
                ok = False
            if nums["lines_after"] > nums["lines_before"]:
                rep.warn(r["_where"], "the library grew (lines_after > lines_before)")
        if not r["concept"]:
            rep.err(r["_where"], "concept name is empty"); ok = False
        if not r["meaning"]:
            rep.warn(r["_where"], "meaning is empty; the page will show no explanation")
        if not HEX_RE.match(r["commit"]):
            rep.err(r["_where"], f"commit {r['commit']!r} is not a git hash"); ok = False
        loc = resolve(r["target"], folders)
        if loc is None:
            rep.err(r["_where"], f"target {r['target']!r} is not a folder of the map"); ok = False
        if ok:
            good_c.append({**{k: r[k] for k in ("date", "target", "concept", "meaning", "commit")},
                           **nums, "folder": loc[0], "part": loc[1]})

    # continuity inside each target
    by_t: dict[str, list[dict]] = defaultdict(list)
    for c in good_c:
        by_t[c["target"]].append(c)
    for t, rows in by_t.items():
        rows_sorted = sorted(rows, key=lambda c: c["date"])
        if rows_sorted != rows:
            rep.warn("data/ledger/concepts.tsv", f"rows for {t} are not in date order")
        for a, b in zip(rows_sorted, rows_sorted[1:]):
            if a["lines_after"] != b["lines_before"]:
                rep.warn("data/ledger/concepts.tsv", f"{t}: '{a['concept']}' ends at {a['lines_after']} "
                         f"lines but '{b['concept']}' starts at {b['lines_before']}")

    # --- history --------------------------------------------------------
    good_h = []
    for r in history:
        ok = check_date(r, rep, today)
        lt, de = to_int(r, "lines_total", rep), to_int(r, "declarations", rep)
        loc = resolve(r["target"], folders)
        if loc is None:
            rep.err(r["_where"], f"target {r['target']!r} is not a folder of the map"); ok = False
        if ok and lt is not None and de is not None:
            good_h.append({"date": r["date"], "target": r["target"], "lines_total": lt,
                           "declarations": de, "note": r["note"], "folder": loc[0], "part": loc[1]})
    hist_t: dict[str, list[dict]] = defaultdict(list)
    for h in good_h:
        hist_t[h["target"]].append(h)
    for t, rows in hist_t.items():
        rows.sort(key=lambda h: h["date"])
        first = rows[0]["lines_total"]
        inside = [c for c in good_c if normalize_target(c["target"])[:len(normalize_target(t))]
                  == normalize_target(t)]
        saved = sum(c["lines_saved"] for c in inside if rows[0]["date"] < c["date"] <= rows[-1]["date"])
        drop = first - rows[-1]["lines_total"]
        if saved and drop != saved:
            rep.warn("data/ledger/history.tsv", f"{t}: lines_total fell by {drop} from {rows[0]['date']} to "
                     f"{rows[-1]['date']}, but the concepts in that period saved {saved}")
    covered = [normalize_target(t) for t in hist_t]
    for t in by_t:
        nt = normalize_target(t)
        if not any(nt[:len(h)] == h for h in covered):
            rep.warn("data/ledger/history.tsv", f"no row for target {t}; the timeline uses concepts.tsv only")

    # --- snapshots of the map ------------------------------------------
    # The ledger may count lines differently from the map (for example all
    # physical lines of the .lean files rather than lines inside
    # declarations). For each folder we convert with one scale factor,
    # map lines of the folder / ledger size of the folder at its baseline.
    # The baseline is the earliest history row for the whole folder, or else
    # the largest lines_before among its concepts.
    def map_lines(f: str) -> int:
        return sum(c["lines"] for c in folders[f]["parts"])
    base: dict[str, int] = {}
    for f in {c["folder"] for c in good_c}:
        whole = sorted((h for h in good_h if h["folder"] == f and h["part"] is None), key=lambda h: h["date"])
        base[f] = whole[0]["lines_total"] if whole else max(c["lines_before"] for c in good_c if c["folder"] == f)
    dates = sorted({c["date"] for c in good_c} | {h["date"] for h in good_h})
    snapshots = []
    for d in dates:
        removed: dict[str, float] = defaultdict(float)
        for c in good_c:
            if c["date"] > d or not base.get(c["folder"]):
                continue
            f = c["folder"]
            amount = c["lines_saved"] * map_lines(f) / base[f]
            if c["part"] is None:
                for p in folders[f]["parts"]:
                    removed[f + "/" + p["part"]] += amount * p["lines"] / map_lines(f)
            else:
                removed[f + "/" + c["part"]] += amount
        for f_p in removed:
            f, part = f_p.split("/", 1)
            cap = next(p["lines"] for p in folders[f]["parts"] if p["part"] == part)
            removed[f_p] = min(removed[f_p], cap)
        snapshots.append({"date": d, "removed": {k: round(v) for k, v in sorted(removed.items())},
                          "concepts": [c["concept"] for c in good_c if c["date"] == d]})

    # --- page text and work board --------------------------------------
    stages = read_tsv(os.path.join(ROOT, "data/site/stages.tsv"), ["stage", "title", "status", "summary"], rep)
    work = read_tsv(os.path.join(ROOT, "data/site/work.tsv"), ["target", "status", "who", "link", "note"], rep)
    for w in work:
        if w["status"] not in WORK_STATUSES:
            rep.err(w["_where"], f"status {w['status']!r} is not one of {sorted(WORK_STATUSES)}")
        loc = resolve(w["target"], folders)
        if loc is None:
            rep.err(w["_where"], f"target {w['target']!r} is not a folder of the map")
        else:
            w["folder"], w["part"] = loc
    cands = read_tsv(os.path.join(ROOT, "data/candidates/first_issues.tsv"),
                     ["id", "kind", "title", "area", "evidence", "size", "status", "issue"], rep)
    for c in cands:
        if c["kind"] not in {"name", "refactor", "both"}:
            rep.err(c["_where"], f"kind {c['kind']!r} is not name, refactor or both")

    contrib_rows, problems = scoring.read_contributions(os.path.join(ledger_dir, "contributions.tsv"))
    for p in problems:
        rep.err("data/ledger/contributions.tsv", p)
    for d in contrib_rows:
        if resolve(d["target"], folders) is None:
            rep.err(d["_where"], f"target {d['target']!r} is not a folder of the map")
    scores = scoring.board(contrib_rows)
    flight = in_flight(read_json(claims_file, rep), read_json(prs_file, rep),
                       time.time())

    strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {
        "summary": {k: summary[k] for k in ("commit", "declarations", "edges", "lines_in_declarations", "final")},
        "map": {"commit": blocks.get("commit", ""), "measure": blocks.get("measure", ""),
                "fields": [{"key": k, "name": n} for k, n in FIELDS],
                "folders": [{"folder": f["folder"],
                             "field": meta.get(f["folder"], {}).get("field", "tools"),
                             "gloss": meta.get(f["folder"], {}).get("gloss", ""),
                             "parts": f["parts"]} for f in blocks["folders"]]},
        "ledger": {"concepts": good_c, "history": good_h, "baselines": base},
        "snapshots": snapshots,
        "stages": strip(stages),
        "work": strip(work),
        "candidates": strip(cands),
        "scores": scores,
        "in_flight": flight,
        "checks": {"errors": len(rep.errors), "warnings": rep.warnings},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default=os.path.join(ROOT, "data/ledger"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs/site/data/site.json"))
    ap.add_argument("--check", action="store_true", help="do not write; fail if the output is stale")
    ap.add_argument("--today", help="YYYY-MM-DD, for tests")
    ap.add_argument("--claims", help="JSON from `claim.py list --json` (deploy only)")
    ap.add_argument("--open-prs", help="JSON from `gh pr list --json number,title,author,body,url,isDraft` (deploy only)")
    ap.add_argument("--example", action="store_true",
                    help="mark the output as example data (the page shows a banner)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    rep = Report()
    data = build(a.ledger, rep, today, a.claims, a.open_prs)
    if a.example:
        data = {"example": True, **data}
    for w in rep.warnings:
        print("warning:", w)
    for e in rep.errors:
        print("error:", e)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    n_c, n_h = len(data["ledger"]["concepts"]), len(data["ledger"]["history"])
    print(f"{n_c} concepts, {n_h} history rows, {len(data['snapshots'])} snapshots, "
          f"{len(rep.errors)} errors, {len(rep.warnings)} warnings")
    if rep.errors:
        sys.exit(1)
    if a.check:
        old = open(a.out, encoding="utf-8").read() if os.path.exists(a.out) else ""
        if old != text:
            print(f"error: {os.path.relpath(a.out, ROOT)} is out of date; run python3 tools/site/build_site.py")
            sys.exit(1)
        print("site data is up to date")
        return
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote", os.path.relpath(a.out, ROOT))


if __name__ == "__main__":
    main()
