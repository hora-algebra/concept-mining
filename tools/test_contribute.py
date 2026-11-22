#!/usr/bin/env python3
"""Tests of tools/contribute.py that need no network and no Lean.

    python3 tools/test_contribute.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contribute as C  # noqa: E402

SITE_MARKER = C.MARKER_RE  # the progress page parses the same marker


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sh(*cmd, cwd=None, env=None, input=None):
    return subprocess.run(cmd, cwd=cwd, env=env, input=input, check=True, capture_output=True, text=True).stdout.strip()


def judge_works() -> bool:
    """tools/verify.py is maintained with the gate; these tests need it to start."""
    return subprocess.run([sys.executable, os.path.join(HERE, "verify.py"), "--help"], capture_output=True).returncode == 0


GIT_ID = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
          "GIT_COMMITTER_EMAIL": "t@t"}


class PickTests(unittest.TestCase):
    cands = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}, {"id": "c", "title": "C"}]

    def pr(self, n, body="", title="", login="someone"):
        return {"number": n, "body": body, "title": title, "url": f"https://x/pull/{n}", "author": {"login": login}}

    def test_marker_and_title_claim(self):
        prs = [self.pr(5, body="text " + C.marker("a", "FT", "claude")),
               self.pr(6, title="[FT/b] something"),
               self.pr(7, body=C.marker("c", "Other", "claude")),  # another target
               self.pr(8, body='<!--concept-mining-target:v1 {"candidate":"","target":"","agent":""}-->'),  # template
               self.pr(9, body="<!--concept-mining-target:v1 {not json}-->", title="Unrelated")]
        self.assertEqual(set(C.taken(prs, "FT")), {"a", "b"})

    def test_oldest_pull_request_wins_and_exclude(self):
        prs = [self.pr(12, title="[FT/a] x"), self.pr(10, title="[FT/a] y")]
        self.assertEqual(C.taken(prs, "FT")["a"]["number"], 10)
        self.assertEqual(C.taken(prs, "FT", exclude=10)["a"]["number"], 12)

    def test_merged_and_numbers(self):
        names = ["0001-a.patch", "0002-bundle-dd790378.patch", "0010-x.y.patch", "README.md", "junk.patch"]
        self.assertEqual(C.merged(names), {"a", "bundle-dd790378", "x.y"})
        self.assertEqual(C.next_number(names), 11)
        self.assertEqual(C.next_number([]), 1)

    def test_pick_skips_merged_and_open(self):
        busy = C.taken([self.pr(3, title="[FT/b] x")], "FT")
        self.assertEqual(C.pick(self.cands, {"a"}, busy)["id"], "c")
        with self.assertRaises(C.Stop) as e:
            C.pick(self.cands, {"a", "c"}, busy)
        self.assertEqual(e.exception.code, 3)

    def test_pick_prefers_untried(self):
        self.assertEqual(C.pick(self.cands, set(), {}, tries={"a": 2, "b": 1})["id"], "c")
        self.assertEqual(C.pick(self.cands, set(), {}, tries={"a": 1, "b": 1, "c": 1})["id"], "a")
        self.assertEqual(C.pick(self.cands, set(), {}, "a", tries={"a": 5})["id"], "a")  # asked for explicitly

    def test_local_failures_count_as_tries(self):
        with tempfile.TemporaryDirectory() as d:
            for cid, verdict in (("a", "reject"), ("b", "accept"), ("c", "error")):
                os.makedirs(os.path.join(d, "out", "contribute", "FT", cid))
                with open(os.path.join(d, "out", "contribute", "FT", cid, "verdict.json"), "w") as f:
                    json.dump({"verdict": verdict}, f)
            saved, C.REPO = C.REPO, d
            try:
                job = C.Contribution(C.parse_args(["--root", d, "--target", "FT", "--pr", "none"]))
                self.assertEqual(job.tries(), {"a": 1, "b": 1})
            finally:
                C.REPO = saved

    def test_pick_wanted(self):
        busy = C.taken([self.pr(3, title="[FT/b] x", login="Me")], "FT")
        self.assertEqual(C.pick(self.cands, set(), busy, "c")["id"], "c")
        for wanted, done, login, code, text in (("a", {"a"}, None, 2, "already done"),
                                                 ("b", set(), "other", 3, "being worked on"),
                                                 ("b", set(), "me", 2, "--fix 3"),
                                                 ("zz", set(), None, 2, "no candidate")):
            with self.assertRaises(C.Stop) as e:
                C.pick(self.cands, done, busy, wanted, login)
            self.assertEqual(e.exception.code, code)
            self.assertIn(text, str(e.exception))


class TextTests(unittest.TestCase):
    c = {"id": "copies-x", "title": "Merge 3 copies of x"}

    def test_bodies_carry_a_parseable_marker(self):
        v = {"tokens_saved": 120, "code_lines_saved": 9}
        for body in (C.claim_body(self.c, "FT", "claude/m"),
                     C.final_body(self.c, "FT", "claude/m", {"name": "x", "meaning": "m " * 600}, v)):
            meta = json.loads(SITE_MARKER.search(body).group(1))
            self.assertEqual(meta, {"candidate": "copies-x", "target": "CFSG/FT", "agent": "claude/m"})
            self.assertEqual(C.pr_candidate({"body": body}, "FT"), "copies-x")
            self.assertLess(len(body), 1200)

    def test_compare_link(self):
        body = C.final_body(self.c, "FT", "codex", {"name": "x", "meaning": "A & B?"}, {"tokens_saved": 1})
        title = C.title_of(self.c, "FT")
        for fork, head in (("alice/concept-mining", "alice:contrib/FT/copies-x"),
                           ("alice/cm2", "alice:cm2:contrib/FT/copies-x"),
                           (C.UPSTREAM, "contrib/FT/copies-x")):
            u = urllib.parse.urlsplit(C.compare_link(fork, "contrib/FT/copies-x", title, body))
            self.assertEqual(u.netloc, "github.com")
            self.assertEqual(urllib.parse.unquote(u.path), f"/{C.UPSTREAM}/compare/main...{head}")
            q = urllib.parse.parse_qs(u.query)
            self.assertEqual(q["title"], [title])
            self.assertEqual(q["body"], [body])
            self.assertEqual(q["quick_pull"], ["1"])

    def test_secrets_and_paths(self):
        env = {"PR_TOKEN": "a-long-secret-value-123", "HOME": "/home/alice-and-more"}
        self.assertTrue(C.contains_secret(b"x ghp_" + b"a" * 36, {}))
        self.assertTrue(C.contains_secret(b"-- sk-ant-api03-" + b"b" * 40, {}))
        self.assertTrue(C.contains_secret(b"/- a-long-secret-value-123 -/", env))
        self.assertFalse(C.contains_secret(b"theorem mask_le : True := trivial /home/alice-and-more", env))
        p = b"diff --git a/CFSG/T/A.lean b/CFSG/T/A.lean\n--- a/x\n+++ b/x\ndiff --git a/CFSG/T/B.lean b/CFSG/T/C.lean\n"
        self.assertEqual(C.patch_paths(p), {"CFSG/T/A.lean", "CFSG/T/B.lean", "CFSG/T/C.lean"})

    def test_explain(self):
        self.assertIn("network", C.explain("fatal: unable to access 'x': Could not resolve host: github.com", "push"))
        self.assertIn("gh auth login", C.explain("HTTP 401: Bad credentials", "list"))
        self.assertIn("no permission", C.explain("remote: Permission to a/b.git denied to c.\nfatal: unable to access "
                                                 "'x': The requested URL returned error: 403", "push"))
        self.assertEqual(C.explain("something odd\n", "push"), "Could not push: something odd")


class EnvTests(unittest.TestCase):
    env = {"PATH": "/bin", "HOME": "/h", "LANG": "C", "LC_ALL": "C", "ELAN_HOME": "/e", "LEAN_PATH": "/l",
           "XDG_CONFIG_HOME": "/x", "HTTPS_PROXY": "p",
           "GH_TOKEN": "s", "GITHUB_TOKEN": "s", "PR_TOKEN": "s", "CONTRIBUTE_PUSH_TOKEN": "s", "GH_ENTERPRISE_TOKEN": "s",
           "ANTHROPIC_API_KEY": "a", "CLAUDE_CODE_OAUTH_TOKEN": "a", "OPENAI_API_KEY": "o", "CODEX_HOME": "/c",
           "AWS_SECRET_ACCESS_KEY": "s", "ACTIONS_RUNTIME_TOKEN": "s", "LEAN_SECRET_TOKEN": "s", "MY_VAR": "v",
           "GITHUB_REPOSITORY": "a/b"}
    base = {"PATH", "HOME", "LANG", "LC_ALL", "ELAN_HOME", "LEAN_PATH", "XDG_CONFIG_HOME", "HTTPS_PROXY"}

    def test_claude_gets_only_its_key(self):
        self.assertEqual(set(C.agent_env("claude", self.env)), self.base | {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"})

    def test_codex_gets_only_its_key(self):
        self.assertEqual(set(C.agent_env("codex", self.env)), self.base | {"OPENAI_API_KEY", "CODEX_HOME"})

    def test_other_commands_get_no_key_unless_asked(self):
        self.assertEqual(set(C.agent_env("cmd:x", self.env)), self.base)
        self.assertEqual(set(C.agent_env("cmd:x", self.env, ["MY_VAR"])), self.base | {"MY_VAR"})
        self.assertEqual(set(C.agent_env("", self.env)), self.base)  # Lean and the judge


class ArgsTests(unittest.TestCase):
    def test_target_needed_unless_fixing(self):
        with self.assertRaises(SystemExit):
            C.parse_args(["--root", "r"])
        self.assertEqual(C.parse_args(["--root", "r", "--fix", "7"]).fix, 7)
        a = C.parse_args(["--root", "r", "--target", "FT", "--no-pr", "--provider", "openai"])
        self.assertEqual(C.Contribution(a).mode, "none")
        self.assertEqual(C.Contribution(a).agent, "codex")


class GitTests(unittest.TestCase):
    """Snapshot, quick check, one-file branch commit and the patch round trip, on toy repositories."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root, self.repo, self.out = (os.path.join(t, n) for n in ("root", "repo", "out"))
        os.makedirs(os.path.join(self.root, "CFSG", "Toy"))
        os.makedirs(os.path.join(self.repo, "lean", "patches", "Toy"))
        os.makedirs(self.out)
        lean = "set_option autoImplicit false\n" + "".join(
            f"theorem t{i} (a b : Nat) : a + b = b + a := by\n  exact Nat.add_comm a b\r\n" for i in range(30))
        with open(os.path.join(self.root, "CFSG", "Toy", "A.lean"), "w", newline="") as f:
            f.write(lean)
        for d in (self.root, self.repo):
            sh("git", "init", "-q", "-b", "main", cwd=d)
        sh("git", "add", "-A", cwd=self.root)
        sh("git", "commit", "-qm", "base", cwd=self.root, env=GIT_ID)
        with open(os.path.join(self.repo, "lean", "patches", "Toy", "0001-old.patch"), "w") as f:
            f.write("x\n")
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "main", cwd=self.repo, env=GIT_ID)
        sh("git", "update-ref", C.UPSTREAM_MAIN, "HEAD", cwd=self.repo)
        self.saved_repo, C.REPO = C.REPO, self.repo
        a = C.parse_args(["--root", self.root, "--target", "Toy", "--agent", "cmd:true", "--pr", "none"])
        self.job = C.Contribution(a)
        self.job.base = sh("git", "rev-parse", "HEAD", cwd=self.root)
        self.job.out = self.out
        self.job.login = "alice"

    def tearDown(self):
        C.REPO = self.saved_repo
        self.tmp.cleanup()

    def edit(self):
        p = os.path.join(self.root, "CFSG", "Toy", "A.lean")
        with open(p, newline="") as f:
            lines = f.read().splitlines(keepends=True)
        with open(p, "w", newline="") as f:
            f.write("".join(lines[:21]) + "theorem shared : True := trivial\n")
        with open(os.path.join(self.root, "CFSG", "Toy", "New.lean"), "w") as f:
            f.write("import CFSG.Toy.A\n")

    def test_snapshot_and_branch_commit(self):
        self.assertIsNone(self.job.snapshot("nothing yet"))
        self.edit()
        status_before = sh("git", "status", "--porcelain", cwd=self.root)
        s = self.job.snapshot("Concept shared")
        self.assertEqual(sh("git", "status", "--porcelain", cwd=self.root), status_before)  # the agent's index is untouched
        self.assertEqual(sh("git", "diff", "--name-only", self.job.base, s, cwd=self.root).split(),
                         ["CFSG/Toy/A.lean", "CFSG/Toy/New.lean"])

        self.assertEqual(self.job.patch_names(), ["0001-old.patch"])
        name = f"lean/patches/Toy/{C.next_number(self.job.patch_names()):04d}-cand.patch"
        self.assertEqual(name, "lean/patches/Toy/0002-cand.patch")
        self.job.push_repo = C.UPSTREAM
        data = self.job.patch_of(s)
        self.assertIn(b"\r\n", data)
        commit = self.job.branch_commit(name, data, "Concept shared")
        main = sh("git", "rev-parse", C.UPSTREAM_MAIN, cwd=self.repo)
        self.assertEqual(sh("git", "rev-parse", f"{commit}^", cwd=self.repo), main)
        self.assertEqual(sh("git", "diff", "--name-status", main, commit, cwd=self.repo), f"A\t{name}")
        self.assertEqual(sh("git", "status", "--porcelain", cwd=self.repo), "")  # the checkout is untouched

        # the patch in the branch reproduces the work exactly (as tools/apply_patches.sh applies it)
        fresh = os.path.join(self.tmp.name, "fresh")
        sh("git", "clone", "-q", self.root, fresh)
        sh("git", "checkout", "-q", self.job.base, cwd=fresh)
        p = os.path.join(self.tmp.name, "p.patch")
        with open(p, "wb") as f:
            f.write(subprocess.run(["git", "show", f"{commit}:{name}"], cwd=self.repo, capture_output=True).stdout)
        sh("git", "am", "-q", "--keep-cr", p, cwd=fresh, env=GIT_ID)
        self.assertEqual(sh("git", "rev-parse", "HEAD^{tree}", cwd=fresh), sh("git", "rev-parse", f"{s}^{{tree}}", cwd=self.root))

    @unittest.skipUnless(judge_works(), "tools/verify.py does not start (it is being changed)")
    def test_quick_check_accepts_a_real_change(self):
        self.edit()
        v = self.job.verify(os.path.join(self.out, "q.json"), head=self.job.snapshot("Concept shared"))
        self.assertEqual(v["verdict"], "unchecked", v)
        self.assertGreater(v["tokens_saved"], 50)

    @unittest.skipUnless(judge_works(), "tools/verify.py does not start (it is being changed)")
    def test_quick_check_rejects_forbidden_changes(self):
        p = os.path.join(self.root, "CFSG", "Toy", "A.lean")
        with open(p, "a") as f:
            f.write("theorem bad : False := sorry\n")
        v = self.job.verify(os.path.join(self.out, "q.json"), head=self.job.snapshot("bad"))
        self.assertEqual((v["verdict"], v["phase"]), ("reject", "guards"))


AGENT = r"""
import json, os, subprocess, sys, time
prompt = sys.stdin.read()
out = sys.argv[1]
child = subprocess.Popen(["sleep", "60"])
json.dump({"env": sorted(os.environ), "child": child.pid, "prompt": prompt[:20]}, open(out, "w"))
time.sleep(float(sys.argv[2]))
"""


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.script = os.path.join(self.tmp.name, "agent.py")
        with open(self.script, "w") as f:
            f.write(AGENT)
        self.report = os.path.join(self.tmp.name, "report.json")

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, sleep, minutes, check_minutes=0.01):
        a = C.parse_args(["--root", self.tmp.name, "--target", "Toy", "--agent",
                          f"cmd:{sys.executable} {self.script} {self.report} {sleep}", "--minutes", str(minutes),
                          "--check-minutes", str(check_minutes)])
        j = C.Contribution(a)
        j.env.update(GH_TOKEN="secret", PR_TOKEN="secret", ANTHROPIC_API_KEY="secret", CONTRIBUTE_PUSH_TOKEN="secret")
        return j

    def alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def wait_dead(self, pid):
        for _ in range(50):
            if not self.alive(pid):
                return True
            time.sleep(0.1)
        return False

    def test_env_ticks_and_time_limit(self):
        ticks = []
        r = self.job(sleep=30, minutes=0.05).run_agent("PROMPT", os.path.join(self.tmp.name, "log"),
                                                       lambda: ticks.append(1))
        self.assertEqual(r["status"], "timeout")
        self.assertLess(r["seconds"], 15)
        self.assertGreaterEqual(len(ticks), 1)
        rep = load(self.report)
        self.assertEqual(rep["prompt"], "PROMPT")
        for k in ("GH_TOKEN", "PR_TOKEN", "ANTHROPIC_API_KEY", "CONTRIBUTE_PUSH_TOKEN", "GITHUB_TOKEN"):
            self.assertNotIn(k, rep["env"])
        self.assertTrue(self.wait_dead(rep["child"]), "the agent's children must be stopped too")

    def test_tick_can_stop_the_agent(self):
        r = self.job(sleep=30, minutes=5).run_agent("P", os.path.join(self.tmp.name, "log"), lambda: "stop")
        self.assertEqual(r["status"], "stopped")
        self.assertTrue(self.wait_dead(load(self.report)["child"]))

    def test_normal_finish(self):
        r = self.job(sleep=0, minutes=5).run_agent("P", os.path.join(self.tmp.name, "log"), lambda: None)
        self.assertEqual((r["status"], r["returncode"]), ("finished", 0))


FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(a) + "\n")
def has(*xs):
    return all(x in a for x in xs)
if has("api", ".permissions.push"):
    print(os.environ.get("FAKE_PUSH", "true"))
elif has("api", "user"):
    print("alice")
elif has("api", ".parent.full_name"):
    print("hora-algebra/concept-mining")
elif has("api", ".full_name"):
    print("hora-algebra/concept-mining")
elif has("repo", "fork"):
    print("! alice/concept-mining already exists", file=sys.stderr)
elif has("pr", "list", "open"):
    path = os.environ["FAKE_OPEN"]
    print(open(path).read() if os.path.exists(path) else "[]")
elif has("pr", "list"):
    print("[]")
elif has("pr", "create"):
    print("https://github.com/hora-algebra/concept-mining/pull/99")
"""

AGENT_EDIT = r"""
import json, os, sys, time
sys.stdin.read()
p = "CFSG/Toy/A.lean"
lines = open(p).read().splitlines(True)
open(p, "w").write("".join(lines[:10]))
json.dump({"name": "shared", "meaning": "A shared lemma."}, open(".concept-mining/concept.json", "w"))
if os.environ.get("TAKE_IT"):  # someone else opens a pull request for the same candidate meanwhile
    time.sleep(0.5)
    open(os.environ["TAKE_IT"], "w").write(json.dumps([{"number": 50, "title": "[Toy/first] x", "body": "",
        "url": "https://github.com/hora-algebra/concept-mining/pull/50", "author": {"login": "bob"}}]))
time.sleep(float(os.environ.get("AGENT_SLEEP", "4")))
"""


class FlowTests(unittest.TestCase):
    """The whole run with a fake gh and no pushes: reservation, hand-in, closing, forks and links."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root, self.repo, bin_ = (os.path.join(t, n) for n in ("root", "repo", "bin"))
        os.makedirs(os.path.join(self.root, "CFSG", "Toy"))
        for d in ("data/pilot/Toy", "data/protected", "lean/patches/Toy"):
            os.makedirs(os.path.join(self.repo, d))
        os.makedirs(bin_)
        with open(os.path.join(self.root, "CFSG", "Toy", "A.lean"), "w") as f:
            f.write("set_option autoImplicit false\n" + "".join(
                f"theorem t{i} (a b : Nat) : a + b = b + a := Nat.add_comm a b\n" for i in range(30)))
        with open(os.path.join(self.repo, "data/pilot/Toy/candidates.jsonl"), "w") as f:
            for cid in ("first", "second"):
                f.write(json.dumps({"id": cid, "kind": "copies", "title": f"Merge {cid}", "summary": "s",
                                    "instructions": "do it", "estimate": 9}) + "\n")
        with open(os.path.join(self.repo, "data/protected/Toy.txt"), "w") as f:
            f.write("t0\n")
        with open(os.path.join(self.repo, "lean/patches/Toy/0001-old.patch"), "w") as f:
            f.write("x\n")
        for d in (self.root, self.repo):
            sh("git", "init", "-q", "-b", "main", cwd=d)
            sh("git", "add", "-A", cwd=d)
            sh("git", "commit", "-qm", "base", cwd=d, env=GIT_ID)
        sh("git", "update-ref", C.UPSTREAM_MAIN, "HEAD", cwd=self.repo)
        for name, body in (("gh", FAKE_GH), ("lake", "#!/bin/sh\nexit 1\n")):
            with open(os.path.join(bin_, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(bin_, name), 0o755)
        self.agent = os.path.join(t, "agent.py")
        with open(self.agent, "w") as f:
            f.write(AGENT_EDIT)
        self.ghlog, self.open_file = os.path.join(t, "gh.log"), os.path.join(t, "open.json")
        self.env = {"PATH": bin_ + os.pathsep + os.environ["PATH"], "FAKE_GH_LOG": self.ghlog,
                    "FAKE_OPEN": self.open_file, "GITHUB_STEP_SUMMARY": os.path.join(t, "summary.md")}
        self.saved = (C.REPO, C.STATE)
        C.REPO, C.STATE = self.repo, os.path.join(self.repo, "out", "contribute-state.json")
        self.pushes = []

    def tearDown(self):
        C.REPO, C.STATE = self.saved
        self.tmp.cleanup()

    def run_flow(self, *args, verdict="accept", env=()):
        from unittest import mock
        pushes, main = self.pushes, sh("git", "rev-parse", C.UPSTREAM_MAIN, cwd=self.repo)
        def verify(job, out, head=None):
            if head:  # the quick check passes whenever there is a change
                return {"verdict": "unchecked", "phase": "size", "reason": "", "tokens_saved": 420}
            v = {"verdict": verdict, "phase": "done" if verdict == "accept" else "build",
                 "reason": "" if verdict == "accept" else "build failed", "tokens_saved": 420, "code_lines_saved": 20}
            with open(out, "w") as f:
                json.dump(v, f)
            return v

        argv = ["--root", self.root, "--target", "Toy", "--agent", f"cmd:{sys.executable} {self.agent}",
                "--skip-prepare", "--allow-outdated", "--check-minutes", "0.02", *args]
        with mock.patch.dict(os.environ, {**self.env, **dict(env)}), \
                mock.patch.object(C.Contribution, "fetch_upstream", lambda job: None), \
                mock.patch.object(C.Contribution, "branch_base", lambda job: main), \
                mock.patch.object(C.Contribution, "push", lambda job, commit: pushes.append((job.push_repo, job.branch, commit))), \
                mock.patch.object(C.Contribution, "verify", verify):
            job = C.Contribution(C.parse_args(argv))
            try:
                code = job.go()
            except C.Stop as e:
                code = e.code
            finally:
                job.cleanup()
        with open(self.ghlog) as f:
            calls = [json.loads(l) for l in f]
        for call in calls:  # every call about pull requests names the repository explicitly
            if call[0] == "pr":
                self.assertIn("--repo", call)
                self.assertEqual(call[call.index("--repo") + 1], C.UPSTREAM)
        return code, job, calls

    def added_files(self, commit):
        main = sh("git", "rev-parse", C.UPSTREAM_MAIN, cwd=self.repo)
        return sh("git", "diff", "--name-status", main, commit, cwd=self.repo).splitlines()

    def test_collaborator_reserves_then_hands_in(self):
        code, job, calls = self.run_flow()
        self.assertEqual(code, 0)
        creates = [c for c in calls if c[:2] == ["pr", "create"]]
        self.assertEqual(len(creates), 1)
        self.assertIn("--draft", creates[0])
        self.assertEqual(creates[0][creates[0].index("--head") + 1], "contrib/Toy/first")
        self.assertIn(["pr", "ready", "99", "--repo", C.UPSTREAM], calls)
        self.assertTrue(any(c[:4] == ["api", "-X", "PATCH", f"repos/{C.UPSTREAM}/pulls/99"] for c in calls))
        self.assertEqual(len(self.pushes), 2)  # the reservation, then the accepted patch
        self.assertEqual(self.added_files(self.pushes[-1][2]), ["A\tlean/patches/Toy/0002-first.patch"])
        self.assertEqual(job.pr_status, "ready")
        self.assertFalse(any(c[:2] == ["pr", "close"] for c in calls))

    def test_rejected_draft_is_closed(self):
        code, job, calls = self.run_flow(verdict="reject")
        self.assertEqual(code, 1)
        close = [c for c in calls if c[:2] == ["pr", "close"]]
        self.assertEqual(len(close), 1)
        self.assertIn("--delete-branch", close[0])
        self.assertEqual(len(self.pushes), 1)  # only the reservation
        with open(C.STATE) as f:
            self.assertEqual(json.load(f)["status"], "closed")

    def test_fork_and_link_push_only_when_accepted(self):
        env = {"FAKE_PUSH": "false"}
        code, job, calls = self.run_flow("--pr", "link", verdict="reject", env=env)
        self.assertEqual((code, self.pushes), (1, []))
        self.assertFalse(any(c[:2] == ["pr", "create"] for c in calls))
        code, job, calls = self.run_flow("--pr", "link", "--candidate", "second", env=env)
        self.assertEqual(code, 0)
        self.assertEqual([p[:2] for p in self.pushes], [("alice/concept-mining", "contrib/Toy/second")])
        self.assertTrue(any(c[:2] == ["repo", "fork"] for c in calls))
        with open(self.env["GITHUB_STEP_SUMMARY"]) as f:
            text = f.read()
        self.assertIn("compare/main...alice:contrib/Toy/second?quick_pull=1", text)

    def test_handoff_then_hand_in_on_another_machine(self):
        from unittest import mock
        handoff = os.path.join(self.tmp.name, "handoff", "handoff.json")
        code, job, calls = self.run_flow("--pr", "none", "--handoff", handoff)
        self.assertEqual((code, self.pushes), (0, []))
        self.assertFalse(any(c[:2] == ["pr", "create"] for c in calls))
        with open(handoff) as f:
            h = json.load(f)
        self.assertEqual((h["target"], h["candidate"], h["concept"]["name"]), ("Toy", "first", "shared"))

        def hand_in(env=(), tamper=None):
            if tamper:
                with open(os.path.join(os.path.dirname(handoff), "result.patch"), "ab") as f:
                    f.write(tamper)
            main = sh("git", "rev-parse", C.UPSTREAM_MAIN, cwd=self.repo)
            pushes = []
            with mock.patch.dict(os.environ, {**self.env, "FAKE_PUSH": "false", **dict(env)}), \
                    mock.patch.object(C.Contribution, "fetch_upstream", lambda job: None), \
                    mock.patch.object(C.Contribution, "branch_base", lambda job: main), \
                    mock.patch.object(C.Contribution, "push", lambda job, commit: pushes.append((job.push_repo, job.branch, commit))):
                job = C.Contribution(C.parse_args(["--hand-in", handoff, "--pr", "link", "--fork", "alice/concept-mining",
                                                   "--contributor", "alice"]))
                return job.hand_in_only(), pushes

        code, pushes = hand_in()
        self.assertEqual(code, 0)
        self.assertEqual([p[:2] for p in pushes], [("alice/concept-mining", "contrib/Toy/first")])
        self.assertEqual(self.added_files(pushes[0][2]), ["A\tlean/patches/Toy/0002-first.patch"])
        with self.assertRaises(C.Stop) as e:  # a token that the agent slipped into the patch is never pushed
            hand_in(env={"PR_TOKEN": "pr-token-value-0123456789"}, tamper=b"-- pr-token-value-0123456789\n")
        self.assertIn("token", str(e.exception))
        with self.assertRaises(C.Stop):  # a patch outside the target is refused
            hand_in(tamper=b"diff --git a/.github/workflows/x.yml b/.github/workflows/x.yml\n")

    def test_someone_else_takes_the_candidate(self):
        code, job, calls = self.run_flow("--pass-env", "TAKE_IT", "--pass-env", "AGENT_SLEEP",
                                         env={"TAKE_IT": self.open_file, "AGENT_SLEEP": "30"})
        self.assertEqual(code, 3)
        self.assertEqual(self.pushes, [])
        self.assertFalse(any(c[:2] == ["pr", "create"] for c in calls))
        self.assertEqual(sh("git", "status", "--porcelain", "--", "CFSG", cwd=self.root), "")


if __name__ == "__main__":
    unittest.main()
