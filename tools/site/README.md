# Progress page: data flow

The progress page lives in [`docs/site/`](../../docs/site). It is static (no
build step): `index.html`, `app.js` and `style.css` read one data file,
`docs/site/data/site.json`, which this folder's script writes. The file is
generated, not committed (it is in `.gitignore`): the Pages deployment
rebuilds it from the data, and so does a local preview.

```
data/map/blocks.json   ─┐  stage 1 map, one entry per part   (aggregate_blocks.py)
data/map/summary.json  ─┤
data/ledger/*.tsv      ─┼─> build_site.py ──> docs/site/data/site.json ──> page
data/site/*.tsv        ─┤  (check, then write)
data/candidates/*.tsv  ─┤
data/ledger/contributions.tsv ─┘ (points, via scoring.py)
```

## Commands

```bash
python3 tools/site/build_site.py              # check the ledger, write site.json (for a preview)
python3 tools/site/build_site.py --check      # check only, as CI does on pull requests
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
| `site.json` can be built from the current data | error |
| a concept has no `meaning` | warning |
| consecutive concepts in one target do not chain (`lines_after` ≠ next `lines_before`) | warning |
| the drop of `lines_total` in `history.tsv` differs from the sum of `lines_saved` over the same period | warning |
| a target has concepts but no history row | warning |

The pull request summary also lists the ledger rows the pull request adds
(`ledger_diff.py`).

Not checked here: that the line counts match the Lean sources. Counting them
needs a checkout of the upstream sources at the recorded commit, which CI
does not have.

## Upper bounds and search results

`data/potential/blocks.tsv` and `data/map/potential_rows.tsv` (upper bound per part and method) and
`data/search/hypotheses.jsonl` (two-layer search) are described in
[docs/potential-and-search.md](../../docs/potential-and-search.md);
`potential.py` reads and checks them, `potential_dead_code.py` writes the
`dead-code` layer from the proof-map graph. `--hypotheses FILE` previews
other search results (an example is in `example_search/`).

## Scoring and claims

- `scoring.py` holds the formula of [docs/scoring.md](../../docs/scoring.md).
  `scoring.py verdict verdict.json` turns the checker's verdict into an
  accept/reject decision with points and reasons (used by the workflow
  *Contribution gate*); `scoring.py board data/ledger/contributions.tsv`
  prints the scoreboard, which `build_site.py` also puts in `site.json`.
- `claim.py` takes, renews, releases and lists claims (`refs/claims/<key>`,
  compare-and-swap with `git push --force-with-lease`).
- When the page is deployed, the workflow adds live claims and open pull
  requests carrying the target marker to `site.json` (`--claims`,
  `--open-prs`), and the rows of contributions the gate accepted
  (`gate_ledger.py`, from the gate's comments); this data is not committed.

Workflows:

| Workflow | Trigger | Rights | Does |
|---|---|---|---|
| `site.yml` | pull request, push to main, every 30 min | read; Pages write for deploy | tests, ledger check, staleness check; deploy when `PAGES_ENABLED` is `true` |
| `contribution-gate.yml` | every pull request to main (`pull_request_target`), or by hand with a number | per job: the Lean build has no token and runs sandboxed; only the last job (which runs no PR content) can comment and merge | shape, apply, guard, size, build, inspect, AI review, comment, merge (see `docs/gate.md`) |
| `contribution-sweep.yml` | every 3 hours, and after each merge | write, never runs PR code | re-checks stale or unfinished pull requests, closes stalled ones |
| `contribute.yml` | manual, in a contributor's fork | the fork's secrets | runs `tools/contribute.py` (pick, rewrite, check, open PR) |

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
