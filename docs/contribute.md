# Contribute with one command

A contribution introduces one concept into the formalization (one definition
instead of several copies, one named hypothesis instead of a restated one, ...)
and makes the code measurably smaller without changing what is proved. You do
not write Lean yourself: an AI of your choice does the rewriting, Lean decides,
and the main repository checks the result again before it is merged.

## Run it

You need a Mac or Linux machine with about 20 GB of free disk, `git`, `python3`,
[elan](https://github.com/leanprover/elan), the GitHub CLI `gh` (logged in), and
one AI agent: the Claude Code CLI (`claude`), the Codex CLI (`codex`), or any
command that reads a prompt on standard input.

```bash
git clone https://github.com/hora-algebra/concept-mining && cd concept-mining
```

```bash
python3 tools/contribute.py --target FeitThompson --root ~/cfsg-work --agent claude
```

That is all. The first run downloads the pinned version of the formalization
and builds the target (FeitThompson: about 10 minutes on a recent 16-core
laptop, longer on smaller machines); later runs reuse the build. Then the
command:

1. picks the best open candidate from `data/pilot/<target>/candidates.jsonl`
   that nobody has claimed;
2. claims it by opening a draft pull request titled `[<target>/<candidate>]`
   (an open pull request with that title is a claim; claims are visible to
   everyone and two runs never work on the same candidate);
3. lets the agent introduce the concept, with a time limit (`--minutes`,
   default 120);
4. judges the result with `tools/verify.py` (below), ignoring whatever the
   agent says about its own work;
5. if accepted: stores the change as `lean/patches/<target>/NNNN-<candidate>.patch`,
   appends a row to the ledger, and marks the pull request ready; if rejected:
   records the verdict and closes the claim.

Options: `--agent codex` (or `--provider anthropic|openai`), `--agent "cmd:<your command>"`,
`--model <name>`, `--budget-usd <n>` (passed to agents that support a cap),
`--candidate <id>` to choose the candidate, `--no-pr` to do everything locally.
Claims use `tools/site/claim.py` (a lease stored as a Git ref) when it is
present, otherwise the draft pull request's title.

## What counts as a contribution

`tools/verify.py` accepts a change only when all of the following hold. The
phases run in this order and the first failure decides.

| Phase | Requirement |
|---|---|
| scope | only `.lean` files under `CFSG/<target>/` change; new imports come from Mathlib or the target |
| guards | added lines contain no `sorry`, `admit`, `native_decide`, `axiom`, `unsafe`, `implemented_by`, `extern`, kernel-check switches, or compile-time metaprogramming (`#eval`, `run_cmd`, `initialize`, `elab`, `macro`, `syntax`, `IO`) |
| size | the target shrinks by at least 50 Lean tokens |
| build | every module of the target builds |
| protected | the statements and axioms of the protected theorems (`data/pilot/<target>/protected.txt`) are exactly as before, and the axioms are among `propext`, `Classical.choice`, `Quot.sound` |

**Size is counted in Lean tokens**, not characters or lines: an identifier of
any length, a number, a string, or one symbol each count as one token;
whitespace, line breaks and comments count as nothing. Joining lines or
shortening names therefore earns nothing. Only removing definitions,
hypotheses, terms and proof steps makes the count drop. The tokenizer is
`tools/size.py`.

The verdict (`data/ledger/verdicts/<candidate>.json`) has these fields:

| Field | Meaning |
|---|---|
| `verdict` | `accept`, `reject`, or `error` (could not be decided) |
| `phase`, `reason` | the phase that decided and why |
| `target`, `base`, `head` | what was compared |
| `files_changed` | number of changed files |
| `tokens_before`, `tokens_after`, `tokens_saved` | size of the target in tokens |
| `code_lines_before`, `code_lines_after`, `code_lines_saved` | the same in non-blank, non-comment lines (for reference) |
| `build_seconds`, `axioms` | build time; axioms of the protected theorems |
| `candidate`, `agent`, `model`, `concept`, `meaning`, `date` | added by `contribute.py`; `concept` and `meaning` are drafted by the AI |

The ledger (`data/ledger/concepts.tsv`, `data/ledger/history.tsv`) counts code
lines of the declarations that the protected theorems need, so code that was
never used does not inflate the numbers.

## Why the result can be trusted

The contributor's machine is not trusted. On every pull request the main
repository runs, with the scripts of the default branch,

```bash
python3 tools/verify_contribution.py --pr-dir <dir> --upstream <path> --pr-json pr.json --changed changed.txt --out verdict.json
```

where `<dir>` holds only the pull request's `lean/patches/` and `data/ledger/`
(copied as data). It writes the verdict in the schema
`concept-mining-verdict/v1` of [scoring.md](scoring.md); points and the merge
decision are computed from it by `tools/site/scoring.py`. The checker

- rejects the pull request if it changes anything other than new patch files
  under `lean/patches/<target>/`, one verdict, one claim and appended ledger
  rows (`concepts.tsv`, `history.tsv`, `contributions.tsv`);
- rebuilds the base from the pinned upstream commit and the patches already on
  `main` (taken from `main`, not from the pull request);
- applies the new patch and runs the judge **from `main`** with its own
  protected-statement baseline;
- checks that the recorded token numbers equal the recomputed ones.

`tools/ci_verify.sh <target> <work-dir>` runs the same check from a checkout
of the pull request, for local use.

**Protected declarations** of a target are listed in `data/protected/<target>.txt`:
the declarations of the target that something outside it uses. For
FeitThompson that is the odd order theorem alone. The final theorem and the
milestones of CFSG live outside the target and depend on it only through
these declarations, so their statements cannot change while these stay
fixed; checking them directly would need a build of all of CFSG.

Only a pull request that passes is merged automatically. Building the
FeitThompson target from scratch takes roughly 1.5 hours on a standard 4-core
GitHub runner (measured: 9,800 CPU-seconds on an M5 Max, about twice that on a
runner core); caching the base build keyed by the patch list on `main` brings a
typical recheck down to the modules downstream of the change. Lean code from a
pull request is compiled, so the job runs without secrets or write tokens, and
the guards above refuse compile-time code execution.

The name and meaning of each concept are drafted by the AI. A mathematician
may review them afterwards; that review is optional and does not block merging.
