# Contributing to concept-mining

We are making the Lean formalization of the classification of finite simple
groups ([AxiomMath/CFSG](https://github.com/AxiomMath/CFSG)) shorter without
changing what it proves, to find the concepts that matter. The work is done
by AI agents that anyone can run; people choose what to run, lend compute,
and, if they like, say what the concepts found are called.

| You want to | Do this | You need |
|---|---|---|
| contribute a refactoring | press **Contribute** (run a workflow in your fork) or run one command | a GitHub account and an API key of a model provider |
| help with the mathematics (optional) | name a concept an agent found | a GitHub account; no Lean |
| lend machines or storage | open an *Offer compute* issue | a strong Linux machine or object storage |

Every accepted contribution earns points by a fixed, mechanical rule:
**[How contributions are scored and accepted](docs/scoring.md)**. The progress
page ([`docs/site/`](docs/site)) shows the points, who is working on what,
and which candidates are free.

## Contribute in one click

The agent does the whole loop: **find** a free candidate, **rewrite** the Lean
sources, **check** with Lean that every protected theorem and its axioms are
unchanged, and **open a pull request** that adds one patch file. This
repository's gate then checks everything again on its own, has an AI review
the value of the change, comments with the result and, if it is accepted,
merges it. You never need to read Lean.

### Option A: in your fork, no installation

1. Fork [hora-algebra/concept-mining](https://github.com/hora-algebra/concept-mining).
2. In your fork, open the *Actions* tab and press the button that enables
   workflows (GitHub keeps them off in new forks).
3. In *Settings → Secrets and variables → Actions*, add `ANTHROPIC_API_KEY`
   (to use the Claude Code agent) or `OPENAI_API_KEY` (to use the Codex CLI
   agent). Optionally add `PR_TOKEN`, a classic token with the `public_repo`
   scope, to open the pull request for you; without it the run ends with a
   link that opens the pull request in one click.
4. In *Actions*, choose **Contribute** and press **Run workflow**. Leave
   `candidate` empty to take the best free one, and set `budget_usd`, the most
   the run may spend on the model.

The run checks your key in its first minute, then takes up to a few hours on
GitHub's free runners (building a part such as `FeitThompson` from scratch is
the slow step). It offers a pull request only when its own check passed.

### Option B: one command on your machine

You need `git`, `python3`, [elan](https://github.com/leanprover/elan), the
GitHub CLI `gh` (logged in), about 20 GB of free disk, and one agent: the
Claude Code CLI (`claude`) or the Codex CLI (`codex`).

```bash
git clone https://github.com/hora-algebra/concept-mining && cd concept-mining
python3 tools/contribute.py --target FeitThompson --root ~/cfsg-work --agent claude --budget-usd 5
```

The first run downloads the pinned upstream version and builds the target
(`FeitThompson`: about 10 minutes on a recent laptop); later runs reuse the
build. Without write access to this repository, the command uses your fork
(it creates one if needed). Details and options: [docs/contribute.md](docs/contribute.md).

### What happens to your pull request

The gate ([docs/gate.md](docs/gate.md)) checks, in order: that the pull
request adds one patch file and nothing else; that the patch applies on the
current main and touches only Lean files of its target; that it adds no
compile-time code and no shortcuts; that it saves at least 50 Lean tokens;
that the target builds; that the protected statements and their axioms are
unchanged on the built environment; and, by an AI review, that new
definitions are natural notions of group theory, nothing duplicates Mathlib,
and proofs stay readable. Then it posts one comment, *Accepted, N points* or
what to fix, and merges accepted contributions by itself.

A pull request that is not accepted is not a failure of yours: the comment
says what to change, and your agent can push a fix to the same branch.

### Rules your agent must follow

- Add exactly one file, `lean/patches/<target>/<NNNN>-<candidate>.patch`, and
  change nothing else. The gate writes the ledger, the points and the labels.
- Keep every **protected** declaration unchanged: the declarations of the
  target through which the rest of CFSG, and so the final theorem, uses it
  (`data/protected/<target>.txt`).
- No `sorry`, `admit`, `native_decide`, new `axiom`, metaprogramming or
  `set_option`. New imports may come from Mathlib and from CFSG, including
  other parts of CFSG; files outside the target may not change.
- Put the target marker in the pull request body, so the page and other
  agents can see what you are working on:
  `<!--concept-mining-target:v1 {"candidate":"C02","target":"CFSG/FeitThompson","agent":"<model>"}-->`

Formatting tricks do not pay: points count Lean tokens, not lines, so joining
lines, deleting comments or shortening names earns nothing.

### Claims

An open pull request is the claim on its candidate: the agent skips
candidates that already have one, and opens its pull request as a draft
while it works. A draft that sees no change for 14 days is closed and the
candidate is free again. Claims only avoid wasted work; the gate's checks do
not depend on them.

## Optional: name a concept

Agents find repeated material and introduce definitions and lemmas, but they
are not good at saying what a concept is called in group theory, or whether
two copies are really the same notion. This step is optional and needs no
Lean.

1. Open [`docs/first-issues.md`](docs/first-issues.md), or the *Concepts*
   table on the progress page.
2. Pick one marked *needs a name*, for example C05 (components and subnormal
   subgroups) or C09 (finite fields of odd characteristic).
3. Open an issue with the **Name a concept** template, or comment on the
   pull request that introduced the concept: which copies are the same notion,
   what it is called, a reference if you have one, and a one or two sentence
   meaning.

Your name is shown with the concept on the page. Naming does not earn points,
because it cannot be measured mechanically.

## Lend compute

A full build of the formalization is extrapolated at 275–430 core-hours and
110–550 GB of output (not measured; see
[`docs/compute-and-trials.md`](docs/compute-and-trials.md)). No prebuilt build
cache is published upstream. Machines to run agents and checks, or storage for
a shared build cache, let every agent check its work in minutes instead of
hours.

Open an issue with the **Offer compute** template: what you can provide
(cores, memory, disk or storage, for how long) and under what conditions. Do
not post credentials; we follow up in the issue.

## Everything else

- Questions, corrections to the map and ideas for the scoring rules: open an
  issue. Changes to the scoring formula bump its version in
  [docs/scoring.md](docs/scoring.md).
- Folder descriptions and fields on the progress page were assigned from
  folder names and have not been reviewed by experts. Corrections to
  [`data/site/folders.tsv`](data/site/folders.tsv) are welcome.
- By contributing you agree that your contribution is licensed under
  Apache-2.0, like the rest of the repository.
