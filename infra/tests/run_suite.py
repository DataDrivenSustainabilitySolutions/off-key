"""Run every infrastructure test once, spread over this machine's processors.

Most of the suite's time is real Ansible plays and their retry delays, which
do not share state. Each test runs in a worker process of its own; a class or
module with a shared fixture stays whole, so that fixture still runs once.
`python -m unittest discover -s tests` remains the serial equivalent.
"""

import argparse
import io
import os
import sys
import time
import unittest
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

TESTS = Path(__file__).resolve().parent
# Workers import the test modules by the names discovery gave them.
sys.path.insert(0, str(TESTS))
SHOWN = 10


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def unit(case):
    """Name what must run together with this test: itself, its class or its module."""
    cls = type(case)
    module = sys.modules[cls.__module__]
    if hasattr(module, "setUpModule") or hasattr(module, "tearDownModule"):
        return cls.__module__
    inherited = unittest.TestCase
    if (
        cls.setUpClass.__func__ is not inherited.setUpClass.__func__
        or cls.tearDownClass.__func__ is not inherited.tearDownClass.__func__
    ):
        return f"{cls.__module__}.{cls.__qualname__}"
    return case.id()


def plan(discovered):
    """Group the tests into units, the shared fixtures first: they run longest."""
    units = {}
    for case in discovered:
        units.setdefault(unit(case), []).append(case.id())
    return sorted(units.items(), key=lambda item: len(item[1]) == 1)


def run_unit(names):
    stream = io.StringIO()
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return (
        stream.getvalue(),
        result.testsRun,
        len(result.skipped),
        result.wasSuccessful(),
        time.monotonic() - started,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    loader = unittest.TestLoader()
    discovered = list(cases(loader.discover(str(TESTS))))
    if loader.errors:
        print(*loader.errors, sep="\n")
        return 1
    started = time.monotonic()
    ran = skipped = 0
    failed, durations = [], []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(run_unit, names): name for name, names in plan(discovered)
        }
        for future in as_completed(futures):
            output, tests, skips, passed, seconds = future.result()
            name = futures[future]
            ran += tests
            skipped += skips
            durations.append((seconds, name))
            if passed:
                print(f"ok {name} ({tests} tests, {seconds:.1f}s)", flush=True)
            else:
                failed.append(name)
                print(f"FAILED {name}\n{output}", flush=True)
    print(f"\nSlowest of {len(durations)} units:")
    for seconds, name in sorted(durations, reverse=True)[:SHOWN]:
        print(f"{seconds:7.1f}s  {name}")
    print(
        f"\nRan {ran} tests ({skipped} skipped) in {time.monotonic() - started:.0f}s "
        f"with {args.jobs} processes."
    )
    if ran != len(discovered):
        print(f"FAILED: discovery found {len(discovered)} tests, {ran} ran.")
        return 1
    if failed:
        print("FAILED: " + ", ".join(sorted(failed)))
        return 1
    return 0 if ran else 1


if __name__ == "__main__":
    sys.exit(main())
