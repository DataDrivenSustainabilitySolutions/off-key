"""Stable image revisions, proven against every committed build input.

Each CI run still builds, attests and rehearses its images. Revision labels and
build arguments change only when that image's inputs change, allowing BuildKit
and the registry to retain an unchanged image digest. Workflow/build-tool edits
invalidate every image. Missing history disables this optimization.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
COMMON = (".github", "infra/scripts", "infra/tests/rehearsal_releases.py")
INPUTS = {
    "api": ("backend",),
    "tactic": ("backend",),
    "mqtt_proxy": ("backend",),
    "mqtt_radar": ("backend",),
    "db_sync": ("backend",),
    "forecast": ("backend",),
    "frontend": ("frontend",),
    "docs": ("docs", "dev/docs", "requirements-docs.txt", "zensical.toml"),
}
NAMES = {
    "api-gateway": "api",
    "tactic-middleware": "tactic",
    "mqtt-proxy": "mqtt_proxy",
    "mqtt-radar": "mqtt_radar",
    "db-sync": "db_sync",
}


def git(*args, project=PROJECT):
    return subprocess.run(
        ["git", *args],
        cwd=project,
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout.strip()


def source_revision(name, revision, project=PROJECT):
    name = name.removeprefix("off-key-")
    name = NAMES.get(name, name)
    paths = (*COMMON, *INPUTS[name])
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Image source requires a full commit SHA")
    if git("rev-parse", "--is-shallow-repository", project=project) == "true":
        return revision
    candidate = git(
        "log",
        "--first-parent",
        "-1",
        "--format=%H",
        revision,
        "--",
        *paths,
        project=project,
    )
    if not candidate:
        return revision
    # Do not rely on history simplification: verify the exact trees, including
    # deletes, renames and merge conflict resolutions, before retaining a label.
    if git(
        "diff",
        "--name-only",
        "--no-renames",
        candidate,
        revision,
        "--",
        *paths,
        project=project,
    ):
        return revision
    return candidate


def revisions(revision, project=PROJECT):
    return {name: source_revision(name, revision, project) for name in INPUTS}


def expected_revisions(release, project=PROJECT):
    revision = release["application_revision"]
    declared = release.get("image_revisions")
    if declared is None:
        # Existing immutable releases keep their original all-images-at-one-SHA
        # contract, including explicitly selected rollback releases.
        return dict.fromkeys(INPUTS, revision)
    expected = revisions(revision, project)
    if declared != expected:
        raise ValueError(
            "Image source revisions do not match the release's build inputs"
        )
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision")
    parser.add_argument("--service")
    args = parser.parse_args()
    print(
        source_revision(args.service, args.revision)
        if args.service
        else json.dumps(revisions(args.revision), sort_keys=True)
    )


if __name__ == "__main__":
    main()
