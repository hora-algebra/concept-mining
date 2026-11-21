# Strategy: where an order of magnitude could come from

Status: night of 2026-11-21/22. Written by the strategy session that watches
the mining sessions. Figures are upper bounds unless marked *verified*. The
library is 35,093,004 lines inside declarations (as in
[plan-one-percent.md](plan-one-percent.md)); shares below are of that total.

## The short version

1. **Textual signals are exhausted.** Copies, same proof shape and same
   statement text together bound ideal abstraction at a few percent
   ([compression-map.md](compression-map.md)). Local rewriting will not reach
   10 %.
2. **The large reductions sit at the level of whole theorems.** Every
   declaration has a *price*: the lines that are used only through it (its
   subtree in the dominator tree of the final theorem). Replacing the proof of
   one expensive declaration by a short argument from the rest of the library
   removes its whole price at once.
3. **The first such move is verified on paper and is 1.44 % of the library:**
   the Feit–Thompson theorem is proved twice, and both proofs are used.
   One proof can become a one-line application of the other (below).
4. **The next and larger class is the induction hypothesis.** The final
   theorem is proved by induction on the order with "every proper section is
   known" (`KProper`) in every branch. Classification theorems from the
   literature that are applied only to proper sections could be replaced by
   that hypothesis plus facts about the known groups. This is the step the
   second-generation proof of Gorenstein, Lyons and Solomon takes, and it is
   where most of the remaining price sits.

## Prices: the dominator tree of the final theorem

`tools/analyze_proofmap.py` already records the immediate dominator of every
declaration. Summing lines over dominator subtrees gives each declaration's
price. The top of the tree (prices in lines):

| Declaration | Price | Share |
|---|---|---|
| `Assembly.large_even` (e(G) ≥ 4) | 5,906,131 | 16.8 % |
| `Assembly.component_type` | 3,715,705 | 10.6 % |
| `Assembly.rank_three_even` (e(G) = 3) | 3,336,960 | 9.5 % |
| `Assembly.quasithin` | 1,450,276 | 4.1 % |
| `Milestones.cl_lit_gh74_sectional_two_rank_four_models` (Gorenstein–Harada) | 1,231,219 | 3.5 % |
| `RankThree.GF2n.Parrott.gf2nType_of_noSqE1` | 816,980 | 2.3 % |
| `odd_order_theorem` (ThirdParty/QiuzhenCFSG) | 504,237 | 1.44 % |
| `ClassicalInvolution...toCoreStep'` | 272,576 | 0.78 % |
| `GorensteinWalter.gorensteinWalter` (ThirdParty/QiuzhenCFSG) | 198,807 | 0.57 % |
| `FeitThompson.isSolvable_of_odd_natCard` (CFSG/FeitThompson) | 187,803 | 0.54 % |
| `BenderSuzuki.suzuki` + `theoremSEMinimalStep` (ThirdParty/QiuzhenCFSG) | 172,317 | 0.49 % |

Declarations that are used by two or more of these branches and dominated by
nothing but the final theorem hold another 15 M lines: 8.0 M in pieces of under
1,000 lines each, 3.6 M in pieces of 1,000–10,000 lines. That is the shared
library, the place where a common foundation layer would act.

The full list of declarations with a price of at least 3,000 lines is in
[`data/map/dominator_roots.tsv`](../data/map/dominator_roots.tsv).

## The three kinds of reduction asked about, ranked

| Rank | Kind | Where | Upper bound | Share | How real |
|---|---|---|---|---|---|
| 1 | **A theory rebuilt in isolation** | Feit–Thompson proved twice (ThirdParty/QiuzhenCFSG and CFSG/FeitThompson) | 504,237 | 1.44 % | *verified*: identical statements, both used; Lean not yet run |
|  |  | literature classification theorems applied to sections where `KProper` is available (GH74, Gorenstein–Walter, Bender–Suzuki, ...) | up to ~2.5 M | ~7 % | being checked (use sites, missing catalog facts) |
|  |  | basic group-theory layer re-proved per region | 130,000 | 0.4 % | measured earlier; needs a full build |
| 2 | **One general theorem plus checks per case** | families of independent subtrees whose statements differ only in numbers or type names | 994,793 | 2.8 % | identifier multiset of the statement, so some families may join different statements; sampled families are real (e.g. `GGResIDisp.{A6,A7,B7,C7,D4..D7,E6}.ggResI_type_*`, `ggResQTwoFinite_{A7,B7,C7,D7,E6}`) |
| 3 | **The same skeleton per sporadic or Lie-type group** | files whose paths differ only in a group or Lie-type name | 790,123 | 2.3 % | noisy: section numbers like `F134` match the pattern; overlaps rank 2 |

Rank 2 and 3 overlap each other and the proof-shape families of
[compression-map.md](compression-map.md) (866,990 lines). Together they are of
the order of 1–1.5 M lines, about 3–4 %. The family bound leaves out two false
matches: `Assembly.large_even` and `Assembly.rank_three_even` (their statements
differ only in `4 ≤ evenRank` versus `evenRank = 3`) and the Feit–Thompson pair
(counted in rank 1).

Reproduce:

```bash
python3 tools/strategy/dominator_prices.py --cache ~/.cache/concept-mining/proofmap --out data/map/dominator_roots.tsv
python3 tools/strategy/statement_signatures.py --root ~/cfsg --out out/statement_signatures.tsv
python3 tools/strategy/schema_families.py --cache ~/.cache/concept-mining/proofmap --sigs out/statement_signatures.tsv --out out/schema
```

The signature scan takes about a minute with six processes; each proof-map
load takes a few minutes and about 3 GB of memory.

Exact statement twins below the top are few. Matching every theorem's
normalized statement (binder style, universes and bound names removed) against
every declaration with a price of at least 2,000 lines finds the Feit–Thompson
pair and otherwise only wrappers (a milestone restating a theorem it calls),
families that differ in a dropped constant (`.J4` vs `.M24`) and one copied
development (`KD46.Inst.exists_sec6`, 4,455 lines, already in the
same-statement table).

### A calibration

The Mathematical Components proof of the odd order theorem is reported as
about 170,000 lines including its libraries (L. Théry, 2012; other counts
exist). The native `CFSG/FeitThompson` proof costs 187,803 lines, about the
same. The Qiuzhen proof costs 504,237, about three times as much. Where the
upstream code follows one route, it is not ten times longer than an expert's
proof. **An order of magnitude has to come from choosing fewer and shorter
routes, not from writing each step better.**

### Facts about the known groups are scattered

47,368 theorems (1.59 M lines of their own, 4.5 %) state something about a
specific known group or family: their statements mention `LieModel`,
`IsSporadic`, `alternatingGroup`, `PSL`, `PSU`, `PSp`, `StatedClassicalModel`,
`InCatalog` or similar. 0.80 M of these lines are in LocalAnalysis, 0.18 M in
Quasithin, 0.15 M in RankThree. Only 2,578 of them carry a K-group hypothesis
in the statement. A single catalog of the known groups with their local
properties (the content of the third volume of Gorenstein, Lyons and Solomon)
is the concept that would both serve the induction hypothesis above and
collect these facts in one place. How much of the 1.59 M is the same fact
proved again is not measured yet.

## Meta-strategies compared

| Strategy | What it looks at | Cost | Expected | Status |
|---|---|---|---|---|
| **Price-tag search** (new) | the expensive declarations and their statements; asks what else in the library, Mathlib or the induction hypothesis implies each one | an hour of analysis per class; one Lean bridge per hit | 1.44 % found; up to ~7 % in the K-group class | running |
| Two-layer search over files ([two-layer-search.md](two-layer-search.md)) | files and hypothesis bundles of one region | ~1 h per region | StageK: 0.9 % of Feit–Thompson | done once |
| Statement-schema families | statements equal up to numbers and type names | prototypes need only Mathlib | ≤ 2.8 % | handed to miner-b |
| Cumulative stages / bundled contexts (StageK, generalized) | repeated hypotheses in statements | ~1 h + build per region | ~1 % of each region | proven on Feit–Thompson |
| Cleanup ([plan-one-percent.md](plan-one-percent.md)) | unreachable declarations | build per part | 5.4 % | Permutation tonight (166 k) |
| Comparison with the second-generation proof (GLS) | which literature theorems the revision avoids | reading | qualitative; it is what points at the K-group class | to do |

Why price-tag search works where the file-level search did not: the file-level
search shows a model local material and gets local ideas back. A price tag
shows where a short argument would pay, and asks a question a mathematician
can answer from the statement alone: "is this already implied by something
else we have?". The Feit–Thompson twin is invisible to every textual signal
(binder style, universe annotation and name differ) and obvious from the
price list.

Procedure for the next runs:

1. List the declarations with a price of at least 10,000 lines (a few hundred).
2. Proposal layer, high temperature, several viewpoints: for each one, its
   statement, its users, and the statements of the other expensive
   declarations; ask for implications ("this follows from X plus a short
   argument", "this is only used on proper sections"). Cheap, wide.
3. Verification layer, cold: write the bridge in Lean. Accept only if Lean and
   the token count say so.

## Next moves (decided)

| Who | What | Why |
|---|---|---|
| concept-map | replace the proof of `CFSG.odd_order_theorem` by `CFSG.FeitThompson.isSolvable_of_odd_natCard`; delete what becomes unreachable in ThirdParty/QiuzhenCFSG | 504,237 lines, 1.44 %; QiuzhenCFSG already imports CFSG/FeitThompson, so the build stays cheap |
| miner-a | delete the unreachable `Permutation/FiveTransitive` (166 k lines) | the largest cleanup whose build fits on the laptop tonight |
| miner-b | rank the statement-schema families, prove the general theorems in files that import only Mathlib | the per-case files need builds the laptop cannot do tonight |
| strategist | check whether GH74, Gorenstein–Walter, Bender–Suzuki are applied only to proper sections; list the catalog facts that would replace them | the largest remaining class |

What the laptop can verify tonight is limited by import closures (lines of
other CFSG folders that a folder imports):

| Folder | Own | Imported from elsewhere |
|---|---|---|
| ThirdParty/QiuzhenCFSG | 1.34 M | 0.27 M (CFSG/FeitThompson only) |
| CharacterTheory | 0.46 M | 1.94 M |
| Monster | 0.42 M | 3.67 M |
| Sporadic | 0.61 M | 9.57 M |
| LieType | 0.74 M | 14.5 M |

## Rules that stand in the way, and safe ways to allow more

None of these is changed here; each is a proposal.

1. **Rebuilding every importer.** A contribution must rebuild every module that
   imports a changed file. For a change that only replaces *proofs of
   theorems* (no statement, no definition body) and deletes declarations that
   nothing left refers to, downstream modules cannot break: Lean never looks
   inside a theorem's proof from outside. Proposal: for such patches, build the
   changed modules and check that no remaining source names a deleted
   declaration; skip the downstream rebuild. This turns cross-region route
   replacements from a full-library build into an hour.
2. **Concepts that pay only when they spread.** Catalog facts about the known
   groups (needed to drop GH74 and the like) add lines before anything can be
   deleted. Proposal: the budgeted investment of
   [two-layer-search.md](two-layer-search.md) (option 2), with the investment
   and the later deletions recorded against one concept.
3. **Tactic abbreviations.** `no_metaprogramming` refuses every new `macro`.
   A macro whose body is a single syntax quotation (no `do`, no `elab`, no
   `run_cmd`, no `initialize`) only expands syntax and cannot run code.
   Proposal: allow exactly that form, recognised syntactically, so that one
   proof pattern repeated across many per-case proofs can be named once.
4. **Cleanup rate.** When `cleanup_tokens` is implemented, "dead" should be
   measured on the *base* commit. Otherwise a route replacement, which makes a
   needed proof unneeded and then deletes it, would be paid at a quarter of the
   rate although it is exactly the kind of concept this project looks for.

## Tool note

`tools/skeletons.py` does not recognise `public theorem` (its declaration
pattern lists `private`, `protected`, ... but not `public`). About 11,000
declarations of ThirdParty/QiuzhenCFSG are therefore missing from the copy,
shape and same-statement tables.
