"""Name the Ansible tasks that failed in a private log, and nothing else.

Deployment logs stay private because task results can hold configuration. Task
names come from this public repository, so printing only them makes a failed
release attributable in the public workflow log without exposing any output.
A failure whose result matches a known connection or privilege cause also prints
that cause's fixed description, never the result text itself.
"""

import argparse
import re
from pathlib import Path

from check_application import CHECKS, PUBLIC

TASK = re.compile(r"^(?:TASK|RUNNING HANDLER) \[(?P<name>.+)\] \**$")
FAILURE = re.compile(r"^(?:fatal|failed): \[[^\]]+\]")
# Known causes, matched case-insensitively in a failure's result; only the fixed
# description on the right is printed. The first match wins.
CAUSES = (
    ("host key verification failed", "SSH host key is not in the known hosts"),
    ("remote host identification has changed", "SSH host key changed"),
    ("permission denied (publickey", "SSH key refused by the host"),
    ("too many authentication failures", "SSH key refused by the host"),
    ("could not resolve hostname", "host name does not resolve"),
    ("no route to host", "no route to the host"),
    ("connection refused", "SSH port refused the connection"),
    ("timed out", "connection timed out"),
    ("missing sudo password", "sudo needs a password"),
    ("incorrect sudo password", "sudo needs a password"),
    ("a password is required", "sudo needs a password"),
    ("privilege escalation", "sudo did not complete"),
    ("cannot connect to the docker daemon", "Docker is not reachable"),
    (
        "permission denied while trying to connect to the docker",
        "Docker is not reachable",
    ),
    ("this node is not a swarm manager", "host is not a Swarm manager"),
    ("is undefined", "a variable is undefined"),
)


def ignored(lines: list[str], index: int) -> bool:
    """An ignore_errors failure prints its result, then this marker, and continues."""
    for line in lines[index + 1 :]:
        if line.startswith((" ", "\t")) or line in {"{", "}"}:
            continue
        return line.startswith("...ignoring")
    return False


def cause(lines: list[str], index: int) -> str | None:
    """The fixed description of a failure's known cause, from its result lines."""
    result = [lines[index]]
    for line in lines[index + 1 :]:
        if not (line.startswith((" ", "\t")) or line in {"{", "}"}):
            break
        result.append(line)
    text = "\n".join(result).lower()
    reason = next(
        (description for marker, description in CAUSES if marker in text), None
    )
    if "unreachable!" in lines[index].lower():
        return f"host unreachable: {reason}" if reason else "host unreachable"
    return reason


def failures(lines: list[str]) -> list[tuple[str, str | None]]:
    """Return each task that failed or was unreachable, in order, once, with its cause."""
    current, failed = None, {}
    for index, line in enumerate(lines):
        if match := TASK.match(line):
            current = match["name"]
        elif (
            FAILURE.match(line)
            and current
            and current not in failed
            and not ignored(lines, index)
        ):
            failed[current] = cause(lines, index)
    return list(failed.items())


def failed_tasks(lines: list[str]) -> list[str]:
    """Return each task that failed or was unreachable, in order, once."""
    return [task for task, _ in failures(lines)]


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
    tasks = failures(args.log.read_text(errors="replace").splitlines())
    for task, reason in tasks:
        print(f"Failed Ansible task: {task}" + (f" ({reason})" if reason else ""))
    if not tasks:
        print("No failed Ansible task was recorded; the command failed outside a task.")
    if check := failed_check(args.readiness):
        print(check)


if __name__ == "__main__":
    main()
