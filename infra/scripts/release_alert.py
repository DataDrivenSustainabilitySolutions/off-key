"""Keep one open GitHub issue per release target while its last release failed.

A failed or refused release must not wait unseen until someone opens the workflow
log. The deploy job records each target's public outcome: the lines it already
prints for a failure, or that the release completed. A failure opens the target's
issue, or comments on it when one is open, and the next completed release of that
target closes it. The issue holds only those public lines, never private output.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

TITLES = {
    "production": "Production release needs attention",
    "demo": "Public demo release needs attention",
}
REFUSED = "Require recovery of a different interrupted release"
RECOVERY = "docs/operations/recovery.md"


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, timeout=60
    ).stdout


def open_issue(title: str, gh=gh) -> str | None:
    issues = json.loads(
        gh(
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,title",
        )
    )
    return next(
        (str(issue["number"]) for issue in issues if issue["title"] == title), None
    )


def failure_report(target: str, lines: list[str], revision: str, run_url: str) -> str:
    report = "\n".join(lines) or "The release job failed before Ansible reported."
    if any(REFUSED in line for line in lines):
        step = (
            "An earlier release is still interrupted, so this one was refused. "
            "Retry the interrupted release first; its SHA is in the first report."
        )
    else:
        option = " with **demo_only** checked" if target == "demo" else ""
        step = (
            "To retry, run **Deploy Production** on `main` with revision "
            f"`{revision}`{option}. If the retry fails the same way, read the "
            f"release log kept on the manager and follow [{RECOVERY}]({RECOVERY})."
        )
    return f"The {target} release of `{revision}` failed in {run_url}.\n\n```\n{report}\n```\n\n{step}"


def alert(target, failure, released, revision, run_url, actor="", gh=gh):
    """Open, update or close the target's issue; report what was done."""
    title = TITLES[target]
    number = open_issue(title, gh=gh)
    if failure is not None:
        body = failure_report(target, failure, revision, run_url)
        if number:
            gh("issue", "comment", number, "--body", body)
            return f"Commented on the open {target} release issue #{number}."
        if actor and not actor.endswith("[bot]"):
            body = f"@{actor} {body}"
        gh("issue", "create", "--title", title, "--body", body)
        return f"Opened an issue: {title}."
    if released and number:
        gh(
            "issue",
            "close",
            number,
            "--comment",
            f"The {target} release of `{revision}` completed in {run_url}.",
        )
        return f"Closed the {target} release issue #{number}."
    return None


def outcomes(directory: Path, job_failed: bool):
    """Each target's failure lines or completion; a silent failure is production's."""
    results = {}
    for target in TITLES:
        failed, released = (
            directory / f"{target}.failed",
            directory / f"{target}.released",
        )
        if failed.is_file():
            results[target] = (failed.read_text().splitlines(), False)
        elif released.is_file():
            results[target] = (None, True)
    if job_failed and not any(failure is not None for failure, _ in results.values()):
        results["production"] = ([], False)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outcomes", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--job-status", required=True)
    args = parser.parse_args()
    run_url = (
        f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
        f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    )
    actor = os.environ.get("GITHUB_TRIGGERING_ACTOR", "")
    for target, (failure, released) in outcomes(
        args.outcomes, args.job_status != "success"
    ).items():
        if note := alert(target, failure, released, args.revision, run_url, actor):
            print(note)


if __name__ == "__main__":
    main()
