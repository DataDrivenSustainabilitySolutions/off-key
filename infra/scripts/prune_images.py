#!/usr/bin/env python3
"""Remove superseded application images from a Swarm node after a verified release.

Swarm pulls each release's images by digest and never removes the old ones, so
every release leaves application images behind on the nodes that ran them. `services`
runs on the manager and prints every image a Swarm service still names, which
covers both stacks and TACTIC's runtime RADAR services. `prune` runs on each
node and removes only images of the application repositories that neither the
release nor any service names.

A broad `docker image prune` is not safe here: images pulled by digest carry no
tag, so the RADAR image seeded for runtime workers looks dangling, and runtime
workers cannot pull it again without registry credentials. An image a container
still uses, including Swarm's retained task history, stays until that goes.

An image can also lose every tag and digest reference, for example when a newer
pull takes over its tag. Such an image is only removed when its
org.opencontainers.image.source label names the off-key repository, and never
when its id is one that a kept reference still resolves to on this node.
"""

import json
import subprocess
import sys

SOURCE_LABEL = "org.opencontainers.image.source"
SOURCE = "github.com/datadrivensustainabilitysolutions/off-key"


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=120
    )


def repository(reference: str) -> str:
    name = reference.split("@", 1)[0]
    head, _, tail = name.rpartition("/")
    return f"{head}/{tail.split(':', 1)[0]}" if head else tail.split(":", 1)[0]


def from_off_key(image) -> bool:
    """Whether the image's source label names the off-key repository."""
    labels = (image.get("Config") or {}).get("Labels") or {}
    source = (labels.get(SOURCE_LABEL) or "").strip().lower().rstrip("/")
    return source.removesuffix(".git").split("://", 1)[-1] == SOURCE


def stale(images, application, keep, kept_ids=()):
    """Return the ids of application images that no kept reference names."""
    repositories = {repository(reference) for reference in application}
    digests = {r.split("@", 1)[1] for r in keep if "@" in r}
    tagged = {r for r in keep if "@" not in r}
    kept_ids = set(kept_ids)
    removable = []
    for image in images:
        if image["Id"] in kept_ids:
            continue
        references = (image.get("RepoTags") or []) + (image.get("RepoDigests") or [])
        if not references:
            # Unreferenced: only off-key's own builds, by their source label.
            if from_off_key(image):
                removable.append(image["Id"])
            continue
        if any(repository(r) not in repositories for r in references):
            continue
        if any(r.split("@", 1)[-1] in digests for r in image.get("RepoDigests") or []):
            continue
        if tagged.intersection(image.get("RepoTags") or []):
            continue
        removable.append(image["Id"])
    return removable


def services() -> int:
    ids = docker("service", "ls", "--quiet")
    if ids.returncode:
        sys.stderr.write(ids.stderr)
        return 1
    images = []
    if ids.stdout.split():
        inspected = docker(
            "service",
            "inspect",
            "--format",
            "{{.Spec.TaskTemplate.ContainerSpec.Image}}",
            *ids.stdout.split(),
        )
        if inspected.returncode:
            sys.stderr.write(inspected.stderr)
            return 1
        images = sorted(set(inspected.stdout.split()))
    print(json.dumps(images))
    return 0


def resolve(references) -> set[str]:
    """Image ids that kept references resolve to here; absent ones are skipped."""
    ids = set()
    for reference in sorted(set(references)):
        result = docker("image", "inspect", "--format", "{{.Id}}", reference)
        if result.returncode == 0:
            ids.add(result.stdout.strip())
    return ids


def prune(application, keep) -> int:
    # Without --all, newer Docker releases leave out untagged images, which
    # is every image Swarm pulled by digest.
    ids = docker("image", "ls", "--all", "--quiet", "--no-trunc")
    if ids.returncode:
        sys.stderr.write(ids.stderr)
        return 1
    images = []
    if ids.stdout.split():
        inspected = docker("image", "inspect", *sorted(set(ids.stdout.split())))
        if inspected.returncode:
            sys.stderr.write(inspected.stderr)
            return 1
        images = json.loads(inspected.stdout)
    removed, in_use = [], 0
    for image in stale(images, application, keep, resolve(keep)):
        result = docker("image", "rm", image)
        if result.returncode == 0:
            removed.append(image)
        elif "conflict" in result.stderr.lower():
            in_use += 1
        else:
            print(f"Could not remove {image}: {result.stderr.strip()}")
    print(
        f"Removed {len(removed)} superseded application images; "
        f"{in_use} are still used by containers."
    )
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["services"]:
        sys.exit(services())
    if sys.argv[1:2] == ["prune"] and len(sys.argv) == 4:
        sys.exit(prune(json.loads(sys.argv[2]), json.loads(sys.argv[3])))
    sys.exit("usage: prune_images.py services | prune APPLICATION_JSON KEEP_JSON")
