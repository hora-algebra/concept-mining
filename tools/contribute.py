#!/usr/bin/env python3
"""One command: pick a concept candidate, let an AI introduce it, judge it, record it, open a PR.

    python3 tools/contribute.py --target FeitThompson --root ~/Codes/upstream/cfsg-work --agent claude

Steps (each stops the run on failure, leaving nothing half-recorded):

  1. prepare  the Lean checkout at --root is the pinned upstream commit with
              every patch of lean/patches/<target>/ applied (tools/apply_patches.sh)
              and built
  2. pick     the best candidate of data/pilot/<target>/candidates.jsonl that
              has no verdict yet and no open claim (or the one given by --candidate)
  3. claim    push a branch contrib/<target>/<id> and open a draft PR titled
              "[<target>/<id>] ..."; an open PR with that prefix is a claim,
              so two runners never work on the same candidate
  4. rewrite  run the agent in the checkout with the candidate, the rules and
              the judge command; it edits files under CFSG/<target>/ only and
              writes the concept's name and meaning to a JSON file
  5. judge    tools/verify.py on the agent's result, independently of what the
              agent says (scope, forbidden constructs, token size, full build
              of the target, protected statements and axioms)
  6. record   on acceptance: the change becomes lean/patches/<target>/NNNN-<id>.patch,
              the ledger gets a concept row and a history row, the verdict is
              saved under data/ledger/verdicts/, and the draft PR becomes ready.
              On rejection the verdict is saved and the claim PR is closed.

Agents (provider is interchangeable):
  --agent claude          Claude Code CLI (`claude -p`), your own login or key
  --agent codex           Codex CLI (`codex exec`)
  --agent "cmd:<command>" any command; it receives the prompt on stdin

Use --no-pr to do everything locally (no push, no PR).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

PROMPT = """You are improving a Lean 4 formalization (Mathlib-based) by introducing one concept.
Working directory: a checkout of AxiomMath/CFSG. You may edit only files under CFSG/{target}/
(you may create new files there). Do not touch any other path.

Candidate {id} ({kind}): {title}
{summary}

What to do: {instructions}

Rules, checked mechanically afterwards; a change that breaks any of them is discarded:
- The statements and axioms of these declarations must not change: {protected}.
- No sorry, admit, native_decide, axiom, unsafe, implemented_by, extern, or kernel-check switches.
- Imports may only be added from Mathlib or CFSG.{target}.
- The size of CFSG/{target} in Lean tokens must drop by at least {min_tokens}. Whitespace, line
  breaks, comments and the length of names do not count, so only real simplification helps:
  fewer definitions, hypotheses, terms and proof steps.
- Every module under CFSG/{target} must build.

Check your work with
    nice -n 15 lake build <the modules you changed and the modules importing them>
and finally with the full judge (it prints accept or reject with a reason):
    python3 {verify} --root . --base {base} --target {target}
Iterate until the judge accepts or you are convinced the candidate does not shrink the code;
in that case undo your edits (git checkout -- CFSG) so the tree is clean.

When done, write a JSON object to {concept_file} with keys "name" (a short name of the concept,
e.g. the Lean identifier you introduced or kept) and "meaning" (one or two sentences: what the
concept is mathematically, for a mathematician reading the ledger). Do not commit.
"""


def sh(cmd, cwd=None, check=True, capture=True, **kw):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))} failed:\n{(r.stdout or '')[-2000:]}{(r.stderr or '')[-2000:]}")
    return r


def log(msg):
    print(f"[contribute {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def modules(root, target):
    base = os.path.join(root, "CFSG", target)
    out = []
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.endswith(".lean"):
                out.append(os.path.relpath(os.path.join(d, f[:-5]), root).replace(os.sep, "."))
    return sorted(out)


def open_claims(target):
    r = sh(["gh", "pr", "list", "--state", "open", "--limit", "200", "--json", "title"], cwd=REPO, check=False)
    if r.returncode != 0:
        raise RuntimeError("cannot list pull requests with gh (needed for claims); use --no-pr to work locally")
    ids = set()
    for pr in json.loads(r.stdout or "[]"):
        m = re.match(rf"\[{re.escape(target)}/([\w.-]+)\]", pr["title"])
        if m:
            ids.add(m.group(1))
    return ids


def run_agent(agent, prompt, root, minutes, model):
    if agent == "claude":
        cmd = ["claude", "-p", "--permission-mode", "acceptEdits",
               "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash(lake:*),Bash(nice:*),Bash(python3:*),"
               "Bash(git diff:*),Bash(git status:*),Bash(git checkout -- CFSG:*),Bash(grep:*),Bash(sed -n:*),"
               "Bash(cat:*),Bash(ls:*),Bash(find:*),Bash(wc:*),Bash(head:*),Bash(tail:*)"]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)
        stdin = None
    elif agent == "codex":
        cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check"]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)
        stdin = None
    elif agent.startswith("cmd:"):
        cmd = shlex.split(agent[4:])
        stdin = prompt
    else:
        raise SystemExit(f"unknown agent {agent}")
    log(f"agent {agent} started (limit {minutes} min)")
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=root, input=stdin, text=True, capture_output=True, timeout=minutes * 60)
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = f"timeout after {minutes} min\n" + (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else f"timeout after {minutes} min"
    log(f"agent finished after {round((time.time() - t0) / 60, 1)} min")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--root", required=True, help="Lean checkout used for the work (created if missing)")
    ap.add_argument("--agent", default="claude")
    ap.add_argument("--model", default=None)
    ap.add_argument("--candidate", default=None)
    ap.add_argument("--minutes", type=int, default=120, help="time limit for the agent")
    ap.add_argument("--min-tokens", type=int, default=50)
    ap.add_argument("--no-pr", action="store_true")
    ap.add_argument("--skip-prepare", action="store_true", help="the checkout is already prepared and built")
    a = ap.parse_args()
    root = os.path.abspath(os.path.expanduser(a.root))
    target = a.target
    pilot = os.path.join(REPO, "data", "pilot", target)
    verdicts = os.path.join(REPO, "data", "ledger", "verdicts")
    os.makedirs(verdicts, exist_ok=True)

    # 1. prepare
    if not a.skip_prepare:
        log("preparing the Lean checkout")
        sh([os.path.join(HERE, "apply_patches.sh"), root, target], capture=False)
        sh(["lake", "exe", "cache", "get"], cwd=root, capture=False, check=False)
        log("building the target (first run: tens of minutes)")
        sh(["nice", "-n", "15", "lake", "build", *modules(root, target)], cwd=root, capture=False)
    base = sh(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if sh(["git", "status", "--porcelain", "CFSG"], cwd=root).stdout.strip():
        raise SystemExit(f"{root} has uncommitted changes under CFSG; clean it first")

    # 2. pick
    cands = [json.loads(l) for l in open(os.path.join(pilot, "candidates.jsonl"), encoding="utf-8") if l.strip()]
    done = {f[:-5] for f in os.listdir(verdicts) if f.endswith(".json")}
    claimed = set() if a.no_pr else open_claims(target)
    pool = [c for c in cands if (c["id"] == a.candidate if a.candidate else c["id"] not in done | claimed)]
    if not pool:
        raise SystemExit("no candidate available")
    c = pool[0]
    log(f"candidate {c['id']}: {c['title']} (estimate {c['estimate']} tokens)")

    # 3. claim
    branch = f"contrib/{target}/{c['id']}"
    pr_url = None
    if not a.no_pr:
        sh(["git", "fetch", "-q", "origin", "main"], cwd=REPO)
        sh(["git", "switch", "-q", "-c", branch, "origin/main"], cwd=REPO)
        claim = os.path.join(REPO, "data", "claims", target, c["id"] + ".json")
        os.makedirs(os.path.dirname(claim), exist_ok=True)
        json.dump({"candidate": c["id"], "since": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "agent": a.agent}, open(claim, "w"), indent=2)
        sh(["git", "add", claim], cwd=REPO)
        sh(["git", "commit", "-q", "-m", f"Claim {target}/{c['id']}"], cwd=REPO)
        sh(["git", "push", "-q", "-u", "origin", branch], cwd=REPO)
        pr_url = sh(["gh", "pr", "create", "--draft", "--title", f"[{target}/{c['id']}] {c['title']}",
                     "--body", f"## 報告\n候補 `{c['id']}` に着手中（自動実行）．\n\n{c['summary']}"],
                    cwd=REPO).stdout.strip()
        log(f"claimed: {pr_url}")

    # 4. rewrite
    with tempfile.TemporaryDirectory() as tmp:
        concept_file = os.path.join(tmp, "concept.json")
        protected = ", ".join(l.strip() for l in open(os.path.join(pilot, "protected.txt")) if l.strip())
        prompt = PROMPT.format(target=target, protected=protected, min_tokens=a.min_tokens, base=base,
                               verify=os.path.join(HERE, "verify.py"), concept_file=concept_file, **c)
        agent_log = run_agent(a.agent, prompt, root, a.minutes, a.model)
        concept = {}
        if os.path.exists(concept_file):
            try:
                concept = json.load(open(concept_file))
            except ValueError:
                concept = {}

    # 5. judge (never trusts the agent's own verdict)
    vpath = os.path.join(verdicts, c["id"] + ".json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "verify.py"), "--root", root, "--base", base,
                        "--target", target, "--min-tokens", str(a.min_tokens), "--json", vpath], text=True)
    verdict = json.load(open(vpath))
    verdict.update(candidate=c["id"], agent=a.agent, model=a.model,
                   concept=concept.get("name", ""), meaning=concept.get("meaning", ""),
                   date=datetime.date.today().isoformat())
    json.dump(verdict, open(vpath, "w"), indent=2, ensure_ascii=False)
    with open(os.path.join(REPO, "out", f"agent-{c['id']}.log"), "w") as f:
        f.write(agent_log)
    log(f"verdict: {verdict['verdict']} {verdict.get('reason', '')}")

    if verdict["verdict"] != "accept":
        sh(["git", "checkout", "-q", "--", "CFSG"], cwd=root, check=False)
        sh(["git", "clean", "-fdq", "CFSG"], cwd=root, check=False)
        if pr_url:
            sh(["git", "add", vpath], cwd=REPO)
            sh(["git", "commit", "-q", "-m", f"Record rejected attempt {target}/{c['id']}"], cwd=REPO)
            sh(["git", "push", "-q"], cwd=REPO)
            sh(["gh", "pr", "close", pr_url, "--comment",
                f"不採用（{verdict['phase']}: {verdict['reason']}）．判定記録だけ残します．"], cwd=REPO, check=False)
        sys.exit(1)

    # 6. record
    name = concept.get("name") or c["id"]
    sh(["git", "add", "-A", "CFSG"], cwd=root)
    sh(["git", "-c", "user.name=concept-mining", "-c", "user.email=concept-mining@users.noreply.github.com",
        "commit", "-q", "-m", f"Concept: {name}\n\n{concept.get('meaning', '')}\n\nCandidate {c['id']}, "
        f"saves {verdict['tokens_saved']} tokens."], cwd=root)
    pdir = os.path.join(REPO, "lean", "patches", target)
    os.makedirs(pdir, exist_ok=True)
    n = 1 + len([f for f in os.listdir(pdir) if f.endswith(".patch")])
    patch = os.path.join(pdir, f"{n:04d}-{c['id']}.patch")
    with open(patch, "w") as f:
        f.write(sh(["git", "format-patch", "-1", "--stdout", "HEAD"], cwd=root).stdout)
    before = os.path.join(REPO, "out", f"measure-{c['id']}-before.json")
    after = os.path.join(REPO, "out", f"measure-{c['id']}-after.json")
    last = os.path.join(pilot, "measure_latest.json")
    if os.path.exists(last):
        os.replace(last, before)
    else:
        json.dump(json.load(open(os.path.join(pilot, "baseline.json"))), open(before, "w"))
    log("measuring (exports declarations with Lean)")
    sh([sys.executable, os.path.join(HERE, "ledger.py"), "measure", "--root", root, "--prefix", f"CFSG.{target}",
        "--protected", os.path.join(pilot, "protected.txt"), "--out", after])
    json.dump(json.load(open(after)), open(last, "w"), indent=2)
    uses = 0
    if concept.get("name"):
        leaf = re.escape(concept["name"].split(".")[-1])
        out = sh(["git", "grep", "-ow", "-E", leaf, "--", f"CFSG/{target}"], cwd=root, check=False).stdout
        uses = len(out.splitlines())
    sh([sys.executable, os.path.join(HERE, "ledger.py"), "concept", "--target", target, "--concept", name,
        "--meaning", concept.get("meaning", ""), "--before", before, "--after", after, "--uses", str(uses),
        "--commit", os.path.basename(patch)])
    sh([sys.executable, os.path.join(HERE, "ledger.py"), "history", "--target", target, "--measure", after,
        "--note", f"after {name}"])
    log(f"accepted: {patch}")
    if pr_url:
        sh(["git", "add", patch, vpath, last, os.path.join(REPO, "data", "ledger")], cwd=REPO)
        sh(["git", "commit", "-q", "-m", f"Concept {name} ({target}/{c['id']})"], cwd=REPO)
        sh(["git", "push", "-q"], cwd=REPO)
        body = (f"## 報告\n概念 `{name}` を導入し，{target} が {verdict['tokens_saved']} トークン"
                f"（{verdict['code_lines_saved']} 行）縮みました．判定は自動（tools/verify.py）．\n\n"
                f"意味（AIの下書き）：{concept.get('meaning', '')}\n")
        sh(["gh", "pr", "edit", pr_url, "--body", body], cwd=REPO)
        sh(["gh", "pr", "ready", pr_url], cwd=REPO)
        log(f"ready for the CI recheck: {pr_url}")


if __name__ == "__main__":
    main()
