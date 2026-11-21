## What this changes

<!-- One or two sentences. Link the issue: "Closes #..." -->

## Kind

- [ ] Refactoring result (ledger rows added)
- [ ] Concept names or meanings
- [ ] Map, page, tools or documentation

## For refactoring results

- Upstream branch or patch:
- Target (as on the map):
- [ ] The statement of `CFSG.classification_finite_simple_groups` is unchanged
- [ ] `#print axioms` on it gives the same axioms as before
- [ ] The touched part builds (say how: command, machine, time)
- [ ] No `sorry`, no new `axiom`
- [ ] Rows added to `data/ledger/concepts.tsv` and `data/ledger/history.tsv`, each concept with a one or two sentence `meaning`
- [ ] `python3 tools/site/build_site.py` run and `docs/site/data/site.json` committed

CI checks the ledger arithmetic and regenerates the page data; it does not build Lean.
