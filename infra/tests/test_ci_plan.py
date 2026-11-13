"""The CI plan narrows only explicit, defensible changes and the gate holds it."""

import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from support import ROOT

SCRIPTS = ROOT.parent / ".github/scripts"
REPOSITORY = "DataDrivenSustainabilitySolutions/off-key"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = load("ci_plan")
gate = load("ci_gate")
FULL_NON_PUSH = {
    job: job not in {"contracts", "publish", "static", "static-release"}
    for job in plan.JOBS
}


def selected(jobs):
    return {job for job, run in jobs.items() if run}


class Repository:
    """A throwaway git repository whose commits the planner diffs for real."""

    def __init__(self, directory):
        self.root = Path(directory)
        self.git("init", "-q", "-b", "main")
        self.write("backend/app.py", "print('a')\n")
        self.write("README.md", "Guide\n")
        self.write("frontend/src/App.tsx", "export {}\n")
        self.write("frontend/package-lock.json", "{}\n")
        self.base = self.commit("base")

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def plan(self, event_name, event, head, **kwargs):
        with (
            patch.object(plan, "git", self.git),
            patch.object(plan, "is_ancestor", self.ancestor),
        ):
            return plan.plan(event_name, event, head, REPOSITORY, **kwargs)

    def ancestor(self, ancestor, descendant):
        try:
            self.git("merge-base", "--is-ancestor", ancestor, descendant)
            return True
        except subprocess.CalledProcessError:
            return False


class ClassificationTests(unittest.TestCase):
    def test_paths_select_the_narrowest_safe_mode(self):
        cases = {
            ("README.md",): "docs",
            ("dev/docs/llms.py", "zensical.toml", "README.md"): "full",
            ("docs/guide.md",): "published-docs",
            ("docs/guide.md", "README.md", "zensical.toml"): "published-docs",
            ("infra/stack/landing.html.j2", "assets/landing/export.py"): "landing",
            (
                "assets/landing/export.py",
                "infra/stack/landing-assets.json",
                "infra/stack/landing.html.j2",
                "infra/stack/landing.md.j2",
            ): "landing",
            (
                "assets/landing/hero-v15.jpg",
                "assets/landing/hero-v15.source.txt",
            ): "landing",
            ("docs/guide.md", "infra/stack/landing.md.j2"): "static",
            ("docs/guide.md", "frontend/src/App.tsx"): "full",
            ("infra/stack/landing-nginx.conf.j2",): "full",
            ("infra/stack/other-assets.json",): "full",
            ("assets/landing/new-build.py",): "full",
            ("dev/docs/Dockerfile",): "full",
            ("frontend/src/App.tsx", "README.md"): "frontend",
            (
                "frontend/e2e/journey.spec.ts",
                "frontend/nginx.conf.template",
            ): "frontend",
            # Shared core and services.
            ("backend/libs/core/src/off_key_core/db/models.py",): "full",
            ("backend/services/api/gateway/main.py", "README.md"): "full",
            # Lockfiles and dependency manifests.
            ("frontend/package-lock.json",): "full",
            ("frontend/package.json",): "full",
            ("frontend/.npmrc",): "full",
            ("backend/uv.lock",): "full",
            ("infra/uv.lock",): "full",
            ("requirements-docs.txt",): "full",
            ("backend/pyproject.toml",): "full",
            # Dockerfiles, infrastructure and CI.
            ("frontend/Dockerfile",): "full",
            ("frontend/.dockerignore",): "full",
            ("backend/Dockerfile",): "full",
            ("infra/README.md",): "full",
            ("infra/stack/landing.md.j2",): "landing",
            (".github/workflows/ci.yml",): "full",
            (".github/scripts/ci_plan.py",): "full",
            (".github/dependabot.yml",): "full",
            ("docker-compose.yml",): "full",
            ("Makefile",): "full",
            ("assets/brand/logo.svg",): "full",
            # Unknown or unusual paths.
            ("LICENSE",): "full",
            ("new-top-level-dir/file.txt",): "full",
            ("docs/../backend/app.py",): "full",
            ("",): "full",
            # Nothing changed is not proof that nothing needs testing.
            (): "full",
        }
        for paths, mode in cases.items():
            with self.subTest(paths=paths):
                self.assertEqual(plan.mode_for(list(paths)), mode)

    def test_each_mode_selects_its_jobs_and_one_image_job_per_event(self):
        docs = plan.plan_for("docs", "pull_request")
        self.assertEqual(selected(docs), {"static"})
        for mode in plan.STATIC_RELEASE_MODES:
            self.assertEqual(selected(plan.plan_for(mode, "pull_request")), {"static"})
            self.assertEqual(
                selected(plan.plan_for(mode, "push")), {"static", "static-release"}
            )
        frontend = plan.plan_for("frontend", "pull_request")
        self.assertEqual(
            selected(frontend),
            {
                "lint",
                "frontend",
                "frontend-browser",
                "contracts",
                "images",
                "deployment-smoke",
            },
        )
        self.assertEqual(
            selected(plan.plan_for("frontend", "push")),
            {
                "lint",
                "frontend",
                "frontend-browser",
                "contracts",
                "publish",
                "deployment-smoke",
            },
        )
        for event in ("pull_request", "merge_group", "workflow_dispatch"):
            jobs = plan.plan_for("full", event)
            self.assertTrue(jobs["images"])
            self.assertFalse(jobs["publish"])
            self.assertEqual(jobs, FULL_NON_PUSH)
        push = plan.plan_for("full", "push")
        self.assertTrue(push["publish"])
        self.assertFalse(push["images"])
        # The full plan runs every suite; contracts are already inside them.
        self.assertEqual(
            selected(push),
            set(plan.JOBS) - {"contracts", "images", "static", "static-release"},
        )
        for mode in plan.SELECTED:
            self.assertEqual(set(plan.plan_for(mode, "push")), set(plan.JOBS))


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Repository(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def pull_request(self, *changes):
        """A GitHub-style merge commit of a feature branch onto main."""
        self.repo.git("checkout", "-q", "-b", "feature", self.repo.base)
        for change in changes:
            change()
        head = self.repo.commit("feature")
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "--no-edit", "feature")
        merge = self.repo.git("rev-parse", "HEAD")
        return merge, {"pull_request": {"head": {"sha": head}}}

    def test_pull_request_diffs_its_merge_commit_against_the_base(self):
        merge, event = self.pull_request(
            lambda: self.repo.write("README.md", "New guide\n")
        )
        mode, jobs, _ = self.repo.plan("pull_request", event, merge)
        self.assertEqual(mode, "docs")
        self.assertEqual(selected(jobs), {"static"})

    def test_published_documentation_runs_the_release_pipeline(self):
        self.repo.write("docs/guide.md", "Published documentation change\n")
        head = self.repo.commit("published docs")
        evidence = [{"name": "production-release", "expired": False}]
        api = self.main_push([self.run_for(1, self.repo.base)], {1: evidence})
        mode, jobs, _ = self.repo.plan(
            "push", {"ref": "refs/heads/main"}, head, api=api
        )
        self.assertEqual(mode, "published-docs")
        self.assertEqual(selected(jobs), {"static", "static-release"})

    def test_deletions_and_renames_classify_both_paths(self):
        # Renaming a backend file into the docs tree still touches the backend.
        merge, event = self.pull_request(
            lambda: self.repo.git("mv", "backend/app.py", "APP.md")
        )
        self.assertEqual(self.repo.plan("pull_request", event, merge)[0], "full")
        self.repo.git("reset", "-q", "--hard", self.repo.base)
        self.repo.git("branch", "-q", "-D", "feature")
        merge, event = self.pull_request(
            lambda: (self.repo.root / "frontend/package-lock.json").unlink()
        )
        self.assertEqual(self.repo.plan("pull_request", event, merge)[0], "full")
        self.repo.git("reset", "-q", "--hard", self.repo.base)
        self.repo.git("branch", "-q", "-D", "feature")
        merge, event = self.pull_request(
            lambda: (self.repo.root / "frontend/src/App.tsx").unlink()
        )
        self.assertEqual(self.repo.plan("pull_request", event, merge)[0], "frontend")

    def test_an_unexpected_pull_request_checkout_runs_everything(self):
        merge, event = self.pull_request(
            lambda: self.repo.write("README.md", "New guide\n")
        )
        stale = {"pull_request": {"head": {"sha": "f" * 40}}}
        mode, jobs, reason = self.repo.plan("pull_request", stale, merge)
        self.assertEqual((mode, jobs), ("full", FULL_NON_PUSH))
        self.assertIn("no trusted comparison base", reason)
        # A non-merge checkout has no first parent to compare against.
        head = event["pull_request"]["head"]["sha"]
        self.assertEqual(self.repo.plan("pull_request", event, head)[0], "full")

    def test_merge_queue_diffs_the_group_against_its_base(self):
        self.repo.write("frontend/src/App.tsx", "export const a = 1\n")
        head = self.repo.commit("queued")
        event = {"merge_group": {"base_sha": self.repo.base, "head_sha": head}}
        self.assertEqual(self.repo.plan("merge_group", event, head)[0], "frontend")
        for broken in (
            {"base_sha": "f" * 40, "head_sha": head},
            {"base_sha": self.repo.base, "head_sha": "f" * 40},
            {},
        ):
            with self.subTest(group=broken):
                mode, jobs, _ = self.repo.plan(
                    "merge_group", {"merge_group": broken}, head
                )
                self.assertEqual((mode, jobs), ("full", FULL_NON_PUSH))

    def test_manual_and_unknown_events_always_run_everything(self):
        self.repo.write("README.md", "New guide\n")
        head = self.repo.commit("docs")
        for event_name in ("workflow_dispatch", "schedule", "pull_request_target"):
            with self.subTest(event=event_name):
                self.assertEqual(
                    self.repo.plan(event_name, {}, head)[:2], ("full", FULL_NON_PUSH)
                )

    def main_push(self, runs, artifacts):
        def api(path):
            if path.startswith("actions/workflows/"):
                return {"workflow_runs": runs}
            run_id = int(path.split("/")[2])
            return {"artifacts": artifacts.get(run_id, [])}

        return api

    def run_for(self, run_id, sha, **changes):
        return {
            "id": run_id,
            "head_sha": sha,
            "event": "push",
            "head_branch": "main",
            "conclusion": "success",
            "head_repository": {"full_name": REPOSITORY},
        } | changes

    def test_main_push_compares_against_the_newest_evidenced_release(self):
        evidence = [{"name": "production-release", "expired": False}]
        self.repo.write("frontend/src/App.tsx", "export const a = 1\n")
        frontend = self.repo.commit("frontend")
        self.repo.write("README.md", "New guide\n")
        docs = self.repo.commit("docs")
        push = {"ref": "refs/heads/main"}
        # The docs-only run kept no release evidence, so the next one still
        # compares against the frontend release.
        api = self.main_push(
            [self.run_for(1, self.repo.base), self.run_for(2, frontend)],
            {1: evidence, 2: evidence},
        )
        mode, jobs, _ = self.repo.plan("push", push, docs, api=api)
        self.assertEqual(mode, "docs")
        self.assertFalse(jobs["publish"] or jobs["deployment-smoke"])
        # A cancelled or failed frontend run leaves the base at the older release.
        api = self.main_push([self.run_for(1, self.repo.base)], {1: evidence})
        mode, jobs, _ = self.repo.plan("push", push, docs, api=api)
        self.assertEqual(mode, "frontend")
        self.assertTrue(jobs["publish"] and jobs["deployment-smoke"])

    def test_main_push_without_trusted_release_evidence_runs_everything(self):
        evidence = [{"name": "production-release", "expired": False}]
        self.repo.write("README.md", "New guide\n")
        head = self.repo.commit("docs")
        push = {"ref": "refs/heads/main"}
        full = plan.plan_for("full", "push")
        self.repo.git("checkout", "-q", "--orphan", "unrelated")
        unrelated = self.repo.commit("unrelated")
        self.repo.git("checkout", "-q", "main")
        cases = {
            "no runs": self.main_push([], {}),
            "expired evidence": self.main_push(
                [self.run_for(1, self.repo.base)],
                {1: [{"name": "production-release", "expired": True}]},
            ),
            "docs-only run": self.main_push([self.run_for(1, self.repo.base)], {}),
            "foreign repository": self.main_push(
                [
                    self.run_for(
                        1, self.repo.base, head_repository={"full_name": "fork/x"}
                    )
                ],
                {1: evidence},
            ),
            "pull request run": self.main_push(
                [self.run_for(1, self.repo.base, event="pull_request")], {1: evidence}
            ),
            "failed run": self.main_push(
                [self.run_for(1, self.repo.base, conclusion="failure")], {1: evidence}
            ),
            "not an ancestor": self.main_push(
                [self.run_for(1, unrelated)], {1: evidence}
            ),
            "only this commit": self.main_push([self.run_for(1, head)], {1: evidence}),
        }
        for name, api in cases.items():
            with self.subTest(case=name):
                self.assertEqual(
                    self.repo.plan("push", push, head, api=api)[:2], ("full", full)
                )

        def broken(path):
            raise OSError("API unavailable")

        mode, jobs, reason = self.repo.plan("push", push, head, api=broken)
        self.assertEqual((mode, jobs), ("full", full))
        self.assertIn("classification failed", reason)
        # Only main pushes compare against releases.
        api = self.main_push([self.run_for(1, self.repo.base)], {1: evidence})
        self.assertEqual(
            self.repo.plan("push", {"ref": "refs/heads/other"}, head, api=api)[0],
            "full",
        )

    def test_landing_push_cannot_hide_a_cancelled_backend_change(self):
        self.repo.write("backend/app.py", "changed backend\n")
        self.repo.commit("cancelled backend run")
        self.repo.write("infra/stack/landing.html.j2", "new landing\n")
        head = self.repo.commit("landing")
        api = self.main_push(
            [self.run_for(1, self.repo.base)],
            {1: [{"name": "production-release", "expired": False}]},
        )
        self.assertEqual(
            self.repo.plan("push", {"ref": "refs/heads/main"}, head, api=api)[0],
            "full",
        )

    def test_an_unreadable_diff_runs_everything(self):
        def failing_git(*args):
            if args[0] == "diff":
                raise subprocess.CalledProcessError(128, "git diff")
            return self.repo.git(*args)

        self.repo.write("frontend/src/App.tsx", "export const a = 1\n")
        head = self.repo.commit("frontend")
        event = {"merge_group": {"base_sha": self.repo.base, "head_sha": head}}
        with (
            patch.object(plan, "git", failing_git),
            patch.object(plan, "is_ancestor", self.repo.ancestor),
        ):
            mode, jobs, _ = plan.plan("merge_group", event, head, REPOSITORY)
        self.assertEqual((mode, jobs), ("full", FULL_NON_PUSH))

    def test_the_planner_writes_its_plan_for_the_workflow(self):
        self.repo.write("README.md", "New guide\n")
        head = self.repo.commit("docs")
        event = Path(self.directory.name) / "event.json"
        event.write_text(
            json.dumps({"merge_group": {"base_sha": self.repo.base, "head_sha": head}})
        )
        output = Path(self.directory.name) / "output"
        environment = {
            "GITHUB_EVENT_NAME": "merge_group",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_SHA": head,
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_OUTPUT": str(output),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }
        subprocess.run(
            ["python3", SCRIPTS / "ci_plan.py"],
            cwd=self.repo.root,
            env=environment,
            check=True,
            capture_output=True,
        )
        lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(lines["mode"], "docs")
        self.assertEqual(selected(json.loads(lines["plan"])), {"static"})
        # A checkout other than the event's commit is never trusted.
        output.unlink()
        environment["GITHUB_SHA"] = self.repo.base
        subprocess.run(
            ["python3", SCRIPTS / "ci_plan.py"],
            cwd=self.repo.root,
            env=environment,
            check=True,
            capture_output=True,
        )
        lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(lines["mode"], "full")


PULL_REQUEST_7 = {"pull_request": {"number": 7}}


class PullRequestDeferralTests(unittest.TestCase):
    """Pull requests leave the heavy suites to the merge queue unless asked."""

    @staticmethod
    def labels(*names):
        def api(path):
            assert path.startswith("issues/7/labels"), path
            return [{"name": name} for name in names]

        return api

    def defer(self, event_name, jobs, api):
        return plan.defer_heavy(event_name, PULL_REQUEST_7, "full", jobs, "r", api=api)

    def test_a_pull_request_runs_only_the_fast_suites(self):
        mode, jobs, reason = self.defer(
            "pull_request", FULL_NON_PUSH, self.labels("enhancement")
        )
        self.assertEqual(mode, "full")
        self.assertEqual(selected(jobs), selected(FULL_NON_PUSH) - plan.HEAVY)
        self.assertEqual(
            selected(jobs), {"lint", "backend", "frontend", "frontend-browser"}
        )
        self.assertIn("merge queue", reason)
        frontend = plan.plan_for("frontend", "pull_request")
        _, jobs, _ = self.defer("pull_request", frontend, self.labels())
        self.assertEqual(
            selected(jobs), {"lint", "frontend", "frontend-browser", "contracts"}
        )

    def test_the_full_ci_label_or_unreadable_labels_run_the_whole_plan(self):
        def broken(path):
            raise OSError("API unavailable")

        for api in (self.labels("full-ci", "enhancement"), broken):
            with self.subTest(api=api):
                _, jobs, _ = self.defer("pull_request", FULL_NON_PUSH, api)
                self.assertEqual(jobs, FULL_NON_PUSH)

    def test_the_merge_queue_main_and_manual_runs_keep_the_whole_plan(self):
        def unused(path):
            raise AssertionError("only pull requests read labels")

        for event_name in ("merge_group", "push", "workflow_dispatch"):
            with self.subTest(event=event_name):
                jobs = plan.plan_for("full", event_name)
                self.assertEqual(self.defer(event_name, jobs, unused)[1], jobs)

    def test_a_plan_without_heavy_suites_reads_no_labels(self):
        def unused(path):
            raise AssertionError("nothing to defer")

        docs = plan.plan_for("docs", "pull_request")
        self.assertEqual(self.defer("pull_request", docs, unused)[1], docs)


class GateTests(unittest.TestCase):
    def needs(self, jobs, **results):
        needs = {"changes": {"result": "success"}}
        for job, run in jobs.items():
            needs[job] = {"result": results.get(job, "success" if run else "skipped")}
        return needs

    def test_planned_success_and_planned_skips_pass(self):
        for mode in plan.SELECTED:
            for event in ("pull_request", "push"):
                jobs = plan.plan_for(mode, event)
                with self.subTest(mode=mode, event=event):
                    self.assertEqual(
                        gate.problems(self.needs(jobs), json.dumps(jobs)), []
                    )

    def test_any_other_result_fails(self):
        jobs = plan.plan_for("frontend", "pull_request")
        for job, result in (
            ("deployment-smoke", "skipped"),
            ("deployment-smoke", "cancelled"),
            ("deployment-smoke", "failure"),
            ("images", "skipped"),
            # A job the plan left out may not run, so it cannot hide a change.
            ("backend", "success"),
            ("backend", "failure"),
            ("radar", "cancelled"),
        ):
            with self.subTest(job=job, result=result):
                problems = gate.problems(
                    self.needs(jobs, **{job: result}), json.dumps(jobs)
                )
                self.assertEqual(len(problems), 1)
                self.assertIn(job, problems[0])

    def test_a_missing_or_failed_plan_fails_closed(self):
        jobs = plan.plan_for("docs", "pull_request")
        for result in ("failure", "cancelled", "skipped"):
            with self.subTest(planner=result):
                needs = self.needs(jobs) | {"changes": {"result": result}}
                self.assertEqual(
                    gate.problems(needs, json.dumps(jobs)),
                    [f"changes {result}, expected success"],
                )
        for document in (None, "", "{", "[]", '{"lint": "yes"}', '{"lint": 1}'):
            with self.subTest(plan=document):
                self.assertTrue(gate.problems(self.needs(jobs), document))

    def test_every_gated_job_must_be_planned_and_every_planned_job_gated(self):
        jobs = plan.plan_for("full", "pull_request")
        needs = self.needs(jobs) | {"new-job": {"result": "skipped"}}
        self.assertEqual(
            gate.problems(needs, json.dumps(jobs)), ["new-job is not in the CI plan"]
        )
        needs = self.needs(jobs)
        del needs["radar"]
        self.assertEqual(
            gate.problems(needs, json.dumps(jobs)), ["radar is planned but not gated"]
        )

    def test_the_gate_exits_non_zero_on_any_problem(self):
        jobs = plan.plan_for("full", "pull_request")
        for needs, code in (
            (self.needs(jobs), 0),
            (self.needs(jobs, backend="failure"), 1),
        ):
            with self.subTest(code=code):
                result = subprocess.run(
                    ["python3", SCRIPTS / "ci_gate.py"],
                    env={"NEEDS": json.dumps(needs), "PLAN": json.dumps(jobs)},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, code, result.stdout)


class ContractCoverageTests(unittest.TestCase):
    """Narrow plans skip suites; any test reading their changed inputs must still run."""

    READS = re.compile(
        r"""(?:/\s*|["'])(?:docs|frontend)/|/\s*["'](?:docs|frontend)["']"""
    )

    def contract_step(self):
        workflow = yaml.load(
            (ROOT.parent / ".github/workflows/ci.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["contracts"]["steps"]
        return {step["name"]: step for step in steps}

    def test_backend_tests_reading_docs_or_frontend_sources_are_contracts(self):
        backend = ROOT.parent / "backend/tests"
        readers = {
            path.relative_to(backend).parts[0]
            for path in backend.rglob("*.py")
            if self.READS.search(path.read_text())
        }
        self.assertEqual(readers, {"contracts"})
        self.assertIn(
            "pytest backend/tests/contracts",
            self.contract_step()["Test documentation and source contracts"]["run"],
        )

    def test_infrastructure_tests_reading_repository_docs_are_contracts(self):
        pattern = re.compile(
            r"""(?:REPOSITORY|ROOT\.parent|PROJECT)\s*/\s*["'](?:docs|frontend)"""
        )
        readers = {
            path.stem
            for path in (ROOT / "tests").glob("test_*.py")
            if pattern.search(path.read_text())
        }
        run = self.contract_step()["Test infrastructure documentation contracts"]["run"]
        self.assertTrue(readers)
        for module in readers:
            self.assertIn(module, run)


if __name__ == "__main__":
    unittest.main()
