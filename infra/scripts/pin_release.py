#!/usr/bin/env python3
"""Resolve a tested, published main release to immutable production images."""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RELEASE = (
    Path(__file__).resolve().parents[1]
    / "ansible/inventories/prod/group_vars/all/release.yml"
)
APPLICATION_IMAGES = {
    "api",
    "frontend",
    "tactic",
    "mqtt_proxy",
    "mqtt_radar",
    "db_sync",
}
REPOSITORY = "DataDrivenSustainabilitySolutions/off-key"
REQUIRED_WORKFLOWS = (
    "ci.yml",
    "deployment-smoke.yml",
    "docker-publish.yml",
    "collection-integration.yml",
    "infra-validation.yml",
)


def github(path):
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/{path}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def main_runs(workflow, revision=None):
    query = "branch=main&event=push&per_page=100"
    if revision:
        query += f"&head_sha={revision}"
    runs = github(f"actions/workflows/{workflow}/runs?{query}")["workflow_runs"]
    latest = {}
    for run in sorted(
        runs, key=lambda run: (run["id"], run["run_attempt"]), reverse=True
    ):
        if run["head_branch"] == "main" and run["event"] == "push":
            latest.setdefault(run["head_sha"], run)
    return latest


def select_revision(requested):
    if requested != "latest" and not re.fullmatch(r"[0-9a-f]{40}", requested):
        raise ValueError("revision must be 'latest' or a full lowercase commit SHA")
    candidates = (
        [commit["sha"] for commit in github("commits?sha=main&per_page=100")]
        if requested == "latest"
        else [requested]
    )
    if requested != "latest":
        comparison = github(f"compare/{requested}...main")
        if comparison["status"] not in {"ahead", "identical"}:
            raise ValueError("The target revision must belong to main history")
    successful = []
    for workflow in REQUIRED_WORKFLOWS:
        # Do not accept an older success if a newer run failed or is still running.
        latest_runs = main_runs(workflow, None if requested == "latest" else requested)
        successful.append(
            {
                sha
                for sha, run in latest_runs.items()
                if run["status"] == "completed" and run["conclusion"] == "success"
            }
        )
    for revision in candidates:
        if all(revision in revisions for revisions in successful):
            if requested == "latest" and revision != candidates[0]:
                print(
                    f"Main {candidates[0]} is not eligible; selecting {revision}.",
                    file=sys.stderr,
                )
            return revision
    scope = "the latest 100 main commits/runs" if requested == "latest" else requested
    raise ValueError(
        f"No eligible release in {scope}: Every required release workflow must succeed for the same commit."
    )


def inspect(reference, field):
    result = subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{json ." + field + "}}",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def pin(reference, revision=None):
    reference = reference.split("@", 1)[0]
    if revision:
        reference = reference.rsplit(":", 1)[0] + ":sha-" + revision[:7]
    digest = inspect(reference, "Manifest")["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid registry digest for {reference}")
    pinned = f"{reference}@{digest}"
    if revision:
        # Read the label by digest, so a moving tag cannot race this check.
        require_image_revision(pinned, revision)
    return pinned


def require_image_revision(reference, revision):
    image = inspect(reference, "Image")
    if image.get("architecture") is None:
        image = image["linux/amd64"]
    actual = (
        image.get("config", {})
        .get("Labels", {})
        .get("org.opencontainers.image.revision")
    )
    if actual != revision:
        raise ValueError(f"{reference} belongs to {actual}, not {revision}")


def tested_release(revision):
    run = main_runs("deployment-smoke.yml", revision).get(revision)
    if not run or run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError("No successful production rehearsal for this main revision")
    with tempfile.TemporaryDirectory(prefix="offkey-tested-release-") as directory:
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                str(run["id"]),
                "--repo",
                REPOSITORY,
                "--name",
                "production-release",
                "--dir",
                directory,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        document = json.loads((Path(directory) / "production-release.json").read_text())
    result = document["release"]
    expected = json.loads(RELEASE.read_text())["release"]
    if (
        result["application_revision"] != revision
        or result["images"].keys() != expected["images"].keys()
    ):
        raise ValueError(
            "The tested release manifest does not match the selected revision"
        )
    for name, reference in result["images"].items():
        repository = expected["images"][name].split("@", 1)[0].rsplit(":", 1)[0]
        if not re.fullmatch(
            re.escape(repository) + r"(?::[^@]+)?@sha256:[0-9a-f]{64}", reference
        ):
            raise ValueError(f"Invalid tested image for {name}")
        if name in APPLICATION_IMAGES:
            require_image_revision(reference, revision)
        elif reference != expected["images"][name]:
            raise ValueError(
                f"The tested platform image for {name} differs from this checkout"
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "revision",
        nargs="?",
        default="latest",
        help="Full application commit SHA, or latest (default)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the resolved release without changing the manifest",
    )
    args = parser.parse_args()
    revision = select_revision(args.revision)
    document = json.loads(RELEASE.read_text())
    release = document["release"] = tested_release(revision)
    release["application_revision"] = revision
    if args.stdout:
        print(json.dumps(document))
        return
    # Resolve every image before replacing the file; a failed lookup leaves it intact.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=RELEASE.parent, delete=False
    ) as output:
        output.write(json.dumps(document, indent=2) + "\n")
    Path(output.name).replace(RELEASE)
    print(f"Updated {RELEASE}; review and commit the release before deploying.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Release resolution failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        sys.exit(1)
