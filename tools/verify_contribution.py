#!/usr/bin/env python3
"""The trusted checker of a contribution pull request (called by CI, no secrets).

    python3 tools/verify_contribution.py --pr-dir <dir> --upstream <path> \
        [--pr-json pr.json] [--changed changed.txt] --out verdict.json

<dir> holds the pull request's `lean/patches/` and `data/ledger/` (as data;
nothing in it is executed). This script, the judge and the protected lists
come from the checkout this file lives in, i.e. the default branch.

  1. paths     every changed path (changed.txt) is a new patch under
               lean/patches/<target>/, a verdict under data/ledger/verdicts/,
               a claim under data/claims/, or an appended ledger table
  2. base      <path> becomes the pinned upstream commit with the patches of
               the default branch applied (tools/apply_patches.sh)
  3. apply     the new patches of the pull request are applied on top
  4. judge     tools/verify.py on the result (scope, shortcuts, size, build,
               protected statements and axioms)
  5. ledger    the token numbers the pull request recorded (verdict and
               contributions.tsv row) equal the measured ones

Writes verdict.json in the schema "concept-mining-verdict/v1" of
docs/scoring.md. Exit status: 0 all checks passed, 1 a check failed,
75 could not decide. Points and the final accept decision are computed by
tools/site/scoring.py from this verdict.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LEDGER_FILES = {"data/ledger/concepts.tsv", "data/ledger/history.tsv", "data/ledger/contributions.tsv"}


def run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr-dir", required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--pr-json", default=None)
    ap.add_argument("--changed", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-ref", default="origin/main",
                    help="the default branch, used when --pr-dir is this checkout")
    a = ap.parse_args()
    prdir = os.path.abspath(a.pr_dir)
    up = os.path.abspath(os.path.expanduser(a.upstream))
    pr = json.load(open(a.pr_json)) if a.pr_json else {}
    v = {"schema": "concept-mining-verdict/v1", "pr": pr.get("pr"), "head_sha": pr.get("head_sha"),
         "contributor": pr.get("contributor"), "agent": None, "target": None, "candidate": None,
         "upstream_commit": None,
         "checks": {"build": None, "protected_unchanged": None, "axioms_unchanged": None,
                    "no_shortcuts": None, "paths_allowed": None, "ledger_matches": None},
         "tokens_before": None, "tokens_after": None, "cleanup_tokens": 0, "lines_saved": None,
         "concepts": [], "reused": [], "reasons": []}
    code = 75

    def finish(c):
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        json.dump(v, open(a.out, "w"), indent=2, ensure_ascii=False)
        print(json.dumps({"checks": v["checks"], "reasons": v["reasons"]}, ensure_ascii=False))
        sys.exit(c)

    try:
        # 1. paths
        # the default branch's patches: from git when the checker runs inside the
        # pull request's own checkout (the preview run), else from this checkout
        main_patches = set()
        if os.path.samefile(prdir, REPO):
            r = run(["git", "-C", REPO, "ls-tree", "-r", "--name-only", a.base_ref, "lean/patches"])
            if r.returncode:
                v["reasons"].append(f"setup: cannot read {a.base_ref}: {r.stderr[-300:]}")
                finish(75)
            main_patches = {p for p in r.stdout.split() if p.endswith(".patch")}
        else:
            main_patches = {os.path.relpath(p, REPO) for p in glob.glob(os.path.join(REPO, "lean/patches/*/*.patch"))}
        pr_patches = {os.path.relpath(p, prdir) for p in glob.glob(os.path.join(prdir, "lean/patches/*/*.patch"))}
        new = sorted(pr_patches - main_patches)
        changed = [l.strip() for l in open(a.changed)] if a.changed else new
        changed = [c for c in changed if c]
        bad = [c for c in changed if not (
            (c.startswith("lean/patches/") and c.endswith(".patch") and c not in main_patches)
            or re.fullmatch(r"data/ledger/verdicts/[\w.-]+\.json", c)
            or re.fullmatch(r"data/claims/[\w.-]+/[\w.-]+\.json", c)
            or re.fullmatch(r"data/pilot/[\w.-]+/measure_latest\.json", c)
            or c in LEDGER_FILES)]
        targets = {p.split("/")[2] for p in new}
        if bad or not new or len(targets) != 1:
            v["checks"]["paths_allowed"] = False
            v["reasons"].append("paths_allowed: " + ("changes outside a contribution: " + ", ".join(bad[:5]) if bad
                                                      else "no new patch" if not new else "patches for several targets"))
            finish(1)
        for f in LEDGER_FILES:
            old, nw = os.path.join(REPO, f), os.path.join(prdir, f)
            if os.path.exists(old) and not os.path.exists(nw):
                v["checks"]["paths_allowed"] = False
                v["reasons"].append(f"paths_allowed: {f} may not be deleted")
                finish(1)
            if os.path.exists(old):
                o, n = open(old).read(), open(nw).read()
                if not n.startswith(o):
                    v["checks"]["paths_allowed"] = False
                    v["reasons"].append(f"paths_allowed: {f} may only be appended to")
                    finish(1)
        target = targets.pop()
        v["target"] = f"CFSG/{target}"
        cand = re.sub(r"^\d+-", "", os.path.basename(new[-1])[:-6])
        v["candidate"] = cand

        # 2. base
        # base = pinned upstream + exactly the default branch's patches
        import tempfile
        pdir = tempfile.mkdtemp(prefix="main-patches-")
        for p in sorted(x for x in main_patches if x.startswith(f"lean/patches/{target}/")):
            if os.path.samefile(prdir, REPO):
                body = run(["git", "-C", REPO, "show", f"{a.base_ref}:{p}"]).stdout
            else:
                body = open(os.path.join(REPO, p), encoding="utf-8").read()
            open(os.path.join(pdir, os.path.basename(p)), "w", encoding="utf-8").write(body)
        env = dict(os.environ, PATCHES_DIR=pdir)
        summary = os.path.join(REPO, "data", "pilot", target, "summary.json")
        if os.path.exists(summary) and json.load(open(summary)).get("edges_to_outside") == 0:
            env["SPARSE_TARGET_ONLY"] = "1"  # a closed island: its folder alone builds
        r = run([os.path.join(HERE, "apply_patches.sh"), up, target], env=env)
        if r.returncode:
            v["reasons"].append("setup: cannot prepare upstream: " + r.stderr[-500:])
            finish(75)
        base = run(["git", "-C", up, "rev-parse", "HEAD"]).stdout.strip()
        v["upstream_commit"] = dict(l.split("=", 1) for l in open(os.path.join(REPO, "lean/UPSTREAM")).read().split())["commit"]
        run(["lake", "exe", "cache", "get"], cwd=up)

        # 3. apply
        for p in new:
            r = run(["git", "-C", up, "apply", os.path.join(prdir, p)])
            if r.returncode:
                v["checks"]["paths_allowed"] = False
                v["reasons"].append(f"paths_allowed: {p} does not apply on the default branch: {r.stderr[-300:]}")
                finish(1)

        # 4. judge (from the default branch)
        vj = os.path.join(os.path.dirname(os.path.abspath(a.out)) or ".", "judge.json")
        r = run([sys.executable, os.path.join(HERE, "verify.py"), "--root", up, "--base", base,
                 "--target", target, "--json", vj])
        j = json.load(open(vj))
        for k in ("build", "protected_unchanged", "axioms_unchanged", "no_shortcuts"):
            v["checks"][k] = j["checks"].get(k)
        if j["checks"].get("paths_allowed") is False:
            v["checks"]["paths_allowed"] = False
        elif v["checks"]["paths_allowed"] is None:
            v["checks"]["paths_allowed"] = True
        v.update(tokens_before=j.get("tokens_before"), tokens_after=j.get("tokens_after"),
                 lines_saved=j.get("code_lines_saved"))
        if j["verdict"] != "accept":
            v["reasons"].append(f"{j['phase']}: {j['reason']}")

        # 5. ledger
        rec = os.path.join(prdir, "data/ledger/verdicts", cand + ".json")
        ok = True
        if os.path.exists(rec):
            mine = json.load(open(rec))
            v["agent"] = mine.get("agent") if not mine.get("model") else f"{mine.get('agent')}/{mine.get('model')}"
            if mine.get("concept"):
                uses = run(["git", "-C", up, "grep", "-ow", "-E", re.escape(mine["concept"].split(".")[-1]), "--",
                            f"CFSG/{target}"]).stdout.count("\n")
                v["concepts"] = [{"name": mine["concept"], "uses": uses, "meaning": mine.get("meaning", "")}]
            if mine.get("tokens_saved") != (j.get("tokens_saved")):
                ok = False
                v["reasons"].append(f"ledger_matches: recorded tokens_saved {mine.get('tokens_saved')} "
                                    f"!= measured {j.get('tokens_saved')}")
        ctsv = os.path.join(prdir, "data/ledger/contributions.tsv")
        if os.path.exists(ctsv):
            rows = list(csv.DictReader(open(ctsv), delimiter="\t"))
            mine_rows = [r for r in rows if r.get("candidate") == cand]
            for r in mine_rows:
                if (int(r["tokens_before"]), int(r["tokens_after"])) != (j.get("tokens_before"), j.get("tokens_after")):
                    ok = False
                    v["reasons"].append("ledger_matches: contributions.tsv tokens differ from the measured ones")
        v["checks"]["ledger_matches"] = ok
        code = 0 if all(v["checks"].values()) else 1
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        v["reasons"].append(f"setup: {type(e).__name__}: {e}"[:500])
        code = 75
    finish(code)


if __name__ == "__main__":
    main()
