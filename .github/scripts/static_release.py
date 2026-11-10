"""Carry tested images forward only across allowlisted static content changes.

The docs image, when changed, comes from this run's checked archive. Every other
digest is inherited from successful main CI and its committed inputs must match.
This keeps normal production release selection and deployment checks intact.
"""

import argparse
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import ci_plan

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/scripts"))
import image_sources
import pin_release


def carried_release(previous, head, paths, sources, docs_image=None):
    if ci_plan.mode_for(paths) not in ci_plan.STATIC_RELEASE_MODES:
        raise ValueError("Only static content may inherit release evidence")
    old_sources = image_sources.expected_revisions(previous)
    for name in image_sources.INPUTS:
        if name == "docs" and docs_image:
            continue
        if old_sources[name] != sources[name]:
            raise ValueError(f"Cannot reuse changed image: {name}")
    result = deepcopy(previous)
    result.update(application_revision=head, image_revisions=sources)
    if docs_image:
        result["images"]["docs"] = docs_image
    return result


def docker(*args):
    return subprocess.run(
        ["docker", *args], check=True, text=True, capture_output=True, timeout=300
    ).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-image")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        os.environ["GITHUB_EVENT_NAME"] != "push"
        or os.environ["GITHUB_REF"] != "refs/heads/main"
    ):
        raise ValueError("Static release evidence is only produced on main pushes")
    head = os.environ["GITHUB_SHA"]
    if ci_plan.git("rev-parse", "HEAD").strip() != head:
        raise ValueError("Unexpected checkout")
    base = ci_plan.evidenced_base(head, os.environ["GITHUB_REPOSITORY"])
    if not base:
        raise ValueError("No successful ancestor with release evidence")
    previous = pin_release.tested_release(base)
    sources = image_sources.revisions(head)
    paths = ci_plan.changed_paths(base, head)
    # Validate the complete diff and all reused inputs before any registry write.
    release = carried_release(previous, head, paths, sources, args.docs_image)
    if args.docs_image:
        local = json.loads(docker("image", "inspect", args.docs_image))[0]
        if (
            local["Config"]["Labels"]["org.opencontainers.image.revision"]
            != sources["docs"]
        ):
            raise ValueError("Docs archive belongs to another source revision")
    for name in sorted(pin_release.APPLICATION_IMAGES):
        reference = previous["images"][name]
        repository = reference.split("@", 1)[0].rsplit(":", 1)[0]
        tag = f"{repository}:sha-{head[:7]}"
        if name == "docs" and args.docs_image:
            docker("tag", args.docs_image, tag)
            docker("push", tag)
            pinned = pin_release.pin(tag)
            manifest = json.loads(
                docker("buildx", "imagetools", "inspect", "--raw", pinned)
            )
            if manifest["config"]["digest"] != local["Id"]:
                raise ValueError("Published docs differ from the checked image")
            pin_release.require_image_revision(pinned, sources[name])
            release["images"][name] = pinned
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(
                    f"docs-name={repository}\ndocs-digest={pinned.split('@')[1]}\n"
                )
        else:
            pinned = reference
        # Keep reused digests discoverable and protected by normal tag retention.
        docker(
            "buildx",
            "imagetools",
            "create",
            "--prefer-index=false",
            "--tag",
            tag,
            "--tag",
            f"{repository}:latest",
            pinned,
        )
        if pin_release.pin(tag).split("@", 1)[1] != pinned.split("@", 1)[1]:
            raise ValueError(f"Retagging changed the tested digest for {name}")
    args.output.write_text(
        json.dumps({"release": release, "static_base": base}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
