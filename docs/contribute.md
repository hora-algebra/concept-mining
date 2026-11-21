# Contribute a refactoring

You lend an AI agent and pay for what it uses. The agent makes the Lean proof of
the classification of finite simple groups shorter by introducing one concept,
Lean checks that every theorem still says exactly the same thing, and this
repository merges the result. You do not need to know Lean.

A contribution is a pull request that adds one file,
`lean/patches/<target>/NNNN-<candidate>.patch`, and nothing else. There are two
ways to make one.

## A. In your browser (nothing to install)

1. Sign in to GitHub, open [hora-algebra/concept-mining](https://github.com/hora-algebra/concept-mining),
   press **Fork**, then **Create fork**.
2. In your fork, open the **Actions** tab and press **I understand my workflows,
   go ahead and enable them**. GitHub switches Actions off in every new fork;
   until you press this button, nothing can run.
3. In your fork, open **Settings → Secrets and variables → Actions → New
   repository secret** and add your API key under exactly one of these names:
   - `ANTHROPIC_API_KEY` to use Claude (key from [console.anthropic.com](https://console.anthropic.com)), or
   - `OPENAI_API_KEY` to use Codex (key from [platform.openai.com](https://platform.openai.com)).
4. Optional: add a secret `PR_TOKEN`, a classic personal access token with the
   `public_repo` scope ([github.com/settings/tokens](https://github.com/settings/tokens)).
   With it the run opens the pull request for you. The agent never sees this
   token: it is used on a separate machine after the agent has finished.
5. Open **Actions → Contribute → Run workflow**, choose `claude` or `codex`, and
   press the green **Run workflow** button.

The first step checks your key; if it is missing or rejected, the run stops
within a minute and says so. A whole run takes up to about five hours, most of
it building the library.

When the run has finished, open it and read the summary at the top:

| The summary says | What to do |
|---|---|
| **Accepted** and *Open the pull request* | press the link, then **Create pull request**; the title and text are filled in |
| **Accepted** and a link to a pull request | nothing: it is already open (you added `PR_TOKEN`) |
| **Not accepted** | nothing was handed in; run it again to try the next candidate |
| **Stopped** | the sentence says what to change; then run it again |

## B. On your computer (one command)

You need a Mac or Linux computer with 20 GB of free disk and `git`, `python3`,
Lean's installer [elan](https://github.com/leanprover/elan#installation), the
GitHub CLI [`gh`](https://cli.github.com) (run `gh auth login` once), and one
agent: Claude Code (`npm install -g @anthropic-ai/claude-code`) or Codex
(`npm install -g @openai/codex`), logged in or with its API key set.

```bash
git clone https://github.com/hora-algebra/concept-mining && cd concept-mining
python3 tools/contribute.py --target FeitThompson --root ~/cfsg-work --agent claude --budget-usd 5
```

The command picks a free candidate, builds the library in `~/cfsg-work` (the
first time about 10 minutes on a recent laptop, longer on smaller machines;
later runs reuse it), and lets the agent work. As soon as the work passes the
quick checks, a draft pull request reserves the candidate; it becomes ready for
review when Lean accepts the result, and is closed otherwise. If you cannot push
to this repository, your fork is used (and created if you have none). If
something is missing, the command stops with one sentence saying what to do.
Run `git pull` before each new run.

## What happens to your pull request

| Step | What is checked |
|---|---|
| Correctness | CI applies the patch to a clean copy of the library and builds it with Lean: every protected theorem and its axioms are unchanged, nothing like `sorry` was added, and the library got smaller |
| Value | an AI review asks three questions: does the change introduce a natural group-theory concept, does it avoid duplicating Mathlib, and is the result readable |
| Merge | when both pass, the pull request is merged automatically and its points ([how they are counted](scoring.md)) appear on the progress page |

CI reports the result in one comment on the pull request. A draft pull request
only reserves its candidate and is not checked. The details are in
[the contribution gate](gate.md).

## If the comment says "Not accepted"

The comment lists what to fix. Let the agent fix it on the same branch:

- in the browser: **Actions → Contribute → Run workflow** with `fix_pr` set to
  the number of your pull request;
- on your computer: `python3 tools/contribute.py --root ~/cfsg-work --agent claude --fix <number>`.

The agent reads the comment, changes the patch, checks it again and pushes it
to the same pull request; CI then checks it again. A pull request gets at most
five AI reviews; after that it is closed, and a new attempt needs a different
approach. If you would rather stop, close the pull request.

## What it costs

- **Claude**: the agent stops once it has spent `budget_usd` (default 5 USD).
- **Codex**: nothing in the run limits what Codex spends; the run only stops
  Codex after `minutes` (default 120). Use a key whose account has a spending
  limit you are comfortable with.
- GitHub Actions in a public fork is free.

## Options of the command

| Option | Meaning |
|---|---|
| `--target T` | the part of the library (a folder of `data/pilot/`) |
| `--agent claude`, `codex` or `"cmd:<command>"` | the agent; a command receives the instructions on standard input |
| `--model M` | the agent's model |
| `--budget-usd N` | Claude only: the most the agent may spend |
| `--minutes N` | time limit for the agent (default 120) |
| `--candidate ID` | work on this candidate instead of the best free one |
| `--pr open`, `link` or `none` | open the pull request (default); push to your fork and print a link that opens it; or keep everything on this computer |
| `--fix N` | fix pull request N |
| `--pass-env NAME` | also give the agent this environment variable; otherwise it sees only its own provider's key and never a GitHub token |

The agent's output, the verdict and the patch of each run are kept on your
computer in `out/contribute/<target>/<candidate>/`.

## What the check requires

Before anything is handed in, `tools/verify.py` runs the machine checks of
[the contribution gate](gate.md) on your computer (all but the AI review), so a
change that fails them is never sent. In short: only `.lean` files under
`CFSG/<target>/` change; no new `sorry`, `axiom`, `set_option`, compile-time
code or similar shortcuts; the target shrinks by at least 50 Lean tokens;
everything builds; and the protected theorems keep exactly their statements and
axioms.

Size is counted in Lean tokens ([`tools/size.py`](../tools/size.py)):
whitespace, line breaks, comments and the length of names count for nothing,
so only removing definitions, hypotheses, terms and proof steps makes it drop.
