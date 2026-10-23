"""Fail a CI lane whose JUnit report is empty or contains skipped tests."""

import sys
import xml.etree.ElementTree as ET


def main(report: str, lane: str) -> None:
    cases = ET.parse(report).findall(".//testcase")
    if not cases:
        raise SystemExit(f"{lane} executed no tests")
    skipped = [
        f"{case.get('classname')}::{case.get('name')}"
        for case in cases
        if case.find("skipped") is not None
    ]
    if skipped:
        raise SystemExit(f"Skipped required {lane} tests: " + ", ".join(skipped))
    print(f"Verified {len(cases)} {lane} tests with zero skips")


if __name__ == "__main__":
    main(*sys.argv[1:])
