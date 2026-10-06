"""Production rehearsal must distinguish failed publication from missing images."""

import importlib.util
import sys
import unittest
from unittest.mock import patch

import yaml
from support import ROOT


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("pin_release")
with patch.dict(sys.modules, {"pin_release": release}):
    publisher = load("wait_for_publish")

REVISION = "a" * 40
RUN = {
    "id": 42,
    "run_attempt": 1,
    "head_sha": REVISION,
    "head_branch": "main",
    "event": "push",
    "status": "completed",
    "conclusion": "success",
    "html_url": "https://github.com/example/repo/actions/runs/42",
}


class PublishTests(unittest.TestCase):
    def test_waits_for_missing_and_running_publisher_before_accepting_success(self):
        with (
            patch.object(
                release,
                "github",
                side_effect=[
                    {"workflow_runs": []},
                    {"workflow_runs": [RUN | {"status": "in_progress"}]},
                    {"workflow_runs": [RUN]},
                ],
            ) as github,
            patch.object(publisher.time, "sleep") as sleep,
        ):
            self.assertEqual(publisher.wait_for_publish(REVISION), RUN)
            self.assertEqual(sleep.call_count, 2)
            self.assertIn(f"head_sha={REVISION}", github.call_args.args[0])

    def test_failed_or_cancelled_publish_fails_immediately(self):
        for conclusion in ("failure", "cancelled", "timed_out", "skipped"):
            with (
                self.subTest(conclusion=conclusion),
                patch.object(
                    release,
                    "github",
                    return_value={"workflow_runs": [RUN | {"conclusion": conclusion}]},
                ),
                patch.object(publisher.time, "sleep") as sleep,
                self.assertRaisesRegex(RuntimeError, f"run 42.*{conclusion}"),
            ):
                publisher.wait_for_publish(REVISION)
            sleep.assert_not_called()

    def test_older_success_cannot_hide_a_failed_rerun(self):
        with (
            patch.object(
                release,
                "github",
                return_value={
                    "workflow_runs": [
                        RUN,
                        RUN | {"run_attempt": 2, "conclusion": "failure"},
                    ]
                },
            ),
            self.assertRaisesRegex(RuntimeError, "attempt 2.*failure"),
        ):
            publisher.wait_for_publish(REVISION)

    def test_another_commit_branch_or_event_never_satisfies_publication(self):
        for changes in (
            {"head_sha": "b" * 40},
            {"head_branch": "feature"},
            {"event": "pull_request"},
        ):
            with (
                self.subTest(changes=changes),
                patch.object(
                    release, "github", return_value={"workflow_runs": [RUN | changes]}
                ),
                self.assertRaisesRegex(TimeoutError, "not started"),
            ):
                publisher.wait_for_publish(REVISION, timeout=0)

    def test_pending_publisher_has_a_bounded_wait(self):
        with (
            patch.object(
                release,
                "github",
                return_value={"workflow_runs": [RUN | {"status": "queued"}]},
            ),
            patch.object(publisher.time, "sleep") as sleep,
            self.assertRaisesRegex(TimeoutError, "still queued"),
        ):
            publisher.wait_for_publish(REVISION, timeout=0)
        sleep.assert_not_called()

    def test_invalid_revision_makes_no_github_request(self):
        with (
            patch.object(release, "github") as github,
            self.assertRaises(ValueError),
        ):
            publisher.wait_for_publish("main&status=success")
        github.assert_not_called()

    def test_main_workflow_checks_publication_before_swarm_setup(self):
        workflow = yaml.safe_load(
            (ROOT.parent / ".github/workflows/deployment-smoke.yml").read_text()
        )
        self.assertEqual(workflow["permissions"]["actions"], "read")
        steps = workflow["jobs"]["deployment-smoke"]["steps"]
        preflight = next(
            step for step in steps if "wait_for_publish.py" in step.get("run", "")
        )
        prepare = next(
            step for step in steps if "docker swarm init" in step.get("run", "")
        )
        self.assertLess(steps.index(preflight), steps.index(prepare))
        self.assertIn("github.event_name == 'push'", preflight["if"])
        self.assertIn("github.ref == 'refs/heads/main'", preflight["if"])
        self.assertEqual(preflight["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertIn('"$GITHUB_SHA"', preflight["run"])
