#!/usr/bin/env python3
"""Per-model totals from judged.jsonl: pass rate, lines removed, cost per 100 lines removed.

    python3 tools/trials/summarize.py --runs out/trials
"""

import argparse
import json
import os
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--runs", required=True)
a = ap.parse_args()
agg = defaultdict(lambda: {"attempts": 0, "passed": 0, "cost": 0.0, "shrink": 0})
for line in open(os.path.join(a.runs, "judged.jsonl")):
    r = json.loads(line)
    g = agg[r["model"]]
    g["attempts"] += 1
    g["cost"] += r.get("cost_usd", 0.0)
    if r.get("passed") and r.get("shrink_lines", 0) > 0:
        g["passed"] += 1
        g["shrink"] += r["shrink_lines"]
print("| model | attempts | passed | lines removed | cost (USD) | USD per 100 lines removed |")
print("|---|---|---|---|---|---|")
for m, g in sorted(agg.items(), key=lambda x: (x[1]["cost"] / x[1]["shrink"]) if x[1]["shrink"] else float("inf")):
    per = f"{100 * g['cost'] / g['shrink']:.3f}" if g["shrink"] else "-"
    print(f"| {m} | {g['attempts']} | {g['passed']} | {g['shrink']} | {g['cost']:.3f} | {per} |")
