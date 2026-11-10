"""The parallel runner runs every discovered test once and reports any failure."""

import sys
import tempfile
import unittest
from pathlib import Path

import run_suite

FAILING = """
import unittest


class Sample(unittest.TestCase):
    def test_passes(self):
        pass

    def test_fails(self):
        for value in (1, 2):
            with self.subTest(value=value):
                self.assertEqual(value, 1)
"""


class RunSuiteTests(unittest.TestCase):
    def test_every_test_is_planned_once_and_shared_fixtures_stay_whole(self):
        discovered = [
            case.id()
            for case in run_suite.cases(
                unittest.TestLoader().discover(str(run_suite.TESTS))
            )
        ]
        self.assertIn(self.id(), discovered)
        units = dict(
            run_suite.plan(
                run_suite.cases(unittest.TestLoader().discover(str(run_suite.TESTS)))
            )
        )
        planned = [name for names in units.values() for name in names]
        self.assertEqual(sorted(planned), sorted(discovered))
        # The rendered production stack is one class fixture; it must not be
        # rebuilt for each of its tests, so the class runs first and whole.
        fixture = "test_deployment.DeploymentTests"
        self.assertEqual(next(iter(units)), fixture)
        self.assertGreater(len(units[fixture]), 1)
        self.assertTrue(all(name.startswith(fixture + ".") for name in units[fixture]))
        for name, names in units.items():
            if name != fixture:
                self.assertEqual(names, [name])

    def test_a_failing_subtest_fails_its_unit_and_keeps_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "sample_failing_suite.py").write_text(FAILING)
            sys.path.insert(0, directory)
            try:
                output, ran, skipped, passed, _ = run_suite.run_unit(
                    ["sample_failing_suite.Sample.test_fails"]
                )
                self.assertFalse(passed)
                self.assertEqual((ran, skipped), (1, 0))
                self.assertIn("AssertionError: 2 != 1", output)
                _, ran, _, passed, _ = run_suite.run_unit(
                    ["sample_failing_suite.Sample.test_passes"]
                )
                self.assertTrue(passed)
                self.assertEqual(ran, 1)
            finally:
                sys.path.remove(directory)
                sys.modules.pop("sample_failing_suite", None)


if __name__ == "__main__":
    unittest.main()
