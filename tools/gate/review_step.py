#!/usr/bin/env python3
"""Step 3 of the contribution gate: the AI review, within its budgets.

    python3 tools/gate/review_step.py --out out/

Reads out/shape.json, out/new.patch, out/facts.json and out/lean.diff (data
from the earlier jobs) and writes out/review.json. Needs OPENAI_API_KEY,
GH_TOKEN (contents: write, for the spend record), REPO, DAILY_CAP_USD.

- An approval is kept, without a new review, while the patch, the rubrics
  and main's fingerprint are unchanged (a re-check of the same state is free).
- A pull request gets at most MAX_REVIEW_ROUNDS reviews.
- Before any call, the review's worst-case cost is reserved in
  review-reservations.tsv on the branch `ci-state` (compare-and-swap writes),
  so parallel reviews together never exceed the daily cap; the actual cost is
  then recorded in review-spend.tsv and the reservation released. A review
  that does not fit waits for the next UTC day.
- A round is counted only when every blocking rubric answered (approve or
  block); waiting for the budget or an API failure costs no round.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
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
RESERVE = "review-reservations.tsv"
HEADER = "date\tpr\thead_sha\trubric\tmodel\tinput_tokens\toutput_tokens\tusd\n"
RHEADER = "date\trun\tusd\n"


def gh(*args, input=None, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r


def read_file(repo: str, path: str, header: str) -> tuple[str, str | None]:
    r = gh("api", f"repos/{repo}/contents/{path}?ref={BRANCH}", check=False)
    if r.returncode:
        return header, None
    d = json.loads(r.stdout)
    return base64.b64decode(d["content"]).decode(), d["sha"]


def write_file(repo: str, path: str, text: str, sha: str | None, message: str) -> bool:
    body = {"message": message, "branch": BRANCH, "content": base64.b64encode(text.encode()).decode()}
    if sha:
        body["sha"] = sha
    return gh("api", "-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-",
              input=json.dumps(body), check=False).returncode == 0


def read_spend(repo: str) -> tuple[str, str | None]:
    return read_file(repo, SPEND, HEADER)


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
        if write_file(repo, SPEND, text + rows, sha, f"Review spend for #{pr}"):
            return
    print("warning: could not record the review spend", file=sys.stderr)


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def spent_today(text: str) -> float:
    day = today()
    total = 0.0
    for line in text.splitlines()[1:]:
        cells = line.split("\t")
        if len(cells) >= 8 and cells[0][:10] == day:
            try:
                total += float(cells[7])
            except ValueError:
                return float("inf")  # unreadable: fail closed
    return total


def open_reservations(text: str, but: str | None = None) -> list[tuple[str, float]]:
    out = []
    for line in text.splitlines()[1:]:
        cells = line.split("\t")
        if len(cells) >= 3 and cells[0] == today() and cells[1] != but:
            try:
                out.append((cells[1], float(cells[2])))
            except ValueError:
                out.append((cells[1], float("inf")))
    return out


def reserve(repo: str, run: str, usd: float, cap: float) -> bool:
    """Atomically reserve `usd` for today if it fits under the cap."""
    ensure_branch(repo)
    for _ in range(10):
        spend, _ = read_spend(repo)
        text, sha = read_file(repo, RESERVE, RHEADER)
        held = sum(u for _, u in open_reservations(text))
        if spent_today(spend) + held + usd > cap + 1e-9:
            return False
        # keep only today's lines: yesterday's reservations expire
        keep = [l for l in text.splitlines()[1:] if l.startswith(today())]
        new = RHEADER + "".join(l + "\n" for l in keep) + f"{today()}\t{run}\t{usd:.6f}\n"
        if write_file(repo, RESERVE, new, sha, f"Reserve {usd:.2f} USD for a review"):
            return True
    return False


def release(repo: str, run: str) -> None:
    for _ in range(10):
        text, sha = read_file(repo, RESERVE, RHEADER)
        lines = [l for l in text.splitlines()[1:] if l.split("\t")[1:2] != [run]]
        if write_file(repo, RESERVE, RHEADER + "".join(l + "\n" for l in lines), sha, "Release a review reservation"):
            return


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

    # an approval carries over only while the patch, the rubrics and main
    # (what the patch could duplicate) are all unchanged
    if prev_review.get("approved") and prev_review.get("patch_sha256") == patch_sha \
            and prev_review.get("rubrics_sha256") == rubrics_sha \
            and prev.get("fingerprint") == facts.get("fingerprint"):
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
    pull = json.loads(gh("api", f"repos/{repo}/pulls/{pr}").stdout)
    json.dump({"number": pr, "title": pull.get("title", ""), "body": pull.get("body") or "",
               "author": pull["user"]["login"]}, open(os.path.join(work, "pr.json"), "w"))
    json.dump({"new": [c["name"] for c in facts.get("concepts") or []]}, open(os.path.join(work, "decls.json"), "w"))
    cap = float(os.environ.get("DAILY_CAP_USD", "10"))
    run = os.environ.get("GITHUB_RUN_ID", "local") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    args = [sys.executable, os.path.join(HERE, "review.py"),
            "--diff", os.path.join(out, "lean.diff"), "--decls", os.path.join(work, "decls.json"),
            "--pr", os.path.join(work, "pr.json"), "--head-sha", shape["head_sha"],
            "--base-fingerprint", facts.get("fingerprint") or ""]
    # the review module sees no GitHub token
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    dry = subprocess.run(args + ["--dry-run", "--out", os.path.join(work, "dry.json"), "--daily-cap-usd", "1e9"],
                         capture_output=True, text=True, timeout=600, env={k: v for k, v in env.items()
                                                                            if k != "OPENAI_API_KEY"})
    try:
        worst = float(json.loads(dry.stdout)["worst_case_usd_total"])
        free = json.loads(dry.stdout).get("too_large") or json.loads(dry.stdout).get("deletion_only")
    except (ValueError, KeyError):
        write({"approved": False, "deferred": False, "error": True, "results": {}, "cost_usd": 0.0,
               "note": "could not estimate the review's cost: " + dry.stderr[-300:]})
        return
    reserved = False
    if not free:
        if not reserve(repo, run, worst, cap):
            write({"approved": False, "deferred": True, "results": {}, "cost_usd": 0.0})
            return
        reserved = True
    try:
        # the ledger the review checks against: actual spend plus the other
        # reviews' reservations (its own is already counted in `worst`)
        spend_text, _ = read_spend(repo)
        rtext, _ = read_file(repo, RESERVE, RHEADER)
        lines = spend_text.rstrip("\n").split("\n")
        for other, usd in open_reservations(rtext, but=run):
            lines.append(f"{today()}\t0\treserved\treserved\t-\t0\t0\t{usd:.6f}")
        open(os.path.join(work, "spend.tsv"), "w").write("\n".join(lines) + "\n")
        rows = os.path.join(work, "spend-rows.tsv")
        r = subprocess.run(args + ["--out", result_path, "--spend", os.path.join(work, "spend.tsv"),
                                   "--spend-out", rows, "--daily-cap-usd", str(cap)],
                           capture_output=True, text=True, timeout=1500, env=env)
        print(r.stdout[-2000:])
        print(r.stderr[-2000:], file=sys.stderr)
        if os.path.exists(rows):
            append_spend(repo, open(rows).read(), pr)
    finally:
        if reserved:
            release(repo, run)
    if not os.path.exists(result_path):
        write({"approved": False, "deferred": False, "error": True, "results": {}, "cost_usd": 0.0})
        return
    write(json.load(open(result_path)))


if __name__ == "__main__":
    main()
