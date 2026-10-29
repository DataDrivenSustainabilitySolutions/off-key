"""Name the Ansible tasks that failed in a private log, and nothing else.

Deployment logs stay private because task results can hold configuration. Task
names come from this public repository, so printing only them makes a failed
release attributable in the public workflow log without exposing any output.
"""

import argparse
import re
from pathlib import Path

from check_application import CHECKS, PUBLIC

TASK = re.compile(r"^(?:TASK|RUNNING HANDLER) \[(?P<name>.+)\] \**$")
FAILURE = re.compile(r"^(?:fatal|failed): \[[^\]]+\]")


def ignored(lines: list[str], index: int) -> bool:
    """An ignore_errors failure prints its result, then this marker, and continues."""
    for line in lines[index + 1 :]:
        if line.startswith((" ", "\t")) or line in {"{", "}"}:
            continue
        return line.startswith("...ignoring")
    return False


def failed_tasks(lines: list[str]) -> list[str]:
    """Return each task that failed or was unreachable, in order, once."""
    current, failed = None, []
    for index, line in enumerate(lines):
        if match := TASK.match(line):
            current = match["name"]
        elif (
            FAILURE.match(line)
            and current
            and current not in failed
            and not ignored(lines, index)
        ):
            failed.append(current)
    return failed


def failed_check(report: Path | None) -> str | None:
    """The readiness check a release recorded, if it is one of the fixed names."""
    if report is None or not report.is_file():
        return None
    line = report.read_text(errors="replace").strip()
    check = line.removeprefix(PUBLIC)
    return line if line != check and check in CHECKS else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument(
        "--readiness", type=Path, help="the release's failed readiness check record"
    )
    args = parser.parse_args()
    if not args.log.is_file():
        print("No Ansible log was written.")
        return
    tasks = failed_tasks(args.log.read_text(errors="replace").splitlines())
    for task in tasks:
        print(f"Failed Ansible task: {task}")
    if not tasks:
        print("No failed Ansible task was recorded; the command failed outside a task.")
    if check := failed_check(args.readiness):
        print(check)


if __name__ == "__main__":
    main()
