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


BLOCKING = ("concept", "reuse", "readability")
SUBJECT_SAFE = re.compile(r"[^A-Za-z0-9_./ -]")


def load_review(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def review_counts(review: dict | None) -> bool:
    """A review round is used only when every blocking rubric answered."""
    if not review or review.get("reused"):
        return False
    res = review.get("results") or {}
    return all((res.get(r) or {}).get("verdict") in ("approve", "block") for r in BLOCKING)


def make_meta(shape, d, prev_meta, review):
    meta = {k: d.get(k) for k in ("pr", "head_sha", "state", "points", "shrink_points", "concept_points",
                                  "target", "candidate", "patch_name", "tokens_before", "tokens_after",
                                  "cleanup_tokens", "lines_saved", "concepts", "upstream_commit", "fingerprint",
                                  "scoring", "review")}
    prev_meta = prev_meta or {}
    rounds = int(prev_meta.get("review_rounds", 0)) + (1 if review_counts(review) else 0)
    same_head = prev_meta.get("head_sha") == d.get("head_sha")
    attempts = (int(prev_meta.get("error_attempts", 0)) if same_head else 0) + (1 if d["state"] == "error" else 0)
    meta.update(kind=shape.get("kind"), contributor=shape.get("author"),
                agent=(shape.get("marker") or {}).get("agent", ""),
                review_rounds=rounds, error_attempts=attempts if d["state"] == "error" else 0,
                merged_by_gate=False,
                checked_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return meta


def review_section(review):
    if not review:
        return ""
    try:
        import review as review_mod  # tools/gate/review.py
        return review_mod.render_comment(review)
    except Exception as e:  # noqa: BLE001  (the comment must still be posted)
        return f"(The AI review result could not be shown: {type(e).__name__}.)"


def write_output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            for k, v in kv.items():
                fh.write(f"{k}={v}\n")


def exact_files(repo: str, base: str, head: str) -> list[dict]:
    """The pull request's files at exactly this head commit."""
    return api(f"repos/{repo}/compare/{base}...{head}").get("files", [])


def report(a, repo, shape, d, cur) -> None:
    pr = int(shape["pr"])
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
    review = load_review(a.review) if d.get("review") else None
    meta = make_meta(shape, d, common.read_meta(prev["body"]) if prev else None, review)
    rounds = meta["review_rounds"]
    note = ""
    if rounds >= common.MAX_REVIEW_ROUNDS and d["state"] == "rejected" and d["checks"].get("value_review") is False:
        note = (f"This pull request has used its {common.MAX_REVIEW_ROUNDS} AI reviews. Please open a new pull "
                "request with a different approach; this one will be closed.")
    if d["state"] == "error" and meta["error_attempts"] >= 3:
        note = "The gate could not decide three times in a row; a maintainer will look at it."
    mergeable = d["state"] == "accepted" and d.get("points", 0) > 0 and cur["state"] == "open" \
        and not cur.get("draft")
    if mergeable:
        note = ("Merging now." if os.environ.get("AUTO_MERGE") == "true"
                else "Merging is switched off for now; a maintainer will merge it.")
    text = body(d, review_section(review), note, False, meta, repo)
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
        {"state": state, "context": common.STATUS_CONTEXT, "description": desc[:140],
         "target_url": os.environ.get("RUN_URL") or None})
    labels = ["contribution", STATE_LABELS[d["state"]]]
    if rounds >= common.MAX_REVIEW_ROUNDS and d["state"] == "rejected":
        labels.append("review-budget-spent")
    if d["state"] == "error" and meta["error_attempts"] >= 3:
        labels.append("needs-maintainer")
    set_labels(repo, pr, labels, [l["name"] for l in cur["labels"]])
    write_output(merge="true" if mergeable and os.environ.get("AUTO_MERGE") == "true" else "false")
    print(json.dumps({"state": d["state"], "note": note}))


def merge(a, repo, shape, d, cur) -> None:
    """Re-check everything that can change after the decision, then merge."""
    pr = int(shape["pr"])
    default = shape.get("default_branch", "main")
    files = exact_files(repo, default, d["head_sha"])
    ok = (d["state"] == "accepted" and d.get("points", 0) > 0 and os.environ.get("AUTO_MERGE") == "true"
          and cur["state"] == "open" and not cur.get("draft") and cur["base"]["ref"] == default
          and len(files) == 1 and files[0]["status"] == "added" and files[0]["filename"] == shape["patch_path"])
    if not ok:
        print("not merging: the pull request changed since the decision")
        return
    subprocess.run(["git", "-C", common.ROOT, "fetch", "-q", "origin", default], check=True)
    subprocess.run(["git", "-C", common.ROOT, "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
    prev = sticky_comment(repo, pr)
    meta = common.read_meta(prev["body"]) if prev else None
    review = load_review(a.review) if d.get("review") else None
    if common.fingerprint(shape["target"]) != d["fingerprint"]:
        if prev and meta:
            api(f"repos/{repo}/issues/comments/{prev['id']}", "PATCH", {"body": body(
                d, review_section(review), "Main changed since this check (another patch or new rules); "
                "checking again now.", False, meta, repo)})
        gh("workflow", "run", "contribution-gate.yml", "--repo", repo, "-f", f"pr={pr}", check=False)
        return
    subject = SUBJECT_SAFE.sub("", f"Contribution {d.get('candidate')} to {d.get('target')}")[:150] + f" (#{pr})"
    r = gh("pr", "merge", str(pr), "--repo", repo, "--squash", "--match-head-commit", d["head_sha"],
           "--subject", subject, "--body", f"Accepted by the contribution gate: {d['points']} points.",
           check=False)
    if r.returncode:
        print("merge failed:", r.stderr.strip()[:500])
        sys.exit(1)
    if prev and meta:
        meta["merged_by_gate"] = True
        api(f"repos/{repo}/issues/comments/{prev['id']}", "PATCH",
            {"body": body(d, review_section(review), "", True, meta, repo)})
    # every other open contribution to this target was checked against the old main
    gh("workflow", "run", "contribution-sweep.yml", "--repo", repo, "-f", f"requeue_target={shape['target']}",
       check=False)
    gh("workflow", "run", "site.yml", "--repo", repo, check=False)
    print("merged")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", required=True)
    ap.add_argument("--decision", required=True)
    ap.add_argument("--review")
    ap.add_argument("--merge", action="store_true", help="the merge step (its own job, one at a time)")
    ap.add_argument("--dry-run", action="store_true", help="print the comment, change nothing")
    a = ap.parse_args()
    repo = os.environ["REPO"]
    shape = json.load(open(a.shape))
    d = json.load(open(a.decision))
    cur = api(f"repos/{repo}/pulls/{int(shape['pr'])}")
    if cur["head"]["sha"] != d["head_sha"]:
        print("the pull request has a newer head; its own run reports")
        return
    if cur["base"]["ref"] != shape.get("default_branch", "main"):
        print("the pull request no longer targets the default branch")
        return
    (merge if a.merge else report)(a, repo, shape, d, cur)


if __name__ == "__main__":
    main()
