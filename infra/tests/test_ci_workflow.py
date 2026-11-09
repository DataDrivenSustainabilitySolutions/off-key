"""CI is one workflow whose single, stable gate job stands for every check."""

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from support import ROOT, run

WORKFLOWS = ROOT.parent / ".github/workflows"
GATE = "ci-gate"


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def load_plan():
    spec = importlib.util.spec_from_file_location(
        "ci_plan", ROOT.parent / ".github/scripts/ci_plan.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Stand-ins for the runner's docker and python3: record every pull, resolve image
# names locally and hand anything else to the real interpreter.
DOCKER_STUB = """#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
"""
PYTHON_STUB = f"""#!/bin/sh
if [ "$1" = .github/scripts/release_image.py ]; then
  echo "ghcr.io/example/$2:release"
elif [ "$1" = -c ] && [ "$3" = ghcr.io/example/mqtt_radar:release ]; then
  echo "ghcr.io/example/mqtt_radar@sha256:pinned"
else
  exec {sys.executable} "$@"
fi
"""


def needs(job):
    value = job.get("needs", [])
    return [value] if isinstance(value, str) else value


class CiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.jobs = workflow("ci.yml")["jobs"]

    def test_the_gate_needs_every_job_so_none_can_fall_outside_it(self):
        gate = self.jobs[GATE]
        self.assertEqual(sorted(needs(gate)), sorted(set(self.jobs) - {GATE}))
        self.assertEqual(gate["if"], "always()")

    def test_the_required_check_name_is_constant(self):
        # Branch rules match check names literally; a matrix value or expression in
        # the gate's name would silently detach the rule on the next version bump.
        self.assertEqual(self.jobs[GATE]["name"], GATE)
        self.assertNotIn("strategy", self.jobs[GATE])

    def test_the_gate_enforces_the_plan_not_a_blanket_skip(self):
        steps = self.jobs[GATE]["steps"]
        gate = steps[-1]
        self.assertEqual(gate["env"]["NEEDS"], "${{ toJSON(needs) }}")
        self.assertEqual(gate["env"]["PLAN"], "${{ needs.changes.outputs.plan }}")
        self.assertEqual(gate["run"], "python3 .github/scripts/ci_gate.py")
        self.assertNotIn("if", gate)
        self.assertNotIn("continue-on-error", gate)

    def test_every_planned_job_is_selected_by_its_own_plan_entry(self):
        plan = load_plan()
        self.assertEqual(set(plan.JOBS), set(self.jobs) - {GATE, "changes"})
        for name in plan.JOBS:
            with self.subTest(job=name):
                condition = self.jobs[name]["if"]
                self.assertTrue(
                    f"fromJSON(needs.changes.outputs.plan).{name}" in condition
                    or f"fromJSON(needs.changes.outputs.plan)['{name}']" in condition
                )
                self.assertIn("changes", needs(self.jobs[name]))
        self.assertNotIn("if", self.jobs["changes"])
        self.assertEqual(needs(self.jobs["changes"]), [])

    def test_exactly_one_image_job_runs_per_event(self):
        self.assertEqual(
            self.jobs["publish"]["if"],
            "github.event_name == 'push' && fromJSON(needs.changes.outputs.plan).publish",
        )
        self.assertTrue(
            self.jobs["images"]["if"].startswith("github.event_name != 'push' && ")
        )
        self.assertNotIn("with", self.jobs["images"])
        self.assertNotIn("publish", self.jobs["publish"]["with"])

    def test_cheap_checks_gate_the_costly_jobs(self):
        for name in (
            "backend",
            "contracts",
            "infrastructure",
            "collection",
            "observability",
            "images",
            "publish",
            "radar",
            "deployment-smoke",
        ):
            with self.subTest(job=name):
                self.assertIn("lint", needs(self.jobs[name]))
        self.assertIn("frontend", needs(self.jobs["deployment-smoke"]))
        # Independent suites do not wait for each other.
        for name in ("backend", "infrastructure", "collection", "observability"):
            self.assertEqual(needs(self.jobs[name]), ["changes", "lint"])
        self.assertEqual(needs(self.jobs["lint"]), ["changes"])
        self.assertEqual(needs(self.jobs["frontend"]), ["changes"])

    def test_version_independent_checks_run_once(self):
        lint = [step.get("run", "") for step in self.jobs["lint"]["steps"]]
        backend = [step.get("run", "") for step in self.jobs["backend"]["steps"]]
        for command in ("pre-commit run", "ty check", "generate_pipeline_types.py"):
            self.assertTrue(any(command in run for run in lint), command)
            self.assertFalse(any(command in run for run in backend), command)
        self.assertEqual(
            self.jobs["backend"]["strategy"]["matrix"]["python"], ["3.12", "3.14"]
        )
        self.assertEqual(
            self.jobs["collection"]["strategy"]["matrix"]["emqx"], ["5.8.7", "6.3.2"]
        )

    def test_main_rehearses_the_images_this_run_published(self):
        smoke = self.jobs["deployment-smoke"]
        self.assertIn("publish", needs(smoke))
        self.assertIn("images", needs(smoke))
        for job in (smoke, self.jobs["radar"]):
            self.assertIn(
                "github.event_name == 'push' && needs.publish.result == 'success'",
                job["if"],
            )
            self.assertIn(
                "github.event_name != 'push' && needs.images.result == 'success'",
                job["if"],
            )
            self.assertNotIn("actions", job["permissions"])
            self.assertEqual(job["permissions"]["packages"], "read")
        prepare = next(
            step
            for step in smoke["steps"]
            if step["name"] == "Prepare disposable production Swarm"
        )
        self.assertNotIn("uses", prepare)
        self.assertEqual(
            prepare["env"]["OFFKEY_REHEARSAL_IMAGES"],
            "${{ github.event_name != 'push' && 'loaded' || 'published' }}",
        )

    def test_other_events_reuse_one_verified_image_build(self):
        images = self.jobs["images"]
        self.assertNotIn("permissions", images)
        build = next(step for step in images["steps"] if step.get("id") == "build")
        self.assertIn("build-ci-images", build["with"]["run"])
        upload = images["steps"][-1]
        self.assertEqual(upload["with"]["name"], "ci-images")
        self.assertEqual(upload["with"]["retention-days"], "1")
        self.assertTrue(
            any(
                "check_nginx_startup.py" in step.get("run", "")
                for step in images["steps"]
            )
        )
        for name in ("radar", "deployment-smoke"):
            load = next(
                step
                for step in self.jobs[name]["steps"]
                if step.get("uses") == "./.github/actions/load-ci-images"
            )
            self.assertEqual(load["if"], "github.event_name != 'push'")
            self.assertEqual(
                load["with"],
                {
                    "manifest": "${{ needs.images.outputs.manifest }}",
                    "archive-sha256": "${{ needs.images.outputs.archive-sha256 }}",
                },
            )
        # No job other than the images job builds a current application image.
        for name, job in self.jobs.items():
            for step in job.get("steps", []):
                text = step.get("run", "") + step.get("with", {}).get("run", "")
                if name != "images":
                    self.assertNotIn("build-ci-images", text)
                    self.assertNotIn("backend/Dockerfile", text)

    def test_only_the_publish_job_can_write_packages(self):
        self.assertEqual(workflow("ci.yml")["permissions"], {"contents": "read"})
        writers = [
            name
            for name, job in self.jobs.items()
            if job.get("permissions", {}).get("packages") == "write"
        ]
        self.assertEqual(writers, ["publish"])
        published = workflow("docker-images.yml")
        self.assertEqual(list(published["on"]), ["workflow_call"])
        self.assertNotIn("publish", published["on"]["workflow_call"]["inputs"])

    def test_published_and_tested_images_share_their_build_inputs(self):
        matrix = workflow("docker-images.yml")["jobs"]["build-images"]["strategy"][
            "matrix"
        ]["include"]
        for entry in matrix:
            with self.subTest(service=entry["service"]):
                if entry["service"] == "frontend":
                    self.assertEqual(entry["target"], "production")
                    continue
                self.assertEqual(entry["target"], "")
                if entry["service"] == "docs":
                    self.assertEqual(entry["context"], ".")
                    self.assertEqual(entry["file"], "./dev/docs/Dockerfile")
                    self.assertEqual(entry["build_args"], "")
                    continue
                self.assertIn("GIT_COMMIT=${{ github.sha }}", entry["build_args"])

    def test_build_cache_credentials_reach_only_image_builds(self):
        self.assertEqual(
            self.jobs["publish"]["with"]["cache-fallback-scope-prefix"],
            "docker-validate",
        )
        cached = {
            step["name"]
            for job in self.jobs.values()
            for step in job.get("steps", [])
            if step.get("uses") == "./.github/actions/run-with-build-cache"
        }
        self.assertEqual(
            cached,
            {
                "Build every application image once",
                "Build the reviewed compatible binary rollback reference",
            },
        )

    def test_radar_image_selection_runs_on_push_and_pull_request(self):
        step = next(
            step
            for step in self.jobs["radar"]["steps"]
            if step.get("name")
            == "Select the production database and this run's RADAR image"
        )
        manifest = {
            "images": {"mqtt_radar": {"reference": "off-key/mqtt-radar:ci-loaded"}}
        }
        for event, radar in (
            ("push", "ghcr.io/example/mqtt_radar@sha256:pinned"),
            ("pull_request", "off-key/mqtt-radar:ci-loaded"),
        ):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                for name, body in (("docker", DOCKER_STUB), ("python3", PYTHON_STUB)):
                    (tmp / name).write_text(body)
                    (tmp / name).chmod(stat.S_IRWXU)
                (tmp / "step.sh").write_text(step["run"])
                # Only what the runner provides; values the step writes to
                # GITHUB_ENV reach later steps, never this one.
                env = {
                    "PATH": f"{tmp}:{os.environ['PATH']}",
                    "GITHUB_ENV": str(tmp / "github_env"),
                    "GITHUB_EVENT_NAME": event,
                    "GITHUB_SHA": "0" * 40,
                    "MANIFEST": json.dumps(manifest),
                    "DOCKER_LOG": str(tmp / "docker.log"),
                }
                run(
                    "bash", "--noprofile", "--norc", "-e", "-o", "pipefail",
                    tmp / "step.sh", cwd=ROOT.parent, env=env,
                )  # fmt: skip
                self.assertEqual(
                    (tmp / "github_env").read_text().splitlines(),
                    [
                        "TEST_RADAR_DATABASE_IMAGE=ghcr.io/example/postgres:release",
                        f"TEST_RADAR_SWARM_IMAGE={radar}",
                    ],
                )
                pulls = (tmp / "docker.log").read_text().splitlines()
                self.assertIn("pull --quiet ghcr.io/example/postgres:release", pulls)
                self.assertIn("pull --quiet eclipse-mosquitto:2.0", pulls)
                self.assertEqual(
                    f"pull --quiet {radar}" in pulls, event == "push", pulls
                )

    def test_a_manual_run_cannot_cancel_the_releasing_push_run(self):
        group = workflow("ci.yml")["concurrency"]["group"]
        self.assertIn("${{ github.event_name }}", group)


if __name__ == "__main__":
    unittest.main()
