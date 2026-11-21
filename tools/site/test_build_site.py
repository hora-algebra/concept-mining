#!/usr/bin/env python3
"""Tests for the ledger checks in build_site.py. Run: python3 tools/site/test_build_site.py"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import build_site as bs  # noqa: E402

HERE = os.path.dirname(__file__)
TODAY = dt.date(2026, 12, 31)
C_HEAD = "\t".join(bs.CONCEPT_COLS)
H_HEAD = "\t".join(bs.HISTORY_COLS)


def run(concepts: list[str], history: list[str]) -> tuple[dict, bs.Report]:
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "concepts.tsv"), "w") as f:
            f.write("\n".join([C_HEAD] + concepts) + "\n")
        with open(os.path.join(d, "history.tsv"), "w") as f:
            f.write("\n".join([H_HEAD] + history) + "\n")
        rep = bs.Report()
        return bs.build(d, rep, TODAY), rep


class LedgerChecks(unittest.TestCase):
    def test_example_ledger_is_clean(self):
        rep = bs.Report()
        data = bs.build(os.path.join(HERE, "example_ledger"), rep, TODAY)
        self.assertEqual(rep.errors, [])
        self.assertEqual(len(data["snapshots"]), 4)
        removed = sum(data["snapshots"][-1]["removed"].values())
        # 23,110 ledger lines out of 274,110, scaled to the map's 209,419 lines
        self.assertAlmostEqual(removed, 23110 * 209419 / 274110, delta=5)

    def test_empty_ledger(self):
        data, rep = run([], [])
        self.assertEqual(rep.errors, [])
        self.assertEqual(data["snapshots"], [])

    def test_missing_ledger_is_not_an_error(self):
        rep = bs.Report()
        bs.build(os.path.join(HERE, "no-such-dir"), rep, TODAY)
        self.assertEqual(rep.errors, [])

    def test_arithmetic(self):
        _, rep = run(["2026-11-22\tCFSG/FeitThompson\tX\tm\t100\t90\t11\t3\tabc1234"], [])
        self.assertTrue(any("lines_saved" in e for e in rep.errors))

    def test_unknown_target(self):
        _, rep = run(["2026-11-22\tCFSG/NoSuchFolder\tX\tm\t100\t90\t10\t3\tabc1234"], [])
        self.assertTrue(any("not a folder" in e for e in rep.errors))

    def test_future_date_and_bad_commit(self):
        _, rep = run(["2027-05-01\tCFSG/FeitThompson\tX\tm\t100\t90\t10\t3\tHEAD"], [])
        self.assertTrue(any("future" in e for e in rep.errors))
        self.assertTrue(any("git hash" in e for e in rep.errors))

    def test_history_mismatch_is_a_warning(self):
        _, rep = run(["2026-11-22\tCFSG/FeitThompson\tX\tm\t100\t90\t10\t3\tabc1234"],
                     ["2026-11-21\tCFSG/FeitThompson\t100\t5\tbase", "2026-11-22\tCFSG/FeitThompson\t80\t5\t"])
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("fell by 20" in w for w in rep.warnings))

    def test_target_spellings(self):
        folders = {"FeitThompson": {"parts": [{"part": "Local"}, {"part": "(4 other parts)"}]}}
        self.assertEqual(bs.resolve("CFSG/FeitThompson", folders), ("FeitThompson", None))
        self.assertEqual(bs.resolve("CFSG.FeitThompson.Local", folders), ("FeitThompson", "Local"))
        self.assertEqual(bs.resolve("CFSG/FeitThompson/Tiny/X.lean", folders), ("FeitThompson", "(4 other parts)"))


if __name__ == "__main__":
    unittest.main()
