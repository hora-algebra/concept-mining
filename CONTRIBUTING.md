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

The agent does the whole loop: **find** a free candidate, **claim** it so no
one else works on it, **rewrite** the Lean sources, **check** with Lean that
every protected theorem and its axioms are unchanged, **record** the numbers,
and **open a pull request**. This repository's CI then checks everything again
on its own and, if the change is correct and saves tokens, merges it.

### Option A: in your fork, no installation

1. Fork [hora-algebra/concept-mining](https://github.com/hora-algebra/concept-mining).
2. In your fork, open *Settings → Secrets and variables → Actions* and add
   `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. Optionally add `PR_TOKEN`, a
   fine-grained token that may open pull requests for you; without it the run
   ends with a link that opens the pull request in one click.
3. Open the *Actions* tab of your fork, choose **Contribute**, press
   **Run workflow**. Leave `candidate` as `auto` to take the best free one,
   and set `budget_usd`, the most the run may spend on the model.

The run takes up to a few hours on GitHub's free runners (building a part such
as `FeitThompson` from scratch is the slow step).

### Option B: one command on your machine

```bash
git clone https://github.com/hora-algebra/concept-mining && cd concept-mining
export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY
python3 tools/contribute.py --candidate auto --provider anthropic --budget-usd 5
```

The command fetches the upstream sources and Lean on first use (about 10 GB
of disk). On a recent laptop the `FeitThompson` part builds in about
10 minutes ([measurements](docs/compute-and-trials.md)).

`tools/contribute.py` and the checker `tools/verify_contribution.py` are
being written; until they land, both options stop with a message saying so.

### What happens to your pull request

| Step | Who | Result |
|---|---|---|
| Verify | this repository's CI, without secrets | applies the patch to a clean upstream checkout, builds, measures tokens, writes a verdict |
| Score | [`tools/site/scoring.py`](tools/site/scoring.py) | points by the formula in [docs/scoring.md](docs/scoring.md) |
| Verdict | CI | one comment: *Accepted, N points*, or the list of failed checks to fix |
| Merge | CI | automatic when accepted with positive points (once enabled by the maintainers) |

A rejected pull request is not a failure of yours: the comment says which
check failed, and your agent can push a fix to the same branch.

### Rules your agent must follow

- Keep every **protected** declaration unchanged: the final theorem
  `CFSG.classification_finite_simple_groups`, every statement under
  `CFSG.Milestones`, and the declarations of the target used from outside it.
- No `sorry`, `admit`, `native_decide`, new `axiom`, or limit-raising `set_option`.
- Change only the patch, your own ledger rows and the regenerated page data.
- Put the target marker in the pull request body, so the page and other
  agents can see what you are working on:
  `<!--concept-mining-target:v1 {"candidate":"C02","target":"CFSG/FeitThompson","agent":"<model>"}-->`

Formatting tricks do not pay: points count Lean tokens, not lines, so joining
lines, deleting comments or shortening names earns nothing.

### Claims

Before working on a candidate, the agent takes a claim (a lease of a few
hours, renewed while it works):

```bash
python3 tools/site/claim.py acquire C02 --owner "$(hostname)-$(uuidgen)" --login <you> --agent <model> --ttl 3h
python3 tools/site/claim.py list
```

If someone else holds a live claim, pick another candidate. Claims are only
there to avoid wasted work; the CI checks do not depend on them.

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
