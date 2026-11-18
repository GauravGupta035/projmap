"""Tests for projmap's own logic, on made-up data. No network and no gh: GitHub answers are stubbed."""
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from projmap import cli

REPO = pathlib.Path(__file__).resolve().parent.parent


def issue(n, open=True, reason="", labels=(), deps=(), text=""):
    return {"n": n, "title": f"Issue {n}", "open": open, "reason": reason, "labels": list(labels),
            "deps": list(deps), "size": None, "criteria": 0, "gate": None, "closedAt": None,
            "url": f"https://example.test/issues/{n}", "text": text or f"Issue {n}"}


def pr(n, closes=(), state="OPEN", merged=None, paths=(), labels=()):
    return {"n": n, "title": f"PR {n}", "state": state, "mergedAt": merged, "labels": list(labels),
            "closes": list(closes), "rounds": 0, "checks": "none", "url": f"https://example.test/pull/{n}",
            "paths": list(paths)}


def raw_pr(n, rollup=(), body="", closing=()):
    return {"number": n, "title": f"PR {n}", "body": body, "state": "OPEN", "mergedAt": None, "labels": [],
            "closingIssuesReferences": [{"number": c} for c in closing], "url": "u", "reviews": [],
            "comments": [], "statusCheckRollup": list(rollup), "files": []}


def raw_issue(n, body="", state="OPEN", comments=()):
    return {"number": n, "title": f"Issue {n}", "state": state, "stateReason": "", "labels": [], "body": body,
            "closedAt": None, "url": "u", "comments": [{"body": c} for c in comments]}


def write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


class TempRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class WordCaps(unittest.TestCase):
    def test_a_record_within_its_cap_passes(self):
        content = {"terms": [{"id": "t", "plain": "short and plain"}], "story": ["One.", "Two."]}
        self.assertEqual(cli.check_caps(content, {}), [])

    def test_each_kind_of_record_over_its_cap_is_named(self):
        long = " ".join(["word"] * 30)
        content = {
            "terms": [{"id": "t", "plain": long}],
            "knobs": [{"id": "k", "plain": "fine", "reaches": [{"to": "x", "how": long}]}],
            "issues": {"7": {"plain": long}},
            "story": ["s"] * (cli.STORY_CAP + 1),
            "lists": [{"id": "codes", "caps": {"plain": 3}, "rows": [{"id": "E1", "plain": "one two three four"}]}],
        }
        over = cli.check_caps(content, {})
        self.assertEqual(len(over), 5)
        for expected in ("terms t.plain", "knobs k -> x", "issues 7.plain", "story:", "lists.codes E1.plain"):
            self.assertTrue(any(line.startswith(expected) for line in over), expected)

    def test_the_config_can_raise_a_cap(self):
        content = {"terms": [{"id": "t", "plain": " ".join(["word"] * 22)}]}
        self.assertEqual(len(cli.check_caps(content, {})), 1)
        self.assertEqual(cli.check_caps(content, {"caps": {"terms.plain": 25}}), [])


class Stages(unittest.TestCase):
    def stage(self, item, prs=(), others=(), stages=cli.STAGES):
        by_number = {i["n"]: i for i in [item, *others]}
        return cli.stage_of(item, list(prs), by_number, stages)

    def test_a_merged_pull_request_means_merged(self):
        self.assertEqual(self.stage(issue(1, open=False), [pr(9, merged="2026-01-01T00:00:00Z", state="MERGED")]), "done")

    def test_closed_as_completed_with_no_pull_request_counts_as_merged(self):
        self.assertEqual(self.stage(issue(1, open=False, reason="COMPLETED")), "done")

    def test_closed_as_not_planned_is_closed(self):
        self.assertEqual(self.stage(issue(1, open=False, reason="NOT_PLANNED")), "closed")

    def test_an_open_pull_request_means_in_review(self):
        self.assertEqual(self.stage(issue(1), [pr(9)]), "review")

    def test_an_open_dependency_means_waiting(self):
        self.assertEqual(self.stage(issue(2, deps=[1]), others=[issue(1)]), "wait")

    def test_a_closed_dependency_lets_it_start(self):
        self.assertEqual(self.stage(issue(2, deps=[1]), others=[issue(1, open=False)]), "open")

    def test_a_dependency_not_on_github_is_not_met(self):
        self.assertEqual(self.stage(issue(2, deps=[99])), "wait")

    def test_label_conditions_in_custom_stages(self):
        stages = [{"id": "triage", "when": {"open": True, "label": "needs-triage"}},
                  {"id": "either", "when": {"anyLabel": ["a", "b"]}},
                  {"id": "approved", "when": {"prLabel": "approved"}},
                  {"id": "rest", "when": {}}]
        self.assertEqual(self.stage(issue(1, labels=["needs-triage"]), stages=stages), "triage")
        self.assertEqual(self.stage(issue(1, labels=["b"]), stages=stages), "either")
        self.assertEqual(self.stage(issue(1), [pr(9, labels=["approved"])], stages=stages), "approved")
        self.assertEqual(self.stage(issue(1), stages=stages), "rest")


class ReadingGitHub(unittest.TestCase):
    def fetch(self, issues=(), prs=(), config=None):
        answers = {"issue": list(issues), "pr": list(prs)}
        with mock.patch.object(cli, "gh", lambda root, *args: answers[args[0]]):
            return cli.fetch_github(pathlib.Path("."), config or {})

    def test_check_states(self):
        prs = self.fetch(prs=[
            raw_pr(1, [{"conclusion": "SUCCESS"}, {"conclusion": "", "status": "IN_PROGRESS"}]),
            raw_pr(2, [{"state": "PENDING"}]),
            raw_pr(3, [{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}, {"conclusion": ""}]),
            raw_pr(4, [{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}, {"conclusion": "SKIPPED"}]),
            raw_pr(5, [{"state": "EXPECTED"}]),
            raw_pr(6, []),
        ])["prs"]
        self.assertEqual({p["n"]: p["checks"] for p in prs},
                         {1: "pending", 2: "pending", 3: "failing", 4: "passed", 5: "pending", 6: "none"})

    def test_a_pull_request_closes_issues_named_in_its_body_and_by_github(self):
        prs = self.fetch(prs=[raw_pr(1, body="Fixes #3 and resolves #4", closing=[5])])["prs"]
        self.assertEqual(prs[0]["closes"], [3, 4, 5])

    def test_issue_dependencies_criteria_and_gate(self):
        body = "Depends on #1, #2 and #7\n\n- [ ] one\n- [x] two\n"
        config = {"gate": {"marker": "<!-- gate -->", "pass": "READY"}}
        issues = self.fetch(issues=[raw_issue(7, body, comments=["<!-- gate --> READY"])], config=config)["issues"]
        self.assertEqual(issues[0]["deps"], [1, 2])
        self.assertEqual(issues[0]["criteria"], 2)
        self.assertEqual(issues[0]["gate"], "ready")

    def test_a_failing_gate_comment_says_needs(self):
        config = {"gate": {"marker": "<!-- gate -->", "pass": "READY"}}
        issues = self.fetch(issues=[raw_issue(1, comments=["<!-- gate --> missing criteria"])], config=config)["issues"]
        self.assertEqual(issues[0]["gate"], "needs")


class Modules(TempRepo):
    def setUp(self):
        super().setUp()
        write(self.root, {
            "src/core/base.py": "def test_one():\n    pass\n",
            "src/api/routes.py": "from core import base\n",
            "src/web/app.py": "import api\n# core is mentioned here but not imported\n",
            "src/empty/README.md": "no code\n",
        })
        self.modules = cli.scan_modules(self.root, {})

    def test_finds_modules_with_code_and_counts_them(self):
        self.assertEqual(sorted(self.modules), ["api", "core", "web"])
        self.assertEqual(self.modules["core"]["files"], 1)
        self.assertEqual(self.modules["core"]["tests"], 1)

    def test_reads_imports_but_not_other_mentions(self):
        self.assertEqual(self.modules["api"]["uses"], ["core"])
        self.assertEqual(self.modules["web"]["uses"], ["api"])

    def test_downstream_follows_imports_through_other_modules(self):
        self.assertEqual(cli.downstream({"core"}, self.modules), ["api", "web"])
        self.assertEqual(cli.downstream({"web"}, self.modules), [])

    def test_owner_is_the_longest_matching_folder(self):
        self.assertEqual(cli.owner_of("src/api/routes.py", self.modules), "api")
        self.assertIsNone(cli.owner_of("README.md", self.modules))
        self.assertIsNone(cli.owner_of("src/apiary/x.py", self.modules))

    def test_an_explicit_list_overrides_discovery(self):
        config = {"modules": {"list": [{"name": "server", "path": "src/api"}]}}
        self.assertEqual(sorted(cli.scan_modules(self.root, config)), ["server"])


class Touches(TempRepo):
    def setUp(self):
        super().setUp()
        write(self.root, {"src/core/a.py": "x = 1\n", "src/api/b.py": "import core\n"})
        self.modules = cli.scan_modules(self.root, {})

    def derive(self, issues, prs, content=None):
        return cli.derive({}, content or {}, self.modules, {"issues": issues, "prs": prs})

    def test_a_merged_pull_request_says_what_was_touched(self):
        issues, _ = self.derive([issue(1, open=False)],
                                [pr(9, closes=[1], state="MERGED", merged="2026-01-01", paths=["src/core/a.py", "README.md"])])
        self.assertEqual(issues[0]["touches"], {"modules": ["core"], "other": 1, "basis": "merged", "affects": ["api"]})

    def test_with_no_pull_request_the_text_predicts_it(self):
        issues, _ = self.derive([issue(1, text="Rename a function in core")], [])
        self.assertEqual(issues[0]["touches"]["basis"], "predicted")
        self.assertEqual(issues[0]["touches"]["modules"], ["core"])

    def test_the_hand_written_part_adds_a_module(self):
        content = {"components": [{"id": "routes", "module": "api"}], "issues": {"1": {"part": "routes"}}}
        issues, _ = self.derive([issue(1, text="Nothing named here")], [], content)
        self.assertEqual(issues[0]["touches"]["modules"], ["api"])

    def test_nothing_named_means_none(self):
        issues, _ = self.derive([issue(1, text="Fix the colours")], [])
        self.assertEqual(issues[0]["touches"]["basis"], "none")


class Drift(TempRepo):
    def test_issues_ids_and_modules(self):
        write(self.root, {"docs/adr/0001-use-json.md": "", "docs/adr/0002-caps.md": ""})
        config = {"ids": [{"kind": "decision", "in": "decisions",
                           "sources": [{"glob": "docs/adr/*.md", "name": r"^(\d{4})-"}]}]}
        content = {"issues": {"1": {"plain": "x"}, "50": {"plain": "gone"}},
                   "decisions": [{"id": "0001"}, {"id": "0009"}],
                   "components": [{"id": "c", "module": "core"}, {"id": "d", "module": "old"}]}
        modules = {"core": {}, "api": {}}
        drift = cli.find_drift(self.root, config, content, modules, [issue(1), issue(2), issue(3, open=False)])
        found = {(d["kind"], d["id"], d["problem"]) for d in drift}
        self.assertEqual(found, {
            ("issue", "2", "has no line on the map"),
            ("issue", "50", "is on the map but not on GitHub"),
            ("decision", "0002", "has no record on the map"),
            ("decision", "0009", "is on the map but no longer in the repo"),
            ("module", "api", "has no record on the map"),
            ("module", "old", "is on the map but no longer in the repo"),
        })

    def test_records_all_also_wants_closed_issues(self):
        drift = cli.find_drift(self.root, {"issues": {"records": "all"}}, {}, {}, [issue(1, open=False)])
        self.assertEqual([d["id"] for d in drift], ["1"])

    def test_ids_from_a_pattern_in_one_file(self):
        write(self.root, {"errors.txt": "E101 bad\nE102 worse\n"})
        found = cli.ids_in_repo(self.root, {"file": "errors.txt", "pattern": r"(E\d+)"})
        self.assertEqual(found, {"E101", "E102"})


class Backlog(unittest.TestCase):
    def test_default_draws_every_issue_linked_to_an_open_one(self):
        issues = [issue(1, open=False), issue(2, deps=[1]), issue(3, open=False), issue(4, open=False, deps=[3])]
        self.assertEqual(cli.pick_backlog({}, issues), [1, 2])

    def test_by_label_and_by_numbers(self):
        issues = [issue(1, labels=["epic"]), issue(2)]
        self.assertEqual(cli.pick_backlog({"backlog": {"label": "epic"}}, issues), [1])
        self.assertEqual(cli.pick_backlog({"backlog": {"numbers": [2]}}, issues), [2])


class Page(TempRepo):
    def test_gather_and_render_end_to_end(self):
        write(self.root, {"src/core/a.py": "x = 1\n", ".projmap/projmap.json": "{}",
                          ".projmap/content.json": json.dumps({"terms": [{"id": "t", "plain": "</script><b>x"}]})})
        github = {"issues": [issue(1)], "prs": [], "at": "1 January 2026, 00:00"}
        data, over = cli.gather(self.root, self.root / ".projmap/projmap.json", github)
        self.assertEqual(over, [])
        self.assertEqual(data["issues"][0]["stage"], "open")
        self.assertNotIn("text", data["issues"][0])
        self.assertEqual(data["content"]["components"][0]["auto"], True)
        page = cli.render(data)
        self.assertNotIn("__DATA__", page)
        self.assertEqual(page.count("</script><b>"), 0)

    def test_invalid_json_says_which_file(self):
        write(self.root, {"projmap.json": "{ not json"})
        with self.assertRaises(cli.MapError) as raised:
            cli.read_json(self.root / "projmap.json")
        self.assertIn("projmap.json", str(raised.exception))


class Init(TempRepo):
    def run_init(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        return subprocess.run([sys.executable, str(REPO / "bin" / "projmap"), "init"], cwd=self.root,
                              capture_output=True, text=True)

    def test_init_in_an_empty_repo_says_none(self):
        out = self.run_init()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("modules found: none", out.stdout)
        self.assertTrue((self.root / ".projmap" / "content.json").is_file())

    def test_init_lists_the_modules_it_found_and_refuses_twice(self):
        write(self.root, {"src/core/a.py": "x = 1\n"})
        self.assertIn("modules found: core", self.run_init().stdout)
        again = subprocess.run([sys.executable, str(REPO / "bin" / "projmap"), "init"], cwd=self.root,
                               capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already exists", again.stderr)


class Check(TempRepo):
    def test_check_exits_1_on_drift_and_0_when_clean(self):
        write(self.root, {"src/core/a.py": "x = 1\n", ".projmap/projmap.json": "{}", ".projmap/content.json": "{}"})
        github = {"issues": [issue(1)], "prs": [], "at": "now"}
        args = mock.Mock(config=str(self.root / ".projmap/projmap.json"), json=True)
        with mock.patch.object(cli, "git_root", return_value=self.root), \
                mock.patch.object(cli, "fetch_github", return_value=github):
            for issues, code in (([issue(1)], 1), ([], 0)):
                github["issues"] = issues
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exited:
                    cli.cmd_check(args)
                self.assertEqual(exited.exception.code, code)
                self.assertEqual(len(json.loads(out.getvalue())["drift"]), len(issues))


if __name__ == "__main__":
    unittest.main()
