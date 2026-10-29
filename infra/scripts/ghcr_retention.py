#!/usr/bin/env python3
"""Delete superseded application image versions from GHCR.

Every main push publishes each application image as `sha-<commit>` and `latest`,
plus a provenance attestation that refers to the image digest. Nothing removes
them, so each package grows by two versions per merge. This keeps the newest
releases of each package, whatever `latest` and the committed release pin point
to, and the attestations of the images it keeps. Everything else is listed, and
deleted only with --delete.

An attestation names its image in its manifest's `subject`; GHCR may also tag it
`sha256-<image digest>`. An untagged version whose manifest cannot be read is
kept. An untagged version without a subject is an orphan, deleted only after a
grace period, so a publish that is still pushing never loses its versions.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

PACKAGES = (
    "off-key-frontend",
    "off-key-api-gateway",
    "off-key-tactic-middleware",
    "off-key-mqtt-radar",
    "off-key-mqtt-proxy",
    "off-key-db-sync",
)
RELEASE = (
    Path(__file__).resolve().parents[1]
    / "ansible/inventories/prod/group_vars/all/release.yml"
)
ORPHAN_GRACE = timedelta(days=1)
MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json"
)


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", "api", *args], capture_output=True, text=True, check=True, timeout=120
    ).stdout


def pinned_digests(release: Path = RELEASE) -> set[str]:
    images = json.loads(release.read_text())["release"]["images"].values()
    return {image.split("@", 1)[1] for image in images if "@" in image}


def created(version: dict) -> datetime:
    return datetime.fromisoformat(version["created_at"])


def tags(version: dict) -> list[str]:
    return version.get("metadata", {}).get("container", {}).get("tags", [])


def plan(versions, keep, pinned, subject_of, now):
    """Return (kept, deleted) versions of one package.

    subject_of(version) returns the digest an untagged version refers to, "" for
    a manifest without a subject, or None when the manifest could not be read.
    """
    images, referrers = [], []
    for version in versions:
        names = tags(version)
        if names and all(name.startswith("sha256-") for name in names):
            referrers.append((version, "sha256:" + names[0].removeprefix("sha256-")))
        elif names:
            images.append(version)
        else:
            subject = subject_of(version)
            if subject is None:
                images.append(version)
            else:
                referrers.append((version, subject))

    releases = sorted(
        (v for v in images if any(t.startswith("sha-") for t in tags(v))),
        key=created,
        reverse=True,
    )
    newest = {v["id"] for v in releases[:keep]}
    kept, deleted = [], []
    for version in images:
        names = tags(version)
        if (
            version["id"] in newest
            or version["name"] in pinned
            or not names  # an unreadable untagged manifest
            or any(t == "latest" or not t.startswith("sha-") for t in names)
        ):
            kept.append(version)
        else:
            deleted.append(version)

    kept_digests = {version["name"] for version in kept}
    for version, subject in referrers:
        if subject in kept_digests:
            kept.append(version)
        elif subject or now - created(version) > ORPHAN_GRACE:
            deleted.append(version)
        else:
            kept.append(version)
    return kept, deleted


class Registry:
    """Reads manifests from ghcr.io with the workflow's token."""

    def __init__(self, owner: str, user: str, token: str):
        self.owner, self.user, self.token = owner, user, token
        self.tokens: dict[str, str] = {}

    def bearer(self, package: str) -> str:
        if package not in self.tokens:
            basic = base64.b64encode(f"{self.user}:{self.token}".encode()).decode()
            request = urllib.request.Request(
                f"https://ghcr.io/token?service=ghcr.io&scope=repository:{self.owner}/{package}:pull",
                headers={"Authorization": f"Basic {basic}"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                self.tokens[package] = json.load(response)["token"]
        return self.tokens[package]

    def subject(self, package: str, digest: str) -> str | None:
        try:
            request = urllib.request.Request(
                f"https://ghcr.io/v2/{self.owner}/{package}/manifests/{digest}",
                headers={
                    "Authorization": f"Bearer {self.bearer(package)}",
                    "Accept": MANIFEST_TYPES,
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                manifest = json.load(response)
        except Exception as error:  # noqa: BLE001 - an unreadable manifest is kept
            print(f"  {package}@{digest}: manifest unreadable ({error}); kept")
            return None
        return manifest.get("subject", {}).get("digest", "")


def describe(version: dict) -> str:
    names = ", ".join(tags(version)) or "untagged"
    return f"{version['name'][:19]} ({names}, {version['created_at'][:10]})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=20)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()
    if args.keep < 1:
        parser.error("--keep must be at least 1")

    owner = os.environ["GITHUB_REPOSITORY_OWNER"].lower()
    kind = json.loads(gh(f"users/{owner}"))["type"]
    base = f"{'orgs' if kind == 'Organization' else 'users'}/{owner}/packages/container"
    registry = Registry(owner, os.environ["GITHUB_ACTOR"], os.environ["GH_TOKEN"])
    pinned = pinned_digests()
    now = datetime.now(UTC)
    summary = [
        "| Package | Kept | " + ("Deleted" if args.delete else "Would delete") + " |",
        "| --- | --- | --- |",
    ]

    for package in PACKAGES:
        pages = json.loads(
            gh("--paginate", "--slurp", f"{base}/{package}/versions?per_page=100")
        )
        versions = [version for page in pages for version in page]
        kept, deleted = plan(
            versions,
            args.keep,
            pinned,
            lambda version, package=package: registry.subject(package, version["name"]),
            now,
        )
        if not any(any(t.startswith("sha-") for t in tags(v)) for v in kept):
            raise SystemExit(f"{package}: refusing to delete every release")
        print(
            f"{package}: keep {len(kept)}, {'delete' if args.delete else 'would delete'} {len(deleted)}"
        )
        for version in sorted(deleted, key=created):
            print(f"  - {describe(version)}")
            if args.delete:
                gh("--method", "DELETE", f"{base}/{package}/versions/{version['id']}")
        summary.append(f"| `{package}` | {len(kept)} | {len(deleted)} |")

    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write("\n".join(summary) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
