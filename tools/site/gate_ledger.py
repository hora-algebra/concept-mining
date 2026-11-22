#!/usr/bin/env python3
"""Rows of contributions.tsv for the contributions the gate accepted.

    python3 tools/site/gate_ledger.py --repo OWNER/NAME --ledger data/ledger --out DIR

Since the contribution gate (docs/gate.md), contributors no longer write
ledger rows: the gate's comment on each pull request ends with a record of
what it measured. This script copies the ledger to DIR and appends one row
per merged pull request whose record says `accepted` for the exact commit
that was merged. Only comments by the Actions bot are read, so nobody else
can add or change a row. Needs GH_TOKEN (read access).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "gate"))
import common  # noqa: E402
import scoring  # noqa: E402

BOT = "github-actions[bot]"


def gh_json(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return json.loads(r.stdout or "null")


def rows(repo: str) -> list[list[str]]:
    # the pull list itself, not the search index (which lags and caps results)
    pages = gh_json("api", "--paginate", "--slurp", f"repos/{repo}/pulls?state=closed&per_page=100")
    merged = sorted((p for page in pages for p in page if p.get("merged_at")
                     and any(l["name"] == "contribution" for l in p.get("labels", []))), key=lambda p: p["number"])
    out = []
    for item in merged:
        n = item["number"]
        pr = gh_json("api", f"repos/{repo}/pulls/{n}")
        pages = gh_json("api", "--paginate", "--slurp", f"repos/{repo}/issues/{n}/comments?per_page=100")
        meta = None
        for c in (c for p in pages for c in p):
            if c["user"]["login"] == BOT and common.COMMENT_MARKER in (c.get("body") or ""):
                meta = common.read_meta(c["body"])
        if not meta or meta.get("state") != "accepted" or meta.get("head_sha") != pr["head"]["sha"]:
            continue
        concepts = ";".join(f"{re.sub(r'[^A-Za-z0-9_.!?]', '', str(c['name']))}:{int(c.get('uses', 0))}"
                            for c in meta.get("concepts") or [])
        out.append([pr["merged_at"][:10], str(n), pr["user"]["login"], meta.get("agent") or "",
                    meta.get("target") or "", meta.get("candidate") or "", str(meta["tokens_before"]),
                    str(meta["tokens_after"]), str(meta.get("cleanup_tokens") or 0), str(meta.get("lines_saved") or 0),
                    concepts, "", meta.get("upstream_commit") or "", meta["head_sha"]])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.path.abspath(a.out) != os.path.abspath(a.ledger):
        shutil.copytree(a.ledger, a.out, dirs_exist_ok=True)
    path = os.path.join(a.out, "contributions.tsv")
    if not os.path.exists(path):
        open(path, "w").write("\t".join(scoring.CONTRIB_COLS) + "\n")
    known = {line.split("\t")[1] for line in open(path).read().splitlines()[1:] if line.count("\t") > 1}
    new = [r for r in rows(a.repo) if r[1] not in known]
    with open(path, "a") as fh:
        for r in new:
            fh.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in r) + "\n")
    print(f"{len(new)} rows from the gate's records")


if __name__ == "__main__":
    main()
