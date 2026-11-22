#!/usr/bin/env python3
"""Housekeeping of contribution pull requests (scheduled, and after merges).

    python3 tools/gate/sweep.py [--requeue-target T] [--dry-run]

Needs GH_TOKEN (pull-requests, issues and actions: write) and REPO.

  requeue   after a merge into target T, every other open contribution was
            checked against an older main (a target is checked against main's
            patches of every target): check them again
  retry     open pull requests whose current head has no final verdict
            (cancelled or failed runs, `error` at most three times per
            head), those that waited for the AI-review budget on an earlier
            day, and accepted ones that were not merged
  close     not accepted and unchanged for STALE_DAYS; out of AI reviews;
            drafts of contributors without write access untouched for
            STALE_DAYS (a draft is a claim; it expires)

At most MAX_DISPATCH checks are started per run, least recently checked
first. After a merge, only verdicts that main's change can alter are
re-checked (a rejection waits for its author's next commit).
Pull requests with the label `keep` are never closed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402

STALE_DAYS = 14
MAX_DISPATCH = 15
BOT = "github-actions[bot]"


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r


def api(path):
    return json.loads(gh("api", path).stdout or "null")


def api_all(path):
    pages = json.loads(gh("api", "--paginate", "--slurp", path).stdout or "[]")
    return [x for p in pages for x in p]


def age_days(ts: str) -> float:
    t = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400


def gate_meta(repo, n):
    meta = None
    for c in api_all(f"repos/{repo}/issues/{n}/comments?per_page=100"):
        if c["user"]["login"] == BOT and common.COMMENT_MARKER in (c.get("body") or ""):
            meta = common.read_meta(c["body"])
    return meta


def gate_status(repo, sha):
    st = api(f"repos/{repo}/commits/{sha}/status")
    for s in st.get("statuses", []):
        if s["context"] == common.STATUS_CONTEXT:
            return s
    return None


def patch_target(repo, n):
    files = api_all(f"repos/{repo}/pulls/{n}/files?per_page=100")
    if len(files) == 1 and files[0]["status"] == "added":
        m = common.PATCH_PATH.match(files[0]["filename"])
        if m:
            return m.group("target")
    return None


def head_date(repo, sha):
    return api(f"repos/{repo}/commits/{sha}")["commit"]["committer"]["date"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--requeue-target")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    repo = os.environ["REPO"]
    auto_merge = os.environ.get("AUTO_MERGE") == "true"
    prs = sorted(api_all(f"repos/{repo}/pulls?state=open&per_page=100"), key=lambda p: p["number"])
    dispatch, close = [], []   # dispatch: (last checked, number)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for p in prs:
        n, labels = p["number"], {l["name"] for l in p["labels"]}
        if p["base"]["ref"] != "main":
            continue
        meta = gate_meta(repo, n) if "contribution" in labels else None
        last = (meta or {}).get("checked_at") or ""
        state = (meta or {}).get("state")
        if a.requeue_target:
            # a verdict that main's change can alter (every target's: the fingerprint
            # covers all patches); a rejection waits for the author
            if not p["draft"] and state != "rejected" and "contribution" in labels:
                dispatch.append((last, n))
            continue
        if "keep" in labels:
            continue
        if "review-budget-spent" in labels:
            close.append((n, f"This pull request used its {common.MAX_REVIEW_ROUNDS} AI reviews without being "
                             "accepted. Please open a new pull request with a different approach."))
            continue
        if "not-accepted" in labels and age_days(head_date(repo, p["head"]["sha"])) > STALE_DAYS:
            close.append((n, f"Closed after {STALE_DAYS} days without a new commit. Push a fix and reopen it, "
                             "or open a new pull request."))
            continue
        if p["draft"]:
            if age_days(head_date(repo, p["head"]["sha"])) > STALE_DAYS and patch_target(repo, n) \
                    and p.get("author_association") not in ("OWNER", "MEMBER", "COLLABORATOR"):
                close.append((n, f"This draft (a claim on its candidate) had no new commit for {STALE_DAYS} days, "
                                 "so the candidate is free again. Reopen it to continue."))
            continue
        if "contribution" not in labels and not patch_target(repo, n):
            continue
        if "needs-maintainer" in labels:
            continue   # failed to decide three times; a person looks first
        st = gate_status(repo, p["head"]["sha"])
        if st is None:
            if age_days(p["updated_at"]) > 2 / 24:
                dispatch.append((last, n))
        elif st["state"] == "error" and int((meta or {}).get("error_attempts", 0)) < 3:
            dispatch.append((last, n))
        elif st["state"] == "pending" and age_days(st["updated_at"]) > 8 / 24:
            dispatch.append((last, n))
        elif st["state"] == "pending" and state == "waiting" and last[:10] < today:
            dispatch.append((last, n))
        elif st["state"] == "success" and auto_merge and age_days(st["updated_at"]) > 2 / 24:
            dispatch.append((last, n))   # accepted but not merged (merge failed or was dropped)
    chosen = [n for _, n in sorted(dispatch)[:MAX_DISPATCH]]   # least recently checked first
    print(json.dumps({"dispatch": chosen, "close": [n for n, _ in close]}))
    if a.dry_run:
        return
    for n in chosen:
        gh("workflow", "run", "contribution-gate.yml", "--repo", repo, "-f", f"pr={n}", check=False)
    for n, why in close:
        gh("pr", "close", str(n), "--repo", repo, "--comment", why, check=False)


if __name__ == "__main__":
    main()
