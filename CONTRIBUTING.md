# Contributing to concept-mining

We are refactoring the Lean formalization of the classification of finite
simple groups ([AxiomMath/CFSG](https://github.com/AxiomMath/CFSG)) to find
the concepts that make it shorter. There are three ways in, and two of them
need no Lean at all.

| You are | You can | You need |
|---|---|---|
| a mathematician | say what a repeated idea is, or should be, called | a GitHub account |
| a Lean user | rewrite a candidate and measure what it saves | Lean 4, about 10 GB of disk |
| someone with machines or storage | host builds or a shared build cache | a strong Linux machine or object storage |

Progress is shown on the progress page ([`docs/site/`](docs/site); see
[`tools/site/README.md`](tools/site/README.md) to run it locally). Candidates
that are ready to pick up are listed there and in
[`docs/first-issues.md`](docs/first-issues.md).

## Mathematicians: name a concept

The formalization was written by a machine. It often defines the same notion
several times under different names, or proves the same argument again in
each local setting. Telling us what these copies have in common is the most
valuable thing a group theorist can do here, and it needs no Lean.

**First step.**

1. Open [`docs/first-issues.md`](docs/first-issues.md) and pick a candidate
   marked `name a concept`, for example C05 (components and subnormal
   subgroups) or C09 (finite fields of odd characteristic).
2. Look at the definitions it lists. Each name links to its source through the
   upstream repository; searching the name in
   [AxiomMath/CFSG](https://github.com/AxiomMath/CFSG) finds it.
3. Open an issue with the **Name a concept** template, or comment on the
   existing issue. Say which copies are the same notion, which differ, and
   what the shared notion is called in the literature (with a reference if you
   have one).

That comment is a contribution in its own right: it turns a list of names
into a concept that a Lean user can then implement. When the refactoring
lands, the ledger records the concept with your one-sentence meaning.

You can also propose a candidate of your own: if you see an argument in the
classification that you expect the formalization to repeat (a standard
reduction, a recurring configuration), describe it in an issue.

## Lean users: refactor a candidate

**Setup.**

```bash
git clone --filter=blob:none --depth 1 https://github.com/AxiomMath/CFSG.git cfsg
cd cfsg
lake exe cache get          # Mathlib cache
lake build CFSG.FeitThompson   # a closed part; about 10 minutes on a laptop
```

A sparse checkout of `CFSG/**/*.lean` (leaving out the binary certificate
data) is enough for source work; see
[`docs/stage1-map.md`](docs/stage1-map.md#size-of-the-upstream-repository).
Build times and memory per part are in
[`docs/compute-and-trials.md`](docs/compute-and-trials.md).

**First step.**

1. Pick a candidate marked `refactor`. C02 (merge the two definitions of
   p-rank) is the smallest. Comment on its issue to claim it, so that two
   people do not do the same work; it then shows as "claimed" on the progress
   page.
2. Do the refactoring on a branch of the upstream sources.
3. Check the rules below, then open a pull request **in this repository** with
   the **Refactoring** template: a link to your upstream branch or a patch,
   and the new ledger rows.

**Rules.** A refactoring counts only if

- the statement of the final theorem `CFSG.classification_finite_simple_groups`
  is unchanged, and `#print axioms` on it reports the same axioms as before;
- the part you touched still builds;
- no `sorry` and no new `axiom`.

**Recording the result.** Add one row per concept to
[`data/ledger/concepts.tsv`](data/ledger) (columns: `date, target, concept,
meaning, lines_before, lines_after, lines_saved, uses, commit`) and one row to
`data/ledger/history.tsv` (`date, target, lines_total, declarations, note`).
`meaning` is one or two sentences a mathematician can read without Lean. Then
run

```bash
python3 tools/site/build_site.py
```

which checks the rows and regenerates the page data. Commit both. CI runs the
same checks on your pull request; see
[`tools/site/README.md`](tools/site/README.md#what-the-checks-catch). CI does
not build Lean, so say in the pull request how you checked the build.

## Compute: offer builds or a cache

A full build of the formalization is extrapolated at 275–430 core-hours and
110–550 GB of output (not measured; see
[`docs/compute-and-trials.md`](docs/compute-and-trials.md)). No prebuilt
build cache is published upstream. A shared cache would let every contributor
rebuild only what they touch.

**First step.** Open an issue with the **Offer compute** template and say
what you can provide (cores, memory, disk, storage, for how long) and under
what conditions. We do not need credentials in the issue; we will follow up
there.

## Everything else

- Questions, corrections to the map, and ideas for better size measures:
  open an issue.
- The text on the progress page (folder descriptions, fields) was assigned
  from folder names and has not been reviewed by experts. Corrections are
  welcome as pull requests to [`data/site/folders.tsv`](data/site/folders.tsv).
- By contributing you agree that your contribution is licensed under
  Apache-2.0, like the rest of the repository.
