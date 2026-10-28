"""A failed release stays visible in one issue per target until a release completes."""

import json
import tempfile
import unittest
from pathlib import Path

from support import load_script

alert = load_script("release_alert")
RUN = "https://github.com/example/off-key/actions/runs/7"
SHA = "a" * 40


class FakeGitHub:
    def __init__(self, issues=()):
        self.issues = list(issues)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        return ""


class ReleaseAlertTests(unittest.TestCase):
    def test_a_failure_opens_one_issue_and_later_failures_comment_on_it(self):
        lines = [
            "Production release failed; inspect private server records and retry.",
            "Failed Ansible task: stack_deploy : Require application readiness after startup",
            "Failed readiness check: ingress heartbeat",
        ]
        github = FakeGitHub([{"number": 3, "title": "Unrelated"}])
        note = alert.alert(
            "production", lines, False, SHA, RUN, "OliverHennhoefer", gh=github
        )
        self.assertEqual(note, "Opened an issue: Production release needs attention.")
        create = github.calls[-1]
        self.assertEqual(
            create[:4], ("issue", "create", "--title", alert.TITLES["production"])
        )
        body = create[-1]
        self.assertTrue(body.startswith("@OliverHennhoefer The production release of"))
        for line in lines:
            self.assertIn(line, body)
        self.assertIn(f"revision `{SHA}`", body)
        self.assertIn(RUN, body)

        github = FakeGitHub([{"number": 12, "title": alert.TITLES["production"]}])
        refused = ["Failed Ansible task: stack_prepare : " + alert.REFUSED]
        note = alert.alert(
            "production", refused, False, "b" * 40, RUN, "OliverHennhoefer", gh=github
        )
        self.assertEqual(note, "Commented on the open production release issue #12.")
        comment = github.calls[-1]
        self.assertEqual(comment[:3], ("issue", "comment", "12"))
        self.assertIn("Retry the interrupted release first", comment[-1])
        self.assertNotIn("@OliverHennhoefer", comment[-1])

    def test_a_completed_release_closes_only_its_own_targets_issue(self):
        github = FakeGitHub(
            [
                {"number": 12, "title": alert.TITLES["production"]},
                {"number": 13, "title": alert.TITLES["demo"]},
            ]
        )
        note = alert.alert("demo", None, True, SHA, RUN, gh=github)
        self.assertEqual(note, "Closed the demo release issue #13.")
        self.assertEqual(github.calls[-1][:3], ("issue", "close", "13"))
        github = FakeGitHub()
        self.assertIsNone(alert.alert("production", None, True, SHA, RUN, gh=github))
        self.assertEqual([call[:2] for call in github.calls], [("issue", "list")])

    def test_demo_retries_name_demo_only_and_bots_are_not_mentioned(self):
        github = FakeGitHub()
        alert.alert(
            "demo",
            ["Demo release failed"],
            False,
            SHA,
            RUN,
            "dependabot[bot]",
            gh=github,
        )
        body = github.calls[-1][-1]
        self.assertTrue(body.startswith("The demo release of"))
        self.assertIn("**demo_only** checked", body)

    def test_outcomes_report_each_target_and_a_silent_job_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self.assertEqual(alert.outcomes(directory, job_failed=False), {})
            self.assertEqual(
                alert.outcomes(directory, job_failed=True), {"production": ([], False)}
            )
            (directory / "production.released").touch()
            (directory / "demo.failed").write_text("Demo release failed\n")
            self.assertEqual(
                alert.outcomes(directory, job_failed=True),
                {"production": (None, True), "demo": (["Demo release failed"], False)},
            )
        self.assertIn(
            "failed before Ansible reported",
            alert.failure_report("production", [], SHA, RUN),
        )


if __name__ == "__main__":
    unittest.main()
