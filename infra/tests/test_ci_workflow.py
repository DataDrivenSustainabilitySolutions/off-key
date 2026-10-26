"""CI is one workflow whose single, stable gate job stands for every check."""

import unittest

import yaml
from support import ROOT

WORKFLOWS = ROOT.parent / ".github/workflows"
GATE = "ci-gate"


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


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

    def test_the_gate_expects_exactly_one_image_job_per_event(self):
        step = self.jobs[GATE]["steps"][0]
        self.assertEqual(step["env"]["NEEDS"], "${{ toJSON(needs) }}")
        self.assertEqual(
            step["env"]["NOT_RUN"],
            "${{ github.event_name == 'push' && 'images' || 'publish' }}",
        )
        self.assertEqual(self.jobs["publish"]["if"], "github.event_name == 'push'")
        self.assertEqual(self.jobs["images"]["if"], "github.event_name != 'push'")
        self.assertEqual(self.jobs["publish"]["with"]["publish"], "true")
        self.assertEqual(self.jobs["images"]["with"]["publish"], "false")

    def test_main_rehearses_the_images_this_run_published(self):
        smoke = self.jobs["deployment-smoke"]
        self.assertEqual(needs(smoke), ["publish"])
        self.assertIn("needs.publish.result == 'success'", smoke["if"])
        # Only events that never publish may run without a successful publish job.
        self.assertIn(
            "needs.publish.result == 'skipped' && github.event_name != 'push'",
            smoke["if"],
        )
        self.assertNotIn("actions", smoke["permissions"])

    def test_only_the_publish_job_can_write_packages(self):
        self.assertEqual(workflow("ci.yml")["permissions"], {"contents": "read"})
        writers = [
            name
            for name, job in self.jobs.items()
            if job.get("permissions", {}).get("packages") == "write"
        ]
        self.assertEqual(writers, ["publish"])

    def test_a_manual_run_cannot_cancel_the_releasing_push_run(self):
        group = workflow("ci.yml")["concurrency"]["group"]
        self.assertIn("${{ github.event_name }}", group)


if __name__ == "__main__":
    unittest.main()
