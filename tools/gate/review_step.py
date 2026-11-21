#!/usr/bin/env python3
"""Step 3 of the contribution gate: the AI review, within its budgets.

    python3 tools/gate/review_step.py --out out/

Reads out/shape.json, out/new.patch, out/facts.json and out/lean.diff (data
from the earlier jobs) and writes out/review.json. Needs OPENAI_API_KEY,
GH_TOKEN (contents: write, for the spend record), REPO, DAILY_CAP_USD.

- An approval is kept, without a new review, while the patch and the rubrics
  are byte-for-byte the same (a re-check after main moved costs nothing).
- A pull request gets at most MAX_REVIEW_ROUNDS reviews.
- The day's spend is read from, and appended to, review-spend.tsv on the
  branch `ci-state`, with compare-and-swap writes so parallel reviews cannot
  overspend by more than one review's reservation.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402
import review  # noqa: E402

BRANCH = "ci-state"
SPEND = "review-spend.tsv"
HEADER = "date\tpr\thead_sha\trubric\tmodel\tinput_tokens\toutput_tokens\tusd\n"


def gh(*args, input=None, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r


def read_spend(repo: str) -> tuple[str, str | None]:
    r = gh("api", f"repos/{repo}/contents/{SPEND}?ref={BRANCH}", check=False)
    if r.returncode:
        return HEADER, None
    d = json.loads(r.stdout)
    return base64.b64decode(d["content"]).decode(), d["sha"]


def ensure_branch(repo: str) -> None:
    if gh("api", f"repos/{repo}/branches/{BRANCH}", check=False).returncode == 0:
        return
    # an orphan branch holding only the spend record
    blob = json.loads(gh("api", "-X", "POST", f"repos/{repo}/git/blobs", "--input", "-",
                         input=json.dumps({"content": HEADER, "encoding": "utf-8"})).stdout)["sha"]
    tree = json.loads(gh("api", "-X", "POST", f"repos/{repo}/git/trees", "--input", "-", input=json.dumps(
        {"tree": [{"path": SPEND, "mode": "100644", "type": "blob", "sha": blob}]})).stdout)["sha"]
    commit = json.loads(gh("api", "-X", "POST", f"repos/{repo}/git/commits", "--input", "-", input=json.dumps(
        {"message": "Start the AI-review spend record", "tree": tree, "parents": []})).stdout)["sha"]
    gh("api", "-X", "POST", f"repos/{repo}/git/refs", "--input", "-",
       input=json.dumps({"ref": f"refs/heads/{BRANCH}", "sha": commit}), check=False)


def append_spend(repo: str, rows: str, pr: int) -> None:
    if not rows.strip():
        return
    ensure_branch(repo)
    for _ in range(8):
        text, sha = read_spend(repo)
        body = {"message": f"Review spend for #{pr}", "branch": BRANCH,
                "content": base64.b64encode((text + rows).encode()).decode()}
        if sha:
            body["sha"] = sha
        if gh("api", "-X", "PUT", f"repos/{repo}/contents/{SPEND}", "--input", "-",
              input=json.dumps(body), check=False).returncode == 0:
            return
    print("warning: could not record the review spend", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = a.out
    repo = os.environ["REPO"]
    shape = json.load(open(os.path.join(out, "shape.json")))
    facts = json.load(open(os.path.join(out, "facts.json")))
    pr = int(shape["pr"])
    with open(os.path.join(out, "new.patch"), "rb") as fh:
        patch_sha = hashlib.sha256(fh.read()).hexdigest()
    rubrics_sha = review.rubrics_sha256()
    prev = shape.get("previous") or {}
    prev_review = prev.get("review") or {}
    result_path = os.path.join(out, "review.json")

    def write(d):
        d.setdefault("schema", "concept-mining-review/v1")
        d.update(head_sha=shape["head_sha"], base_fingerprint=facts.get("fingerprint"), patch_sha256=patch_sha,
                 rubrics_sha256=d.get("rubrics_sha256") or rubrics_sha)
        json.dump(d, open(result_path, "w"), indent=1)
        print(json.dumps({k: d.get(k) for k in ("approved", "deferred", "reused", "cost_usd")}))

    if prev_review.get("approved") and prev_review.get("patch_sha256") == patch_sha \
            and prev_review.get("rubrics_sha256") == rubrics_sha:
        write({"approved": True, "deferred": False, "reused": True, "results": {}, "cost_usd": 0.0,
               "model": prev_review.get("model")})
        return
    if int(prev.get("review_rounds", 0)) >= common.MAX_REVIEW_ROUNDS:
        write({"approved": False, "deferred": False, "results": {"rounds": {
            "verdict": "block", "summary": f"this pull request has used its {common.MAX_REVIEW_ROUNDS} AI reviews; "
                                           "open a new pull request with a different approach"}}, "cost_usd": 0.0})
        return
    if not os.environ.get("OPENAI_API_KEY"):
        write({"approved": False, "deferred": True, "results": {}, "cost_usd": 0.0,
               "note": "the AI review is not configured (no OPENAI_API_KEY)"})
        return

    work = tempfile.mkdtemp(prefix="review-")
    spend_text, _ = read_spend(repo)
    open(os.path.join(work, "spend.tsv"), "w").write(spend_text)
    pull = json.loads(gh("api", f"repos/{repo}/pulls/{pr}").stdout)
    json.dump({"number": pr, "title": pull.get("title", ""), "body": pull.get("body") or "",
               "author": pull["user"]["login"]}, open(os.path.join(work, "pr.json"), "w"))
    json.dump({"new": [c["name"] for c in facts.get("concepts") or []]}, open(os.path.join(work, "decls.json"), "w"))
    rows = os.path.join(work, "spend-rows.tsv")
    r = subprocess.run([sys.executable, os.path.join(HERE, "review.py"),
                        "--diff", os.path.join(out, "lean.diff"), "--decls", os.path.join(work, "decls.json"),
                        "--pr", os.path.join(work, "pr.json"), "--head-sha", shape["head_sha"],
                        "--base-fingerprint", facts.get("fingerprint") or "", "--out", result_path,
                        "--spend", os.path.join(work, "spend.tsv"), "--spend-out", rows,
                        "--daily-cap-usd", os.environ.get("DAILY_CAP_USD", "10")],
                       capture_output=True, text=True, timeout=1500)
    print(r.stdout[-2000:])
    print(r.stderr[-2000:], file=sys.stderr)
    if os.path.exists(rows):
        append_spend(repo, open(rows).read(), pr)
    if not os.path.exists(result_path):
        write({"approved": False, "deferred": False, "results": {"review": {
            "verdict": "error", "summary": "the review step failed; it is retried automatically"}}, "error": True})
        return
    d = json.load(open(result_path))
    write(d)


if __name__ == "__main__":
    main()
