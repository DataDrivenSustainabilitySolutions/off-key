"""Summarize where a private Ansible log spent its time, naming tasks only.

With the profile_tasks callback, each task header is followed by a stamp that
holds the previous task's duration, and the run ends with its slowest tasks.
Task names come from this public repository, like the names failed_tasks.py
prints, so the totals and the slowest names can go to the public workflow log
while every task result stays private.
"""

import argparse
import re
import statistics
from pathlib import Path

# Wednesday 28 October 2026  10:38:51 +0000 (0:00:02.316)       0:00:04.139 *****
STAMP = re.compile(
    r"\((?P<previous>\d+:\d{2}:\d{2}\.\d+)\)\s+(?P<total>\d+:\d{2}:\d{2}\.\d+) \*+\s*$"
)
# stack_deploy : Wait for all stack services to converge ------------- 45.67s
SLOW = re.compile(r"^(?P<name>.+?) -+ (?P<seconds>\d+\.\d+)s\s*$")
# Tasks this quick are mostly connection setup and module transfer.
SHORT = 2.0
SHOWN = 15


def seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def timings(lines: list[str]) -> tuple[float, list[float], list[tuple[str, float]]]:
    """Return the run's elapsed time, every task's duration and the slowest tasks."""
    total, durations, slowest, recap = 0.0, [], [], False
    for line in lines:
        if match := STAMP.search(line):
            durations.append(seconds(match["previous"]))
            total = seconds(match["total"])
        elif line.startswith("TASKS RECAP"):
            recap = True
        elif recap and (match := SLOW.match(line)):
            slowest.append((match["name"], float(match["seconds"])))
    # The first stamp measures the time before the first task.
    return total, durations[1:], slowest


def clock(value: float) -> str:
    minutes, rest = divmod(round(value), 60)
    return f"{minutes}m{rest:02d}s"


def summary(lines: list[str]) -> list[str]:
    total, durations, slowest = timings(lines)
    if not durations:
        return ["No Ansible task timings were recorded."]
    short = [duration for duration in durations if duration < SHORT]
    overview = (
        f"Ansible ran {len(durations)} tasks in {clock(total)}; "
        f"median {statistics.median(durations):.1f}s per task, "
        f"{len(short)} tasks under {SHORT:.0f}s took {clock(sum(short))} together."
    )
    report = [overview, "Slowest Ansible tasks:"]
    report += [f"{duration:7.1f}s  {name}" for name, duration in slowest[:SHOWN]]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    if not args.log.is_file():
        print("No Ansible log was written.")
        return
    print("\n".join(summary(args.log.read_text(errors="replace").splitlines())))


if __name__ == "__main__":
    main()
