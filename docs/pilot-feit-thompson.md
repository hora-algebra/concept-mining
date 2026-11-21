# Pilot: Feit–Thompson

The first refactoring trials ran on `CFSG/FeitThompson` of
[AxiomMath/CFSG](https://github.com/AxiomMath/CFSG) at commit `965a077`. That
folder holds the odd order theorem. It is a closed island: nothing in it uses
the rest of CFSG, and it builds in about 10 minutes on a 16-core laptop.

## Baseline

| | Value |
|---|---|
| Modules | 1,414 |
| Code lines (non-blank, outside comments) | 240,567 |
| Lean tokens (`tools/size.py`) | 2,868,073 |
| Declarations | 19,794 |
| Declarations needed by the protected theorem | 16,446 |
| Their code lines (**the ledger's baseline**) | **189,217** |
| Declarations not needed (left untouched, not counted) | 3,348 (21,147 lines) |

**Protected theorem.** The only declaration of the folder that the rest of
CFSG uses is `CFSG.FeitThompson.isSolvable_of_odd_natCard`, which states that a
finite group of odd order is solvable. Its statement and axioms (`propext`,
`Classical.choice`, `Quot.sound`) are recorded in
`data/pilot/FeitThompson/protected_baseline.txt`. Every change must reproduce
them exactly.

The counts come from the elaborated declarations of the built checkout
(`tools/export_decls.py`, `tools/mine.py`). Reachability follows the constants
each declaration actually uses.

## Candidates

`tools/candidates.py` found 52 candidates of two kinds
(`data/pilot/FeitThompson/candidates.jsonl`, ordered by estimated saving):

- **copies**: definitions that coincide after copies are identified, with
  the lemmas that then coincide too.
- **bundles**: multi-line hypotheses restated in many statements.

| Candidate | Kind | What it is | Estimated tokens |
|---|---|---|---|
| bundle-dd790378 | bundle | two TI conditions on the cyclic TI difference set, restated in 27 statements | 3,833 |
| copies-hallCoreIn | copies | Hall core of a subgroup, 5 definitions, 18 coinciding lemma groups | 2,132 |
| copies-CauchySchwarzProjection-irr | copies | irreducible characters, 3 definitions | 1,797 |
| copies-Prep06-fittingIn | copies | Fitting subgroup of a subgroup, 7 definitions | 856 |
| copies-cfInner | copies | inner product of class functions, 3 definitions | 846 |
| copies-centralizerWithin | copies | centralizer inside a subgroup, 2 definitions | 743 |
| copies-dadeExtend | copies | Dade extension map, 2 definitions | 657 |
| bundle-56a7c48d | bundle | a Dade compatibility hypothesis, 11 statements | 562 |
| bundle-92bc9128 | bundle | "conjugates of A are equal or disjoint", 9 statements | 560 |

Estimates rank candidates and nothing more. They overcount: the Hall core was
estimated at 2,132 tokens and saved 721.

Two more signals were measured but not turned into candidates. There are 180
groups of theorems whose elaborated statements are already identical (about
1,100 lines). Repeated 7-binder windows appear in up to 138 statements, but
these are mostly structure projections, which cost nothing in the source.

## Adopted concepts

All three were accepted by `tools/verify.py`, which builds every module and
checks the protected theorem, the forbidden constructs and the token count.
Each is one patch.

| Concept | Meaning | Code lines saved | Tokens saved | Made by |
|---|---|---|---|---|
| `hallCoreIn` | the Hall core of a subgroup, as a subgroup of the ambient group; defined five times before | 57 | 721 | recipe written in this session (`tools/recipes/hall_core_in.py`) |
| `IsTIDiff` | the cyclic TI difference set of (W, W₁, W₂) has stabilizer W and is disjoint from its conjugates outside W; `IsCyclicTIPair` now extends it | 289 | 5,604 | **the unattended loop** (`tools/contribute.py`, Claude Code, 10 minutes, no human step) |
| `Irr` | the irreducible complex characters of a group; defined three times before | 0 (all 40 lines saved were in declarations the theorem does not need) | 564 | the unattended loop, 10 minutes |

Code lines in this table are the ledger's: lines of the needed declarations.
`data/ledger/concepts.tsv` and `data/ledger/history.tsv` hold the rows, and
`data/ledger/verdicts/` holds the full verdicts.

## Not achieved

Every candidate other than the three above remains **open** (not attempted). No
attempt has been rejected yet. Rejections will be recorded in
`data/ledger/verdicts/` with the deciding phase.

## How the Lean code is stored

This repository never copies the formalization. `lean/UPSTREAM` pins the
upstream commit. `lean/patches/<target>/NNNN-<candidate>.patch` holds one
concept per patch, in `git format-patch` form. The patches are applied in
order:

```bash
tools/apply_patches.sh ~/cfsg-work FeitThompson
```

The command checks that applying the three patches to `965a077` gives exactly
the tree that was built and judged (same git tree hash).

## Reproduce

```bash
python3 tools/fetch_proofmap.py --out ~/.cache/concept-mining/proofmap
```

```bash
python3 tools/island.py --cache ~/.cache/concept-mining/proofmap --prefix CFSG.FeitThompson --out data/pilot/FeitThompson
```

```bash
tools/apply_patches.sh ~/cfsg-work FeitThompson
```

Build the target in `~/cfsg-work` (`lake exe cache get`, then `lake build` of
the FeitThompson modules), then run the following. For the baseline, run them
on the unpatched commit (`git -C ~/cfsg-work checkout 965a077`, then build again).

```bash
python3 tools/export_decls.py --root ~/cfsg-work --prefix CFSG.FeitThompson --out out/ft_decls.tsv
```

```bash
python3 tools/mine.py --decls out/ft_decls.tsv --root ~/cfsg-work --protected data/pilot/FeitThompson/protected.txt --out data/pilot/FeitThompson
```

```bash
python3 tools/candidates.py --decls out/ft_decls.tsv --root ~/cfsg-work --target FeitThompson --out data/pilot/FeitThompson/candidates.jsonl
```

To contribute the next concept, see [contribute.md](contribute.md).
