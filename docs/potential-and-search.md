# Upper bounds and the two-layer search: data for the progress page

Two kinds of results feed the progress page besides the ledger. Both are
plain files; any tool may write them, and `tools/site/build_site.py` checks
them on every pull request.

## The upper-bound map: `data/potential/blocks.tsv`

For each part of the map, how many lines **at most** could be removed by a
given method. One row per (folder, part, method):

| Column | Meaning |
|---|---|
| `folder` | top-level folder as on the map, e.g. `FeitThompson` (a leading `CFSG.` is ignored) |
| `part` | a part of that folder as on the map (see `data/map/blocks.json`), or empty for the whole folder, which is then spread over its parts in proportion to their size |
| `method` | lowercase name of the method, e.g. `dead-code`, `copies`, `duplicate-statements` |
| `lines` | upper bound in lines inside declarations (the map's measure) |
| `tokens` | the same bound in Lean tokens, if known; may be empty |
| `evidence` | one short sentence: what was counted |

The page colours each part by the sum of its methods divided by the size of
the part, capped at 100 %. Different methods may count the same lines twice,
so the sum is still an upper bound, but a loose one; the tooltip shows each
method separately.

Present now:

- `dead-code` (`tools/site/potential_dead_code.py`): lines of declarations
  the final theorem does not depend on, 1,897,095 lines in all. Deleting
  them cannot change the final theorem. Most are in `Milestones` (statement
  copies kept for reference) and `Permutation`.

To add a method, write its rows with
`potential.replace_method(path, "<method>", rows)` from
[`tools/site/potential.py`](../tools/site/potential.py), which keeps the
rows of other methods.

## The two-layer search: `data/search/hypotheses.jsonl`

One JSON object per line, one line per hypothesis proposed by layer (a) of
[two-layer-search.md](two-layer-search.md). Fields:

```json
{"id": "h-0001", "date": "2026-11-22",
 "concept": "short name of the proposed concept",
 "meaning": "one or two sentences a mathematician can read",
 "status": "proposed | duplicate | selected | verifying | accepted | rejected",
 "proposer": {"provider": "anthropic", "model": "claude-sonnet-5-5", "viewpoint": "group theorist"},
 "regions": ["FeitThompson", "LocalAnalysis"],
 "potential": {"statements": 120, "tokens": 15000},
 "duplicate_of": "h-0007",
 "candidate": "id of the candidate in data/pilot/<target>/candidates.jsonl, once selected",
 "verdict": {"accepted": true, "tokens_saved": 4000, "reasons": []}}
```

Required: `id` (unique), `concept`, `status`. `potential.statements` is the
reach of option (3) in the memo: the number of statements whose elaborated
form would coincide if the concept were used. It ranks hypotheses and is
never what gets a contribution accepted. `verdict` is copied from the Lean
judge once the hypothesis has been tried.

The page shows a funnel (proposed → after removing duplicates → selected →
tried with Lean → accepted / rejected), how many hypotheses each model
proposed, and a table of every hypothesis that got past deduplication.
