"""Local stacks run the production platform images, except for listed drift."""

import json
import re
import unittest

import yaml
from support import ROOT

REPOSITORY = ROOT.parent
RELEASE = ROOT / "ansible/inventories/prod/group_vars/all/release.yml"
PLATFORM = ("postgres", "socket_proxy", "tailscale", "gost", "emqx")
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.cluster.yml",
    "dev/local/compose.yml",
    "infra/stack/docker-compose.swarm.yml",
    "backend/tests/collection_integration/compose.yml",
)
# (file, platform image) -> the deliberately different repository:tag, and why.
ALLOWED_DRIFT = {
    # Local stacks track EMQX 6.x; production stays on 5.8.7, the last
    # Apache-2.0 release. The collection matrix covers both.
    ("docker-compose.yml", "emqx"): "emqx/emqx:6.3.1",
    ("docker-compose.cluster.yml", "emqx"): "emqx/emqx:6.3.1",
    # The production Docker Hub image is amd64-only; local runs use the
    # multi-arch GHCR build (see swarm_smoke.py).
    ("dev/local/compose.yml", "socket_proxy"): (
        "ghcr.io/tecnativa/docker-socket-proxy:v0.4.2"
    ),
}
DEFAULT = re.compile(r"^\$\{[A-Z0-9_]+:-(.+)\}$")


class ComposeLoader(yaml.SafeLoader):
    """Reads Compose merge tags (!reset, !override) as their plain values."""


ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_scalar(node)
    ),
)


def repository_and_tag(reference):
    """`repo[:tag][@digest]` -> (repo, tag); a missing tag means latest."""
    name = reference.split("@", 1)[0]
    repository, _, tag = name.rpartition(":")
    if not repository or "/" in tag:
        return name, "latest"
    return repository, tag


def release_images():
    images = json.loads(RELEASE.read_text())["release"]["images"]
    return {key: repository_and_tag(images[key]) for key in PLATFORM}


def platform_key(repository, release):
    for key, (expected, _) in release.items():
        if repository == expected or repository.endswith("/" + expected):
            return key
    return None


def compose_images(path):
    document = yaml.load((REPOSITORY / path).read_text(), Loader=ComposeLoader)
    for service, definition in (document.get("services") or {}).items():
        image = (definition or {}).get("image")
        if image:
            match = DEFAULT.match(image)
            yield service, match.group(1) if match else image


class PlatformPinTests(unittest.TestCase):
    def test_compose_platform_images_match_release_or_are_listed_drift(self):
        release = release_images()
        seen = set()
        for path in COMPOSE_FILES:
            for service, image in compose_images(path):
                repository, tag = repository_and_tag(image)
                key = platform_key(repository, release)
                if key is None:
                    continue
                seen.add((path, key))
                with self.subTest(path=path, service=service):
                    drift = ALLOWED_DRIFT.get((path, key))
                    if drift is None:
                        self.assertEqual((repository, tag), release[key])
                    else:
                        self.assertEqual(f"{repository}:{tag}", drift)
        self.assertLessEqual(set(ALLOWED_DRIFT), seen, "stale ALLOWED_DRIFT entry")

    def test_collection_matrix_covers_production_and_local_emqx(self):
        workflow = yaml.safe_load(
            (REPOSITORY / ".github/workflows/collection-integration.yml").read_text()
        )
        (job,) = workflow["jobs"].values()
        matrix = {str(tag) for tag in job["strategy"]["matrix"]["emqx"]}
        production = release_images()["emqx"][1]
        local = ALLOWED_DRIFT[("docker-compose.yml", "emqx")].rsplit(":", 1)[1]
        self.assertEqual(matrix, {production, local})


if __name__ == "__main__":
    unittest.main()
