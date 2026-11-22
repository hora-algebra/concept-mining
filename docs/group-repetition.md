# Arguments repeated group by group

Status: measured on AxiomMath/CFSG at `965a077`, from the source text, without
a build. All savings are estimates, not checked in Lean. Tool:
[`tools/group_families.py`](../tools/group_families.py); tables in
[`data/map/group_families/`](../data/map/group_families).

## Question

CFSG treats the 26 sporadic groups and the families of groups of Lie type one
at a time. If the same argument is written out again for every group, one
general theorem (taking the group's data as a parameter) plus one
instantiation per group would replace all the copies. Such a theorem would be
an abstraction across the case division of the classification, the kind of
concept this project is looking for. How much of CFSG is such repetition?

## Method

A declaration is *group-indexed* when its name or file path contains a group
token: a sporadic group (`J1`, `McL`, `Co2`, `Fi22`, ...), a Lie type (`E6`,
`G2`, `BCD`, `Ree`, ...) or `PSL`/`PSU`/`PSp`. Group-indexed declarations of
at least three lines make up 7.2 million lines, **21% of CFSG**.

Each declaration is reduced to a skeleton (local names renamed, numbers and
group tokens abstracted, global names kept) and compared by the Jaccard index
of 6-token shingles. Repetitions are grouped three ways:

- **by name**: names that agree once the group is abstracted
  (`CFSG.Sporadic.<G>.pt_inj`);
- **by skeleton**: declarations of different groups whose skeletons are at
  least 50% alike, whatever their names;
- **by file**: whole files whose paths agree up to the group
  (`PairFrameExc<G>Levi.lean`).

For a family, the members at least θ-similar to its medoid are replaced by one
general proof of 1.15 times the largest member plus two lines per member:
`removable = Σ lines − 1.15 · max lines − 2 · members`, at θ = 0.8 (near
copies) and θ = 0.5 (same argument, different details). Families made mostly
of data tables (at least 60% literal tokens) are counted separately: making
them shorter is a question of encoding, not of concepts.

## Result

| Grouping | Lines in families | Removable, θ = 0.8 | Removable, θ = 0.5 | of which arguments, θ = 0.5 |
|---|---|---|---|---|
| by name | 402,498 | 42,147 (0.12%) | 60,024 (0.17%) | 43,023 (0.12%) |
| by skeleton | 497,960 | 107,658 (0.31%) | 195,437 (0.56%) | 120,299 (0.34%) |
| by file | 956,790 | 17,120 (0.05%) | 35,217 (0.10%) | 13,119 (0.04%) |

Shares are of the 35,093,004 lines of CFSG. The three groupings overlap; the
skeleton grouping contains most of the name grouping.

**Group-by-group repetition of arguments is at most about 0.3% of CFSG.** A
fifth of the library is specific to one group, but almost all of it is that
group's own argument or data, not a copy of another group's. Where Axiom met a
truly uniform argument, it already wrote the general version: the
Schreier–Sims chain lemmas (`CFSG.Perm.ChainSpec.chain_facts`), simplicity
from a primitive action (`isSimpleGroup_of_primitive_coprime_orders`), and the
isomorphism of a presentation with its model
(`nonempty_mulEquiv_of_closure`) are each stated once and used for every
sporadic group.

What remains is a long tail. Of the 4,800 argument clusters found by
skeleton, 4,688 would each save fewer than 100 lines, and only 6 would save
500 or more (5,603 lines together). Files of different groups rarely look
alike as a whole (the file grouping finds 13,119 lines), because each group's
file mixes the shared steps with its own.

### Where it is

Arguments only, by skeleton, θ = 0.5, by the folder of the cluster's
representative.

| Folder | Lines in clusters | Removable | Share of CFSG |
|---|---|---|---|
| LocalAnalysis | 146,708 | 54,433 | 0.16% |
| Quasithin | 48,853 | 16,798 | 0.05% |
| HardMathSupport | 30,426 | 11,142 | 0.03% |
| ClassicalInvolution | 19,520 | 9,250 | 0.03% |
| RankThree | 22,862 | 8,344 | 0.02% |
| Sporadic | 18,972 | 5,810 | 0.02% |
| LieType | 13,261 | 3,861 | 0.01% |
| Milestones | 8,563 | 2,866 | 0.01% |
| GH74 | 6,812 | 2,350 | 0.01% |
| Monster | 1,210 | 269 | 0.001% |

`Sporadic` (522k lines) and `Monster` (330k lines), where one would expect
the per-group repetition, hold little of it: about 6,000 removable lines of
argument together. They hold more repeated data (26,000 lines by skeleton,
mostly word lists and generator tables). The per-group case analysis that
repeats most is in `LocalAnalysis` (19,000 lines in `StandardType` alone),
where the standard-component and classical-position arguments are run once
per family of groups of Lie type.

### Largest themes

| Theme | Groups | Lines in clusters | Removable θ = 0.8 / 0.5 | What repeats |
|---|---|---|---|---|
| `ClassicalInvolution.ModelFacts`, `PairFrameExc<G>*` and `StandardPairDichotomyExcA2<G>*` (68 files, 12,286 lines) | E6, E7, E8, F4 | 9,631 | 3,961 / 5,459 | the Levi-subgroup arguments for a pair of commuting involutions, written once per exceptional type: eight files per type with the same layout (Class, Data, Descent, Levi, Main, Rank1, Rational, Stab) |
| `StandardType.ClassicalPosition.BlockModel*` | PSU, PSp | 3,389 | 628 / 2,579 | block-model isometry lemmas for the unitary and symplectic cases |
| `Sporadic.<G>.Simple`, `Setup`, `Action`, `Class`, `Chain` | J1, J2, He, McL, Suz, ON, Fi22, Fi23, Fi24 (and J3, HS, Th, Ly, J4 in other layouts) | 2,423 | 859 / 1,187 | the glue between a group's certificate (orbit, Schreier–Sims chain, primitivity data) and the general chain lemmas: unpacking the certificate, the permutation representation, the levels of the stabilizer chain |
| `RankThree.PartOne.CTP.SporadicOrders`, `K133.KillSporadic` | 20 sporadic groups | 634 | 255 / 484 | divisibility facts about the order of each sporadic group |

### What this means for the search

- The case division of the classification is not where an
  order-of-magnitude reduction hides. Even taken generously, group-by-group
  repetition of arguments is about 0.3% of CFSG. It is nevertheless 100 to 300
  times what has been removed so far (346 lines).
- The best single theme is the exceptional-type Levi argument in
  `ClassicalInvolution.ModelFacts`: one statement over a root system with
  its model, instead of four copies, worth 4,000 to 5,500 lines (about
  0.013% of CFSG). It is a genuine concept (the argument does not depend on
  which exceptional type it is run for), but checking it needs a build of
  1.68 million lines of dependencies (about 2.8 hours on six cores).
- In `Sporadic` the shared steps are already general; what repeats is the
  glue between each group's certificate and those steps. A structure that
  packages a group's certificate (orbit, chain, primitivity data) with the
  facts derived from it would remove most of that glue, about 1,000 lines.
  Building these modules requires the certificate modules under
  `Certificates/`, which are not part of the sparse checkout used so far.

## Reproduce

```bash
python3 tools/group_families.py --near --files --root ~/Codes/upstream/cfsg --out data/map/group_families
```

About 4 minutes and 2 GB of memory for all of CFSG. `summary.json` has the
totals per grouping and folder; `families.tsv`, `near_clusters.tsv` and
`file_families.tsv` list the 1,000 largest families of each grouping with a
representative declaration and file.
