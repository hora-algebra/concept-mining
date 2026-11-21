"""Tests of the gate's decision logic (no network, no Lean).

    python3 -m unittest discover -s tools/gate -p 'test_gate.py'
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import act  # noqa: E402
import common  # noqa: E402
import decide  # noqa: E402
import shape  # noqa: E402

PR = {"state": "open", "base": {"ref": "main"}, "draft": False}
SUP = ["FeitThompson"]


def f(name, status="added", prev=None):
    d = {"filename": name, "status": status}
    if prev:
        d["previous_filename"] = prev
    return d


class Shape(unittest.TestCase):
    def kind(self, files, pr=PR):
        return shape.classify(pr, files, "main", SUP)

    def test_one_new_patch_is_a_contribution(self):
        s = self.kind([f("lean/patches/FeitThompson/0005-copies-foo.patch")])
        self.assertEqual((s["kind"], s["target"], s["candidate"]), ("contribution", "FeitThompson", "copies-foo"))

    def test_draft(self):
        self.assertEqual(self.kind([f("lean/patches/FeitThompson/0005-x.patch")], {**PR, "draft": True})["kind"],
                         "draft")

    def test_extra_files_are_refused(self):
        for files in ([f("lean/patches/FeitThompson/0005-x.patch"), f("data/ledger/contributions.tsv", "modified")],
                      [f("lean/patches/FeitThompson/0005-x.patch"), f("lean/patches/FeitThompson/0006-y.patch")],
                      [f("lean/patches/FeitThompson/0001-copies-hallCoreIn.patch", "removed")],
                      [f("lean/patches/FeitThompson/0001-a.patch", "modified")],
                      [f("data/claims/x.json", "renamed", prev="lean/patches/FeitThompson/0001-a.patch")],
                      [f("lean/patches/FeitThompson/../../tools/x.patch")],
                      [f("lean/patches/Unknown/0001-a.patch")]):
            s = self.kind(files)
            self.assertEqual(s["kind"], "malformed", files)
            self.assertTrue(all(r.startswith("paths_allowed") for r in s["reasons"]), s)

    def test_rename_out_of_patches_is_noticed(self):
        s = self.kind([f("docs/x.md", "renamed", prev="lean/patches/FeitThompson/0001-a.patch")])
        self.assertEqual(s["kind"], "malformed")

    def test_other_and_closed(self):
        self.assertEqual(self.kind([f("docs/x.md", "modified")])["kind"], "other")
        self.assertEqual(self.kind([f("lean/patches/FeitThompson/0005-x.patch")], {**PR, "state": "closed"})["kind"],
                         "closed")
        self.assertEqual(self.kind([f("lean/patches/FeitThompson/0005-x.patch")],
                                   {**PR, "base": {"ref": "stage1-map"}})["kind"], "closed")

    def test_patch_path_pattern(self):
        ok = ["lean/patches/FeitThompson/0005-a.patch", "lean/patches/ThirdParty/Qiuzhen/0001-b_c.patch"]
        bad = ["lean/patches/FeitThompson/.patch", "lean/patches/FeitThompson/-a.patch",
               "lean/patches/Feit Thompson/0001.patch", "lean/patches/FeitThompson/0001.patch.txt",
               "lean/patches//0001.patch", "lean/patches/a/../b/0001.patch"]
        for p in ok:
            self.assertTrue(common.PATCH_PATH.match(p), p)
        for p in bad:
            self.assertFalse(common.PATCH_PATH.match(p), p)


CHECKS_OK = {c: True for c in decide.MECHANICAL}
SHAPE = {"kind": "contribution", "pr": 7, "head_sha": "a" * 40, "author": "alice", "target": "FeitThompson",
         "candidate": "x", "patch_name": "0005-x.patch", "fingerprint": "fp", "marker": {"agent": "codex/gpt"}}
FACTS = {"fingerprint": "fp", "checks": CHECKS_OK, "reasons": [], "setup_error": None, "tokens_before": 10000,
         "tokens_after": 9000, "cleanup_tokens": 0, "lines_saved": 40, "concepts": [{"name": "K", "uses": 3}],
         "upstream_commit": "u"}
REVIEW_OK = {"approved": True, "deferred": False, "results": {"concept": {"verdict": "approve"}}}
MEASURE = {"checks": {c: True for c in ("paths_allowed", "applies", "no_metaprogramming", "no_shortcuts",
                                        "saves_tokens")}, "tokens_before": 10000, "tokens_after": 9000,
           "setup_error": None, "reasons": []}


class Decide(unittest.TestCase):
    def test_accept(self):
        d = decide.decide(SHAPE, FACTS, REVIEW_OK, MEASURE)
        self.assertEqual(d["state"], "accepted")
        self.assertEqual(d["points"], 11.5)  # 10 shrink + min(1.5, 10)

    def test_review_blocks(self):
        rv = {"approved": False, "results": {"readability": {"verdict": "block", "summary": "golfed"},
                                             "advisory": {"verdict": "block", "summary": "ignored"}}}
        d = decide.decide(SHAPE, FACTS, rv, MEASURE)
        self.assertEqual(d["state"], "rejected")
        self.assertTrue(any("readability" in r for r in d["reasons"]))
        self.assertFalse(any("advisory" in r for r in d["reasons"]))

    def test_budget_waits(self):
        d = decide.decide(SHAPE, FACTS, {"approved": False, "deferred": True, "results": {}}, MEASURE)
        self.assertEqual(d["state"], "waiting")

    def test_mechanical_failure_rejects_without_review(self):
        facts = {**FACTS, "checks": {**CHECKS_OK, "protected_unchanged": False},
                 "reasons": ["protected_unchanged: x"]}
        d = decide.decide(SHAPE, facts, None)
        self.assertEqual((d["state"], d["reasons"]), ("rejected", ["protected_unchanged: x"]))

    def test_missing_or_stale_facts_are_errors_not_rejections(self):
        self.assertEqual(decide.decide(SHAPE, None, None)["state"], "error")
        self.assertEqual(decide.decide(SHAPE, {**FACTS, "fingerprint": "old"}, REVIEW_OK)["state"], "error")
        self.assertEqual(decide.decide(SHAPE, {**FACTS, "setup_error": "x"}, REVIEW_OK)["state"], "error")
        self.assertEqual(decide.decide(SHAPE, FACTS, None, MEASURE)["state"], "error")
        self.assertEqual(decide.decide(SHAPE, FACTS, REVIEW_OK, None)["state"], "error")

    def test_build_report_must_match_independent_measurement(self):
        forged = {**MEASURE, "tokens_after": 9990}
        d = decide.decide(SHAPE, FACTS, REVIEW_OK, forged)
        self.assertEqual((d["state"], d["checks"]["build"]), ("rejected", False))
        bad = {**MEASURE, "checks": {**MEASURE["checks"], "no_metaprogramming": False}}
        self.assertEqual(decide.decide(SHAPE, FACTS, REVIEW_OK, bad)["state"], "rejected")

    def test_unknown_check_value_is_not_a_pass(self):
        facts = {**FACTS, "checks": {**CHECKS_OK, "build": None}}
        self.assertEqual(decide.decide(SHAPE, facts, REVIEW_OK, MEASURE)["state"], "rejected")

    def test_shapes(self):
        self.assertEqual(decide.decide({**SHAPE, "kind": "other"}, None, None)["state"], "not_contribution")
        self.assertEqual(decide.decide({**SHAPE, "kind": "draft"}, None, None)["state"], "waiting")
        m = decide.decide({**SHAPE, "kind": "malformed", "reasons": ["paths_allowed: x"]}, None, None)
        self.assertEqual((m["state"], m["checks"]["paths_allowed"]), ("rejected", False))


class Records(unittest.TestCase):
    def test_meta_roundtrip_and_no_comment_break(self):
        meta = {"agent": "x-->y", "concepts": [{"name": "a--b", "uses": 1}], "points": 1.5}
        text = "hello\n" + common.write_meta(meta)
        self.assertEqual(text.count("-->"), 1)
        self.assertEqual(common.read_meta(text), meta)

    def test_marker_is_sanitised(self):
        body = 'x <!--concept-mining-target:v1 {"candidate":"c<b>","agent":"@bob x","target":"CFSG/F"}--> y'
        self.assertEqual(common.parse_marker(body), {"candidate": "cb", "agent": "bobx", "target": "CFSG/F"})
        self.assertEqual(common.parse_marker("<!--concept-mining-target:v1 [1]-->"), {})

    def test_safe_text(self):
        s = act.safe("@octocat <!--concept-mining-gate--> <b>")
        self.assertNotIn("<!--", s)
        self.assertNotIn("@octocat", s)

    def test_fingerprint_moves_with_patches_and_rules(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "lean/patches/T"))
            os.makedirs(os.path.join(d, "data/protected"))
            os.makedirs(os.path.join(d, "tools/gate"))
            open(os.path.join(d, "lean/UPSTREAM"), "w").write("repo=x\ncommit=y\n")
            open(os.path.join(d, "data/protected/T.json"), "w").write("{}")
            open(os.path.join(d, "tools/gate/guard.py"), "w").write("# v1")
            a = common.fingerprint("T", d)
            open(os.path.join(d, "lean/patches/T/0001-a.patch"), "w").write("p")
            b = common.fingerprint("T", d)
            open(os.path.join(d, "tools/gate/guard.py"), "w").write("# v2")
            c = common.fingerprint("T", d)
            open(os.path.join(d, "tools/gate/test_guard.py"), "w").write("# tests do not count")
            self.assertEqual(len({a, b, c}), 3)
            self.assertEqual(c, common.fingerprint("T", d))
            self.assertEqual(common.supported_targets(d), ["T"])

    def test_comment_renders(self):
        d = decide.decide(SHAPE, FACTS, REVIEW_OK, MEASURE)
        text = act.body(d, "", "", True, {"x": 1}, "o/r")
        self.assertIn("Accepted: 11.5 points", text)
        self.assertIn("Merged automatically", text)
        self.assertEqual(common.read_meta(text), {"x": 1})


if __name__ == "__main__":
    unittest.main()
