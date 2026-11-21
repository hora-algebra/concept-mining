# Strategy: where an order of magnitude could come from

Status: night of 2026-11-21/22, updated for the 1 % goal of
[plan-one-percent.md](plan-one-percent.md). Written by the strategy session that watches
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
   One proof can become a one-line application of the other (below). It needs
   a new import from ThirdParty/QiuzhenCFSG into CFSG/FeitThompson, which the
   checker's scope rule refuses today.
4. **The induction hypothesis does not free the large literature theorems.**
   The final theorem is proved by induction on the order with "every proper
   section is known" (`KProper`) in every branch. We checked whether the
   largest classification theorems from the literature are applied only to
   proper sections, where that hypothesis would replace them. They are not:
   each has at least one use on the simple group of the branch itself (below).
5. **For the 1 % goal, cleanup on the laptop is enough.** Declarations that
   neither the final theorem nor any `CFSG.Milestones` declaration needs come
   to 1,337,670 lines (3.8 %). Six parts whose builds fit the laptop hold
   365,994 of them (1.04 %); see [Cleanup toward 1 %](#cleanup-toward-1-).

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
|  |  | literature classification theorems applied to sections where `KProper` is available (GH74, Gorenstein–Walter, Bender–Suzuki, ...) | 0 | 0 % | **refuted**: every one of them is also applied to the simple group of its branch; see below |
|  |  | basic group-theory layer re-proved per region | 130,000 | 0.4 % | measured earlier; needs a full build |
| 2 | **One general theorem plus checks per case** | families of independent subtrees whose statements differ only in numbers or type names | 994,793 | 2.8 % | identifier multiset of the statement, so some families may join different statements; sampled families are real (e.g. `GGResIDisp.{A6,A7,B7,C7,D4..D7,E6}.ggResI_type_*`, `ggResQTwoFinite_{A7,B7,C7,D7,E6}`) |
| 3 | **The same skeleton per sporadic or Lie-type group** | declarations that name a group (21 % of the library), clustered by name and by proof skeleton | 60,000–195,000 | 0.2–0.6 % | measured by miner-b: about 120,000 lines of repeated argument at most (0.3 %), the rest data tables; 4,688 of 4,800 clusters are under 100 lines each. A first count by file names (790,123 lines) was mostly section numbers |

Rank 2 and 3 overlap each other and the proof-shape families of
[compression-map.md](compression-map.md) (866,990 lines). Together they are of
the order of 1 M lines, about 3 %, as an upper bound; where the repetition was
measured more closely (per group, rank 3) it shrank to a tenth of the first
count. The family bound leaves out two false
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

### The induction hypothesis: checked and refuted

Six expensive theorems from the literature were traced to the groups they are
finally applied to (about 40 use sites read):

| Theorem | Price | Applied to the simple group of the branch | Applied to a proper section |
|---|---|---|---|
| Gorenstein–Harada, sectional 2-rank ≤ 4 | 1,231,219 | yes: rank 3 (Sims 3.16), GF(2)-type width 2 (Aschbacher 1977), type E (Smith 1980) | one site already has `IsKGroupCat` (`HNRecog/GH73/Reduction.lean`), so the theorem is redundant there |
| GF(2^n)-type (Parrott, Timmesfeld) | 816,980 | all three users | none |
| Gorenstein–Walter | 198,807 | probably (`CFSG/Dihedral`) | five sites (involution centralizers, local subgroups) |
| Bender–Suzuki (`theorem_SE`) | 172,317 | yes: the disconnected-graph branch | three sites, with no K-group hypothesis in scope |
| Holt | 57,987 | all four users | none |
| Goldschmidt | 32,529 | yes: O'Nan's analysis | Goldschmidt 1975's own counterexample |

A theorem's price is freed only when **all** its uses go away, so none of these
subtrees can be dropped this way.

### One candidate survives: the classical involution theorem for q = 3

The same check on the 19 other shared theorems of price at least 50,000 lines
(Aschbacher's uniqueness case, weak closure, quasithin amalgams, the signalizer
functor theorem, ...) found them applied to the simple group of their branch,
or already built on facts about known groups, with one exception. The four
pieces of Aschbacher's classical involution theorem for q = 3
(`Q3Residuals₁₄.largeJ` 166,090, `Sec13.dLeafEnd_three` 72,191,
`TwinPerp.twinPerp233E_proved` 64,721, `twinPerpV3E_proved` 51,304; together
354,306 lines, 1.0 %) are applied only to groups smaller than G:

- in the component branch the theorem meets a component J, which is
  quasisimple, so J/O(J) is SL₂(q) with q ≥ 5 or 2A₇ and the case q = 3 does
  not arise;
- inside the classical involution theorem, `CIT3Below` is an induction
  hypothesis on smaller groups (`Q3JITyped9.lean`, `MilestoneAssemblyWired14.lean`);
- the other consumer, `QuaternionInspectionLie`, is stated under `KProper`.

So `KProper` could take over every use. What it would need is one fact about
the known groups that the library does not seem to have: a K-group generated
by a class of such subgroups is, modulo its odd core, of Lie type over F₃. Its
size is not known; it needs centralizers of involutions in the known groups.
Not traced: whether one solvable branch (`partOne_of_l2PrimeBalance`) applies
the theorem to G itself. The milestone for the quaternion component already
takes `KProper` as an argument and does not use it. This is the best
concept-level candidate found tonight; it needs the full build. The catalog of facts about the known groups
would still help: several intermediate statements (`GH74ModelsInput`,
`gorensteinWalterStatement`, `theorem_SE`, ...) are quantified over all groups
without a K-group hypothesis, and the uses on sections could be rerouted. That
removes uses, not lines.

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
| **Price-tag search** (new) | the expensive declarations and their statements; asks what else in the library, Mathlib or the induction hypothesis implies each one | an hour of analysis per class; one Lean bridge per hit | 1.44 % found (Feit–Thompson); one 1.0 % candidate (classical involutions, q = 3) | 25 shared theorems checked |
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

## Cleanup toward 1 %

"Deletable" below means: reached neither from the final theorem nor from any
declaration in `CFSG.Milestones` (which is kept), in the elaborated graph of
the proof map. 1,337,670 lines qualify; another 559,425 are needed only by
Milestones. The checker builds the target folder, so what a laptop can verify
is set by the import closure of the modules that change (lines of source that
must be built). One part with a closure of about 1.3 M lines takes 1.5–2 hours
on six cores.

| Part | Deletable | Closure to build | Where |
|---|---|---|---|
| Permutation.FiveTransitive | 165,930 | 0.20 M | laptop |
| Sporadic.Schreier | 79,232 | 1.29 M | laptop |
| ThirdParty.QiuzhenCFSG | 58,726 | 1.32 M | laptop |
| LieType.AlgebraicGroups | 26,150 | 0.23 M | laptop |
| FeitThompson (mostly Representations) | 21,616 | 0.27 M | laptop |
| ThirdParty.BrauerInduction | 14,370 | 0.02 M | laptop |
| **Laptop total** | **365,994 (1.04 %)** | | |
| Monster.B | 36,960 | 1.80 M | laptop, slow |
| Walter.Ree, CharacterTheory.Semidihedral / .Wreathed, ClassicalInvolution.Balance, LocalAnalysis.ComponentInitial | 15,000–22,000 each | 1.9–2.3 M | laptop, slow |
| LocalAnalysis.StandardType | 69,415 | 16.4 M | full build |
| LocalAnalysis.ComponentClassification | 50,296 | 7.1 M | full build |
| Certificates.Kernel | 40,677 | 8.9 M | full build |
| ClassicalInvolution.Q3, LocalAnalysis.AGLEmbeddingD2, RankThree.PartTwo, ... | 10,000–27,000 each | 5–17 M | full build |
| Certificates (top level) | 104,859 | not measured (outside our checkout) | unknown |

The route replacement of Feit–Thompson would add 504,232 lines to the laptop
column (closure 0.62 M lines). None of those lines is needed by Milestones: the
only declaration outside the subtree that refers into it is the proof being
replaced. It waits for a decision on the scope rule (rule 5 below).

Per-part tables: `tools/strategy/` computes prices; the deletable and build
figures come from the same graph plus the module imports of upstream
`965a077` (the proof map is of `3e39d10`, so every deletion is still checked by
building).

## Next moves (decided)

| Who | What | Why |
|---|---|---|
| concept-map | measure the Feit–Thompson route replacement and open a draft pull request marked as waiting for the scope rule; in the same build, delete the unreachable parts of ThirdParty/QiuzhenCFSG and ThirdParty/BrauerInduction | 504,232 lines pending a decision; 73,096 lines within today's rules |
| miner-a | the cleanup script; then Permutation.FiveTransitive, Sporadic.Schreier, LieType.AlgebraicGroups, FeitThompson | 293,000 lines, all on the laptop |
| miner-b | count cleanup and concepts separately on the progress page; make the checker and ledger accept cleanup | needed before any cleanup can be recorded |
| strategist | price-tag search on the shared theorems; "Resume here" below | |

What the laptop can verify is limited by import closures (lines of other
CFSG folders that a folder imports, at upstream `965a077`):

| Folder | Own | Imported from elsewhere |
|---|---|---|
| ThirdParty/QiuzhenCFSG | 1.34 M | 0 (closed) |
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

5. **Imports across folders.** The checker accepts new imports only from
   Mathlib or the target folder. The Feit–Thompson route replacement must
   import CFSG/FeitThompson from ThirdParty/QiuzhenCFSG. Proposal: also accept
   an import of a module of another folder when (a) that folder does not import
   the target (no cycle), and (b) the checker builds that module too. Both are
   mechanical checks, and the protected statements still guard the rest of the
   library.

## Tool note

`tools/skeletons.py` does not recognise `public theorem` (its declaration
pattern lists `private`, `protected`, ... but not `public`). About 11,000
declarations of ThirdParty/QiuzhenCFSG are therefore missing from the copy,
shape and same-statement tables.
