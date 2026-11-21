# First issues: drafts

Ten candidates cut into pieces that one agent run, or one person, can pick up. Each is listed in
[`data/candidates/first_issues.tsv`](../data/candidates/first_issues.tsv) and
shown on the progress page. They are drafts: none has been opened as an issue
yet. When one is opened, put its number in the `issue` column.

All numbers come from the stage 1 tables in [`data/map/`](../data/map) and
[`data/bundles/`](../data/bundles). Groups of definitions were formed **by
name only**, so whether the copies really define the same thing is part of
each task. "Direct users" counts declarations whose elaborated term refers to
the definition.

Every issue below follows the same shape: what was found, the mathematical
question, what "done" means, and who can help. Labels: `name a concept`
(no Lean needed; optional help for the agents), `refactor` (a rewrite, done by
an agent run as in [CONTRIBUTING.md](../CONTRIBUTING.md#contribute-in-one-click)),
`good first issue`. "Done" for a rewrite always means: accepted by CI under
[the scoring rules](scoring.md).

---

## C01. One p-core O_p instead of six

Labels: `name a concept`, `refactor`

**Found.** Six definitions whose names say "p-core":
`CFSG.Open.pCoreOf` (55,573 direct users), `CFSG.pCore` (55,250),
`CFSG.FeitThompson.pCore` (314), `CFSG.ABGTheoremB.pCoreIn` (211),
`CFSG.FeitThompson.pCoreIn` (144),
`CFSG.Quasithin.G11.SzG11S.M12Vec.PCore` (22).

**Question.** Do they all define O_p(G), the largest normal p-subgroup? Some
end in `In`, which may mean O_p(H) for a subgroup H of G. Is that the same
notion applied to a subgroup, or something else?

**Done when.**
- Mathematicians: a comment that sorts the six into "the same as O_p",
  "relative version", or "different", with a reason.
- Lean: a pull request that keeps one definition (or Mathlib's, if one fits),
  proves the others equal to it, and replaces their uses. CI reports the
  change in size; the final theorem must stay as it is.

**Data.** `pcore` row of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C02. Merge the two definitions of p-rank

Labels: `refactor`, `good first issue`

**Found.** `CFSG.Open.pRank` (25,431 direct users) and `CFSG.pRank` (7,638).

**Question.** Both should be the p-rank: the largest rank of an elementary
abelian p-subgroup. Check that the two Lean definitions agree (maximum versus
supremum, the case of no p-subgroups, the type of the value).

**Done when.** A lemma `Open.pRank G p = pRank G p` (or a counterexample), and
a pull request that uses one definition everywhere. This is the smallest
merge in the list, a good first run for an agent.

**Data.** `prank` row of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C03. Elementary abelian p-groups: one predicate

Labels: `name a concept`, `refactor`

**Found.** `CFSG.Open.IsElemAbelian` (76,558 direct users),
`CFSG.IsElementaryAbelian` (15,418), `CFSG.FeitThompson.IsElementaryAbelian`
(196), and three local variants in `LocalAnalysis.UniquenessCase` and
`QuasithinUnique` (100 together).

**Question.** Are the two big ones the same predicate? Does either fix the
prime p, or say "for some p"? Are the local variants the same notion carrying
extra data?

**Done when.** A classification of the six as in C01, then one predicate in
use.

**Data.** `elemabelian` and `elementaryabelian` rows of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C04. Quasisimple groups: one definition

Labels: `name a concept`, `refactor`

**Found.** `CFSG.IsQuasisimple` (31,470 direct users), `CFSG.Open.IsQuasisimple`
(18,587), `CFSG.Assembly.IsQuasisimple` (3,763),
`CFSG.GorensteinWalter.IsQuasisimple` (726).

**Question.** Quasisimple means perfect with simple quotient by the centre.
Do all four say this, or do some use an equivalent form (for example,
G/Z(G) simple and G = [G, G])? If they differ, the equivalence proof is the
reusable lemma.

**Done when.** One definition in use, with the equivalences proved once.

**Data.** `quasisimple` row of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C05. Components and subnormal subgroups

Labels: `name a concept`

**Found.** Ten definitions named "component" (37,336 direct users together;
the largest are `CFSG.Open.IsComponentOf`, `CFSG.IsComponent`,
`CFSG.Assembly.IsComponentOf`) and four named "subnormal"
(`CFSG.Open.IsSubnormal`, `CFSG.Assembly.IsSubnormal`, and two more; 16,008).

**Question.** A component is a subnormal quasisimple subgroup. Which of the
ten mean this, and which use "component" in another sense (for example
`OrderReductions.InvolutionGraph.Component`, probably a connected component of
a graph)? This sorting is needed before anyone merges them.

**Done when.** A comment with a table: definition, meaning, same as the
standard notion or not.

**Data.** `component` and `subnormal` rows of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C06. One p′-core O_p′ instead of five

Labels: `name a concept`, `refactor`

**Found.** `CFSG.pPrimeCore` (29,148 direct users),
`CFSG.GH74.GLS.pPrimeCoreOf` (5,269), and three local copies (373 together).

**Question.** Same as C01 for the largest normal p′-subgroup. If the
definitions of O_p and O_p′ share a pattern (largest normal π-subgroup), one
definition of O_π may replace both families.

**Done when.** As in C01.

**Data.** `pprimecore` row of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C07. 29 ways to say "Sylow subgroup"

Labels: `name a concept`

**Found.** 29 predicates named like `IsSylowOf` / `IsSylowIn`
(23,898 direct users; the largest is `CFSG.ABGLocalTools.IsSylowOf`) and five
more for Sylow 2-subgroups (18,801; mostly `CFSG.QuasithinUnique.IsSylowTwoOf`).

**Question.** Mathlib already has Sylow subgroups. Why did the formalization
define its own, many times? Possible reasons: a subgroup-of-a-subgroup
version, a version stated by order, or a version for a fixed prime 2. Sorting
the 34 by which of these they are tells us how many concepts there really are.

**Done when.** A comment sorting the definitions into groups, with the
Mathlib notion each group corresponds to (if any).

**Data.** `sylow` and `sylowtwo` rows of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C08. The odd core O(G), defined 25 times

Labels: `name a concept`, `refactor`

**Found.** 25 definitions named "odd core", e.g. `CFSG.oddCore` (8,355
direct users), `CFSG.ClassicalInvolution.Asc77.oddCoreOf` (3,234),
`CFSG.ClassicalInvolution.Balance.oddCoreIn` (1,578).

**Question.** O(G) is the largest normal subgroup of odd order, that is
O_2′(G). If C06 produces one O_p′, is O(G) simply O_2′, so that this family
disappears into C06?

**Done when.** A comment confirming (or refuting) O(G) = O_2′(G) for each
definition; then a merge after C06.

**Data.** `oddcore` row of
[`parallel_definitions.tsv`](../data/map/parallel_definitions.tsv).

---

## C09. "K is a finite field of odd characteristic" as a hypothesis bundle

Labels: `name a concept`

**Found.** The hypotheses `1 ≤ f`, `p ≠ 2`, `p.Prime` appear together, in this
order, in 1,011 theorem statements across 16 folders, and
`Nat.card K = p ^ f`, `p ≠ 2`, `p.Prime` in 458 statements across 7 folders.

**Question.** These say "K is a finite field with q = p^f elements, p odd".
What is the right single object to replace them: a structure bundling
(K, p, f) with these facts, a typeclass, or just Mathlib's `CharP` and
`Fintype.card`? Which choice would let the most statements become shorter?

**Done when.** A short proposal (a few lines, no Lean needed) naming the
bundle and listing what it should contain.

**Data.** Rows of [`hyp_windows.tsv`](../data/bundles/hyp_windows.tsv)
containing `p ≠ 2 ; p.Prime`.

---

## C10. What is a "frame"? 136 copies of `exists_frame`

Labels: `name a concept`

**Found.** A lemma called `exists_frame` occurs in 136 namespaces (8,962 lines
in 16 folders), concentrated in `LocalAnalysis.StandardType`; for example
`CFSG.StandardType.F4Model.F4Rep.exists_frame`.

**Question.** What object is a "frame" in these settings, and is it the same
idea each time (for example, a basis adapted to a root system, or a set of
commuting root subgroups)? If yes, the 136 proofs may be one theorem applied
136 times.

**Done when.** A comment that reads three or four of the copies and says what
they have in common, or why they differ.

**Data.** `exists_frame` row of
[`name_families.tsv`](../data/map/name_families.tsv).
