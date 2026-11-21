# Progress page: data flow

The progress page lives in [`docs/site/`](../../docs/site). It is static (no
build step): `index.html`, `app.js` and `style.css` read one data file,
`docs/site/data/site.json`, which this folder's script writes.

```
data/map/blocks.json   ─┐  stage 1 map, one entry per part   (aggregate_blocks.py)
data/map/summary.json  ─┤
data/ledger/*.tsv      ─┼─> build_site.py ──> docs/site/data/site.json ──> page
data/site/*.tsv        ─┤  (check, then write)
data/candidates/*.tsv  ─┘
```

## Commands

```bash
python3 tools/site/build_site.py              # check the ledger, rewrite site.json
python3 tools/site/build_site.py --check      # check only; fail if site.json is stale
python3 tools/site/test_build_site.py         # tests of the checks
python3 -m http.server -d docs/site 8000      # then open http://localhost:8000
```

To preview the page with made-up numbers (it then shows an "Example data"
banner), write the example ledger somewhere outside the repository and serve
a copy of the page with it:

```bash
python3 tools/site/build_site.py --ledger tools/site/example_ledger --example --out /tmp/site/data/site.json
cp docs/site/*.html docs/site/*.js docs/site/*.css /tmp/site/ && python3 -m http.server -d /tmp/site 8000
```

`aggregate_blocks.py` rebuilds `data/map/blocks.json` from the exact
declaration graph (downloaded by `tools/fetch_proofmap.py`); it only needs to
run when the upstream version changes.

## What the checks catch

Run on every pull request that touches `data/`, `tools/site/` or `docs/site/`
(workflow `.github/workflows/site.yml`). No Lean build is involved.

| Check | Level |
|---|---|
| headers of `concepts.tsv` and `history.tsv` are exactly as expected | error |
| dates are real `YYYY-MM-DD` dates, not in the future | error |
| line counts are non-negative integers | error |
| `lines_saved = lines_before - lines_after` | error |
| `commit` is a git hash | error |
| `target` is a folder of the map (`CFSG/FeitThompson`, `CFSG.FeitThompson.Local`, ...) | error |
| `site.json` is what the script produces from the current data | error |
| a concept has no `meaning` | warning |
| consecutive concepts in one target do not chain (`lines_after` ≠ next `lines_before`) | warning |
| the drop of `lines_total` in `history.tsv` differs from the sum of `lines_saved` over the same period | warning |
| a target has concepts but no history row | warning |

The pull request summary also lists the ledger rows the pull request adds
(`ledger_diff.py`).

Not checked here: that the line counts match the Lean sources. Counting them
needs a checkout of the upstream sources at the recorded commit, which CI
does not have.

## How the page uses the ledger

- **Shrinking over time** plots `lines_total` from `history.tsv` per target.
  A target with concepts but no history is plotted from `lines_before` and
  `lines_after`. Each concept is numbered at its date.
- **Concepts found** sums `lines_saved` per concept name and shows the first
  non-empty `meaning`.
- **The map** converts each concept's `lines_saved` into the map's own measure
  (lines inside declarations) with one factor per folder: map lines of the
  folder divided by the folder's size in the ledger at its first history row
  (or, without one, the largest `lines_before` among its concepts). A concept
  on a whole folder shrinks its parts in proportion; a concept on one part
  shrinks that part. The result is approximate and shown as hatched area.
- **Who is working on what** is `data/site/work.tsv`
  (`status` is `open`, `claimed`, `in-progress` or `done`).
- **Candidates** is `data/candidates/first_issues.tsv`; once an issue is
  opened, put its number in the `issue` column and the card links to it.
