#!/usr/bin/env python3
"""Step 4 of the contribution gate: one decision from the facts and the review.

    python3 tools/gate/decide.py --shape out/shape.json [--facts out/facts.json] \
        [--review out/review.json] --out out/decision.json

Pure: reads JSON, writes JSON, runs nothing. States:

  accepted          every machine check and the AI review passed, points > 0
  rejected          a check failed; `reasons` says what to fix
  waiting           nothing is wrong yet, but the decision has to wait (draft,
                    the author's open-PR limit, the daily AI-review budget)
  error             the gate could not decide (setup failure); not the
                    contributor's fault, the next run retries
  not_contribution  not a contribution pull request; left to maintainers
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "site"))
import common  # noqa: E402
import scoring  # noqa: E402

MECHANICAL = [c for c in scoring.CHECKS if c != "value_review"]


def load(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def decide(shape: dict, facts: dict | None, review: dict | None) -> dict:
    d = {"schema": "concept-mining-decision/v2", "scoring": scoring.VERSION, "pr": shape.get("pr"),
         "head_sha": shape.get("head_sha"), "contributor": shape.get("author"),
         "agent": (shape.get("marker") or {}).get("agent", ""), "target": None, "candidate": shape.get("candidate"),
         "patch_name": shape.get("patch_name"), "fingerprint": shape.get("fingerprint"),
         "state": "error", "accepted": False, "points": 0.0, "shrink_points": 0.0, "concept_points": 0.0,
         "checks": {c: None for c in scoring.CHECKS}, "reasons": [], "review": None}
    kind = shape.get("kind")
    if shape.get("target"):
        d["target"] = "CFSG/" + shape["target"]
    if kind in ("other", "closed"):
        d["state"] = "not_contribution"
        return d
    if kind == "malformed":
        d["state"] = "rejected"
        d["checks"]["paths_allowed"] = False
        d["reasons"] = list(shape.get("reasons", []))
        return d
    if kind in ("draft", "limited"):
        d["state"] = "waiting"
        d["reasons"] = list(shape.get("reasons", [])) or ["draft: mark the pull request as ready for review "
                                                          "to have it checked"]
        return d
    if facts is None:
        d["reasons"] = ["setup: the build did not finish (cancelled or timed out); it is retried automatically"]
        return d
    if facts.get("fingerprint") != shape.get("fingerprint"):
        d["reasons"] = ["setup: main changed while this pull request was being checked; it is checked again"]
        return d
    for k in ("tokens_before", "tokens_after", "cleanup_tokens", "lines_saved", "concepts", "upstream_commit"):
        d[k] = facts.get(k)
    for c in MECHANICAL:
        d["checks"][c] = facts.get("checks", {}).get(c)
    if facts.get("setup_error"):
        d["reasons"] = ["setup: " + facts["setup_error"]]
        return d
    reasons = list(facts.get("reasons", []))
    if not all(d["checks"][c] is True for c in MECHANICAL):
        d["state"] = "rejected"
        d["reasons"] = reasons or ["a machine check failed"]
        return d
    # the AI review (only reached when every machine check passed)
    if review is None:
        d["reasons"] = ["setup: the AI review did not run; it is retried automatically"]
        return d
    d["review"] = {k: review.get(k) for k in ("approved", "deferred", "model", "rubrics_sha256", "cost_usd",
                                              "patch_sha256", "reused")}
    results = review.get("results", {})
    if review.get("deferred"):
        d["state"] = "waiting"
        d["reasons"] = ["review: today's AI-review budget is used up; the review runs automatically tomorrow"]
        return d
    if review.get("error") or any(r.get("verdict") == "error" for n, r in results.items() if n != "advisory"):
        # a failed API call or an unreadable answer holds the merge without
        # blaming the contributor; the sweep retries it
        d["reasons"] = ["setup: the AI review could not be completed; it is retried automatically"]
        return d
    if review.get("approved"):
        d["checks"]["value_review"] = True
    else:
        d["checks"]["value_review"] = False
        for name, r in sorted(results.items()):
            v = r.get("verdict")
            if v == "too_large":
                reasons.append("value_review: the change is too large for one review; split it into smaller "
                               "pull requests")
                break
            if v in ("block", "error") and name != "advisory":
                reasons.append(f"value_review ({name}): " + (r.get("summary") or v)[:400])
    verdict = {"checks": d["checks"], "tokens_before": d["tokens_before"], "tokens_after": d["tokens_after"],
               "cleanup_tokens": d["cleanup_tokens"] or 0, "concepts": d["concepts"] or [], "reasons": reasons,
               "pr": d["pr"], "head_sha": d["head_sha"]}
    dec = scoring.decide(verdict)
    d.update(accepted=dec["accepted"], points=dec["points"], shrink_points=dec["shrink_points"],
             concept_points=dec["concept_points"], tokens_saved=dec["tokens_saved"], reasons=dec["reasons"])
    d["state"] = "accepted" if dec["accepted"] else "rejected"
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", required=True)
    ap.add_argument("--facts")
    ap.add_argument("--review")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    shape = load(a.shape)
    if shape is None:
        sys.exit("no shape.json")
    d = decide(shape, load(a.facts), load(a.review))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(d, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: d[k] for k in ("state", "points", "reasons")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
