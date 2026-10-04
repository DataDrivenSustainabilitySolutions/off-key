"""Select a trusted, fully tested commit; a workflow_run event alone is insufficient."""

import argparse
import json
import os
from pathlib import Path

from pin_release import REPOSITORY, github, select_revision


def candidate(event: dict, event_name: str) -> str:
    if event_name == "workflow_dispatch":
        return event["inputs"]["revision"]
    run = event.get("workflow_run", {})
    if (
        event_name != "workflow_run"
        or run.get("event") != "push"
        or run.get("head_branch") != "main"
        or run.get("head_repository", {}).get("full_name") != REPOSITORY
        or run.get("conclusion") != "success"
    ):
        raise ValueError("Only trusted main pushes can trigger production deployment")
    return run["head_sha"]


def ready(revision: str, automatic: bool) -> bool:
    if automatic and github("commits/main")["sha"] != revision:
        return False
    try:
        return select_revision(revision) == revision
    except ValueError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision")
    parser.add_argument("--automatic", action="store_true")
    args = parser.parse_args()
    automatic = args.automatic or os.environ["GITHUB_EVENT_NAME"] == "workflow_run"
    revision = args.revision or candidate(
        json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()),
        os.environ["GITHUB_EVENT_NAME"],
    )
    eligible = ready(revision, automatic)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(
            f"revision={revision if eligible else ''}\nready={str(eligible).lower()}\n"
        )
    print(
        "Release eligible"
        if eligible
        else "Release pending, superseded or failed; no deployment"
    )
    if not eligible and not automatic:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
