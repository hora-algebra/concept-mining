#!/usr/bin/env python3
"""Step 5 of the contribution gate: report the decision, and merge.

    python3 tools/gate/act.py --shape out/shape.json --decision out/decision.json \
        [--review out/review.json]

Needs GH_TOKEN (contents, pull-requests, issues, statuses and actions: write),
REPO, and optionally AUTO_MERGE ("true" to merge), RUN_URL. Runs no pull
request content. One comment per pull request is kept up to date (it ends
with a machine-readable record from which the ledger is rebuilt), plus one
commit status `concept-mining/gate` and one state label.

A pull request is merged only if, at this moment: the decision is
`accepted`, the head commit is the one that was checked, the pull request is
open and not a draft, and main still has the fingerprint the check ran
under (same patches for the target, same rules and tools). If main moved,
the check is started again instead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402

BOT = "github-actions[bot]"
STATE_LABELS = {"accepted": "accepted", "rejected": "not-accepted", "waiting": "waiting", "error": "waiting"}
LABEL_COLORS = {"contribution": "1d76db", "accepted": "0e8a16", "not-accepted": "d93f0b", "waiting": "fbca04",
                "needs-maintainer": "5319e7", "review-budget-spent": "b60205"}
CHECK_TEXT = [
    ("paths_allowed", "One patch file, touching only Lean files of the target"),
    ("applies", "Applies on the current main"),
    ("no_metaprogramming", "No code that runs while Lean compiles"),
    ("no_shortcuts", "No shortcuts (sorry, new axioms, raised limits)"),
    ("saves_tokens", f"Saves at least {common.MIN_TOKENS} Lean tokens"),
    ("build", "Builds"),
    ("protected_unchanged", "Protected statements unchanged"),
    ("axioms_unchanged", "Axioms unchanged"),
    ("value_review", "AI review: natural concepts, no duplication of Mathlib, readable"),
]


def gh(*args, check=True, input=None):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r


def api(path, method="GET", fields=None):
    args = ["api", "-X", method, path]
    if fields is not None:
        args += ["--input", "-"]
        return json.loads(gh(*args, input=json.dumps(fields)).stdout or "null")
    return json.loads(gh(*args).stdout or "null")


def safe(text: str) -> str:
    """Text from a pull request or a model, made inert in a comment."""
    text = str(text).replace("\r", "")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"@(?=[A-Za-z0-9-])", "@​", text)
    return text


def sticky_comment(repo: str, pr: int) -> dict | None:
    comments = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments?per_page=100").stdout)
    mine = [c for page in comments for c in page
            if c["user"]["login"] == BOT and common.COMMENT_MARKER in (c.get("body") or "")]
    return mine[-1] if mine else None


def body(d: dict, review_md: str, note: str, merged: bool, meta: dict, repo: str) -> str:
    st = d["state"]
    head = (d.get("head_sha") or "")[:7]
    title = {"accepted": f"✅ Accepted: {d['points']} points",
             "rejected": "❌ Not accepted yet",
             "waiting": "⏸ Waiting",
             "error": "⚠️ Could not decide (not your fault; checked again automatically)"}[st]
    lines = [common.COMMENT_MARKER, f"### {title}", "",
             f"Checked commit `{head}` against the current main branch. How the checks work: "
             f"[docs/gate.md](https://github.com/{repo}/blob/main/docs/gate.md).", ""]
    if any(v is not None for v in d["checks"].values()):
        lines += ["| Check | |", "|---|---|"]
        for k, text in CHECK_TEXT:
            v = d["checks"].get(k)
            mark = "✅" if v is True else "❌" if v is False else "·"
            extra = ""
            if k == "saves_tokens" and d.get("tokens_before") is not None and d.get("tokens_after") is not None:
                extra = f" ({d['tokens_before'] - d['tokens_after']} saved)"
            lines.append(f"| {text} | {mark}{extra} |")
        lines.append("")
    if d.get("reasons"):
        head_word = "What to fix" if st == "rejected" else "Details"
        lines += [f"**{head_word}**", ""] + [f"- {safe(r)[:600]}" for r in d["reasons"][:25]] + [""]
    if review_md:
        lines += [review_md, ""]
    if st == "rejected":
        lines += ["Push a fix to the same branch (your agent can do it); every push is checked again.", ""]
    if merged:
        lines += ["Merged automatically. Thank you!", ""]
    if note:
        lines += [note, ""]
    lines.append(common.write_meta(meta))
    return "\n".join(lines)


def ensure_labels(repo: str):
    have = {l["name"] for l in json.loads(gh("api", f"repos/{repo}/labels?per_page=100").stdout)}
    for name, color in LABEL_COLORS.items():
        if name not in have:
            gh("api", "-X", "POST", f"repos/{repo}/labels", "-f", f"name={name}", "-f", f"color={color}", check=False)


def set_labels(repo: str, pr: int, add: list[str], current: list[str]):
    remove = [l for l in set(STATE_LABELS.values()) if l in current and l not in add]
    for l in remove:
        gh("api", "-X", "DELETE", f"repos/{repo}/issues/{pr}/labels/{l}", check=False)
    if add:
        api(f"repos/{repo}/issues/{pr}/labels", "POST", {"labels": add})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", required=True)
    ap.add_argument("--decision", required=True)
    ap.add_argument("--review")
    ap.add_argument("--dry-run", action="store_true", help="print the comment, change nothing")
    a = ap.parse_args()
    repo = os.environ["REPO"]
    shape = json.load(open(a.shape))
    d = json.load(open(a.decision))
    pr = int(shape["pr"])
    cur = api(f"repos/{repo}/pulls/{pr}")
    if cur["head"]["sha"] != d["head_sha"]:
        print("the pull request has a newer head; its own run reports")
        return
    if d["state"] == "not_contribution":
        if shape.get("kind") == "other" and not shape.get("author_can_push") and cur["state"] == "open" \
                and not sticky_comment(repo, pr) and not a.dry_run:
            ensure_labels(repo)
            gh("pr", "comment", str(pr), "--repo", repo, "--body",
               common.COMMENT_MARKER + "\nThank you! Only contribution patches (one file under `lean/patches/`) "
               "are checked and merged automatically. A maintainer will look at this pull request.")
            set_labels(repo, pr, ["needs-maintainer"], [l["name"] for l in cur["labels"]])
        return

    prev = sticky_comment(repo, pr)
    prev_meta = common.read_meta(prev["body"]) if prev else None
    rounds = int((prev_meta or {}).get("review_rounds", 0))
    if (d.get("review") or {}).get("approved") is not None and not (d["review"] or {}).get("reused"):
        rounds += 1
    review_md = ""
    if a.review and os.path.exists(a.review) and d.get("review"):
        try:
            import review as review_mod  # tools/gate/review.py
            review_md = review_mod.render_comment(json.load(open(a.review)))
        except Exception as e:  # noqa: BLE001  (the comment must still be posted)
            review_md = f"(The AI review result could not be shown: {type(e).__name__}.)"
    meta = {k: d.get(k) for k in ("pr", "head_sha", "state", "points", "shrink_points", "concept_points",
                                  "target", "candidate", "patch_name", "tokens_before", "tokens_after",
                                  "cleanup_tokens", "lines_saved", "concepts", "upstream_commit", "fingerprint",
                                  "scoring", "review")}
    meta.update(contributor=shape.get("author"), agent=(shape.get("marker") or {}).get("agent", ""),
                review_rounds=rounds, checked_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    merged, note = False, ""
    run_url = os.environ.get("RUN_URL", "")
    if rounds >= common.MAX_REVIEW_ROUNDS and d["state"] == "rejected" and d["checks"].get("value_review") is False:
        note = (f"This pull request has used its {common.MAX_REVIEW_ROUNDS} AI reviews. Please open a new pull "
                "request with a different approach; this one will be closed.")
    want_merge = d["state"] == "accepted" and d.get("points", 0) > 0 and cur["state"] == "open" \
        and not cur.get("draft")
    if want_merge and os.environ.get("AUTO_MERGE") != "true":
        note = "Merging is switched off for now; a maintainer will merge it."
        want_merge = False
    if want_merge and not a.dry_run:
        # main as it is now, not as it was when this job started
        subprocess.run(["git", "-C", common.ROOT, "fetch", "-q", "origin", shape.get("default_branch", "main")],
                       check=True)
        subprocess.run(["git", "-C", common.ROOT, "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
        if common.fingerprint(shape["target"]) != d["fingerprint"]:
            want_merge = False
            note = "Main changed since this check (another patch or new rules); checking again now."
            gh("workflow", "run", "contribution-gate.yml", "--repo", repo, "-f", f"pr={pr}", check=False)
    meta["merged_by_gate"] = False
    text = body(d, review_md, note, False, meta, repo)
    if a.dry_run:
        print(text)
        return
    ensure_labels(repo)
    if prev:
        api(f"repos/{repo}/issues/comments/{prev['id']}", "PATCH", {"body": text})
    else:
        api(f"repos/{repo}/issues/{pr}/comments", "POST", {"body": text})
    state = {"accepted": "success", "rejected": "failure", "waiting": "pending", "error": "error"}[d["state"]]
    desc = {"accepted": f"Accepted: {d['points']} points", "rejected": "Not accepted: see the comment",
            "waiting": "Waiting: see the comment", "error": "Could not decide; retried automatically"}[d["state"]]
    api(f"repos/{repo}/statuses/{d['head_sha']}", "POST",
        {"state": state, "context": common.STATUS_CONTEXT, "description": desc[:140], "target_url": run_url or None})
    labels = ["contribution", STATE_LABELS[d["state"]]]
    if rounds >= common.MAX_REVIEW_ROUNDS and d["state"] == "rejected":
        labels.append("review-budget-spent")
    set_labels(repo, pr, labels, [l["name"] for l in cur["labels"]])

    if want_merge:
        subject = f"{cur['title'][:200]} (#{pr})"
        r = gh("pr", "merge", str(pr), "--repo", repo, "--squash", "--match-head-commit", d["head_sha"],
               "--subject", subject, "--body", f"Accepted by the contribution gate: {d['points']} points.",
               check=False)
        if r.returncode == 0:
            meta["merged_by_gate"] = True
            api(f"repos/{repo}/issues/comments/{(prev or {}).get('id') or sticky_comment(repo, pr)['id']}", "PATCH",
                {"body": body(d, review_md, "", True, meta, repo)})
            # every other open contribution to this target was checked against the old main
            gh("workflow", "run", "contribution-sweep.yml", "--repo", repo, "-f", f"requeue_target={shape['target']}",
               check=False)
            gh("workflow", "run", "site.yml", "--repo", repo, check=False)
        else:
            print("merge failed:", r.stderr.strip()[:500])
    print(json.dumps({"state": d["state"], "merged": meta["merged_by_gate"], "note": note}))


if __name__ == "__main__":
    main()
