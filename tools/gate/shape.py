#!/usr/bin/env python3
"""Step 1 of the contribution gate: what kind of pull request is this?

    python3 tools/gate/shape.py --repo OWNER/NAME --pr N --out out/

Reads the pull request through the GitHub API (read-only token in GH_TOKEN)
and writes out/shape.json, and, for a contribution, out/new.patch (the one
added file, downloaded by content at the exact head commit). Nothing from the
pull request is executed. Kinds:

  contribution  exactly one added file lean/patches/<target>/<name>.patch,
                for a target the gate supports, at most MAX_PATCH_BYTES
  malformed     touches lean/patches/ but is not exactly that
  draft         a contribution still marked as draft (a claim; not built)
  limited       the author already has MAX_OPEN_PER_AUTHOR open contributions
  other         anything else (documentation, tools, ...): left to maintainers
  closed        the pull request is not open, or not against the default branch

Exit status 0 when shape.json was written, 75 on API errors.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def gh_api(path: str, paginate: bool = False):
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json", path]
    if paginate:
        cmd.insert(2, "--paginate")
        cmd.insert(3, "--slurp")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {path}: {r.stderr.strip()[:300]}")
    data = json.loads(r.stdout)
    if paginate:
        return [x for page in data for x in page]
    return data


def can_push(repo: str, login: str, association: str) -> bool:
    try:
        perm = gh_api(f"repos/{repo}/collaborators/{login}/permission").get("permission", "")
        if perm in ("admin", "maintain", "write"):
            return True
    except RuntimeError:
        pass
    return association in ("OWNER", "MEMBER", "COLLABORATOR")


def classify(pr: dict, files: list[dict], default_branch: str, supported: list[str]) -> dict:
    """Pure classification from API data (unit-tested)."""
    out = {"kind": "other", "reasons": [], "target": None, "patch_path": None, "patch_name": None,
           "candidate": None}
    if pr.get("state") != "open" or pr["base"]["ref"] != default_branch:
        out["kind"] = "closed"
        return out
    touches_patches = any(f["filename"].startswith("lean/patches/") or
                          (f.get("previous_filename") or "").startswith("lean/patches/") for f in files)
    if not touches_patches:
        return out
    if len(files) != 1:
        out["kind"] = "malformed"
        extra = [f["filename"] for f in files if not (f["status"] == "added" and common.PATCH_PATH.match(f["filename"]))]
        if len([f for f in files if f["status"] == "added" and common.PATCH_PATH.match(f["filename"])]) > 1:
            out["reasons"].append("paths_allowed: the pull request adds several patches; "
                                  "send one patch per pull request")
        if extra:
            out["reasons"].append("paths_allowed: a contribution adds exactly one patch file and changes nothing "
                                  "else; remove these changes from the pull request: " + ", ".join(extra[:10]))
        return out
    f = files[0]
    m = common.PATCH_PATH.match(f["filename"])
    if f["status"] != "added" or not m:
        out["kind"] = "malformed"
        out["reasons"].append(f"paths_allowed: {f['filename']} ({f['status']}): a contribution adds one new file "
                              "lean/patches/<target>/<NNNN>-<candidate>.patch and changes nothing else")
        return out
    target = m.group("target")
    if target not in supported:
        out["kind"] = "malformed"
        out["reasons"].append(f"paths_allowed: target {target} is not open for contributions yet "
                              f"(open: {', '.join(supported) or 'none'})")
        return out
    out.update(target=target, patch_path=f["filename"], patch_name=m.group("name") + ".patch",
               candidate=common.candidate_of(m.group("name")))
    out["kind"] = "draft" if pr.get("draft") else "contribution"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    try:
        repo = gh_api(f"repos/{a.repo}")
        pr = gh_api(f"repos/{a.repo}/pulls/{a.pr}")
        # the files at exactly this head commit (a push in between cannot mix
        # one head's file list with another head's content)
        files = gh_api(f"repos/{a.repo}/compare/{repo['default_branch']}...{pr['head']['sha']}").get("files", [])
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(75)
    default = repo["default_branch"]
    s = classify(pr, files, default, common.supported_targets())
    author = pr["user"]["login"]
    s.update(pr=a.pr, head_sha=pr["head"]["sha"], head_repo=(pr["head"].get("repo") or {}).get("full_name"),
             author=author, author_type=pr["user"].get("type"), title=pr.get("title", "")[:200],
             marker=common.parse_marker(pr.get("body")), default_branch=default,
             author_can_push=can_push(a.repo, author, pr.get("author_association", "")))
    if s["target"]:
        s["fingerprint"] = common.fingerprint(s["target"])
    # the gate's own earlier record (only comments by the Actions bot count)
    s["previous"] = None
    try:
        for c in gh_api(f"repos/{a.repo}/issues/{a.pr}/comments?per_page=100", paginate=True):
            if c["user"]["login"] == "github-actions[bot]" and common.COMMENT_MARKER in (c.get("body") or ""):
                s["previous"] = common.read_meta(c["body"])
    except RuntimeError as e:
        print(f"warning: {e}", file=sys.stderr)
    # One file at the exact head commit, by content API: never a checkout of
    # the pull request, and bounded in size before it is downloaded.
    if s["kind"] in ("contribution", "draft"):
        try:
            meta = gh_api(f"repos/{a.repo}/contents/{s['patch_path']}?ref={s['head_sha']}")
            if meta.get("type") != "file" or int(meta.get("size", 0)) > common.MAX_PATCH_BYTES:
                s["kind"] = "malformed"
                s["reasons"].append(f"paths_allowed: the patch is larger than {common.MAX_PATCH_BYTES} bytes; "
                                    "split the change into smaller pull requests")
            elif s["kind"] == "contribution":
                content = meta.get("content")
                if meta.get("encoding") == "base64" and content is not None:
                    data = base64.b64decode(content)
                else:
                    r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                                        f"repos/{a.repo}/contents/{s['patch_path']}?ref={s['head_sha']}"],
                                       capture_output=True, timeout=120)
                    if r.returncode:
                        raise RuntimeError(r.stderr.decode(errors="replace")[:300])
                    data = r.stdout
                if len(data) > common.MAX_PATCH_BYTES:
                    raise RuntimeError("patch grew while downloading")
                open(os.path.join(a.out, "new.patch"), "wb").write(data)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            sys.exit(75)
    # Rate limit for authors without write access: their oldest open pull
    # requests are checked (and claim candidates); later ones wait. Counted from the
    # pull request list itself (the search index lags); fails closed.
    if s["kind"] in ("contribution", "draft") and not s["author_can_push"]:
        try:
            # drafts count too: a draft is a claim on a candidate
            mine = sorted(p["number"] for p in gh_api(f"repos/{a.repo}/pulls?state=open&per_page=100", paginate=True)
                          if p["user"]["login"] == author)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            sys.exit(75)
        if a.pr in mine and mine.index(a.pr) >= common.MAX_OPEN_PER_AUTHOR:
            s["kind"] = "limited"
            s["reasons"].append(f"limit: you have {len(mine)} open pull requests; at most "
                                f"{common.MAX_OPEN_PER_AUTHOR} are checked at a time. This one is checked "
                                "automatically once some of the older ones are merged or closed")
    json.dump(s, open(os.path.join(a.out, "shape.json"), "w"), indent=1)
    print(json.dumps({k: s[k] for k in ("kind", "target", "candidate", "head_sha", "reasons")}))


if __name__ == "__main__":
    main()
