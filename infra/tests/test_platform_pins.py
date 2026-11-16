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
ALLOWED_DRIFT = {}
# EMQX 5.9 and later is BSL 1.1, not open source (docs/operations/emqx-license.md).
FIRST_NON_FOSS_EMQX = (5, 9)
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

    def test_collection_matrix_tests_the_production_emqx(self):
        workflow = yaml.safe_load((REPOSITORY / ".github/workflows/ci.yml").read_text())
        job = workflow["jobs"]["collection"]
        matrix = {str(tag) for tag in job["strategy"]["matrix"]["emqx"]}
        self.assertEqual(matrix, {release_images()["emqx"][1]})

    def test_every_emqx_pin_stays_open_source(self):
        workflow = yaml.safe_load((REPOSITORY / ".github/workflows/ci.yml").read_text())
        tags = {
            "release.yml": release_images()["emqx"][1],
            "ci.yml": workflow["jobs"]["collection"]["strategy"]["matrix"]["emqx"],
        }
        for path in COMPOSE_FILES:
            for service, image in compose_images(path):
                repository, tag = repository_and_tag(image)
                if repository.endswith("emqx/emqx"):
                    tags[f"{path}:{service}"] = tag
        flat = [
            (where, str(tag))
            for where, value in tags.items()
            for tag in (value if isinstance(value, list) else [value])
        ]
        self.assertGreater(len(flat), 4)
        for where, tag in flat:
            with self.subTest(where=where, tag=tag):
                version = re.match(r"^(\d+)\.(\d+)\.\d+$", tag)
                self.assertIsNotNone(version, "pin EMQX to an exact release")
                self.assertLess(
                    (int(version.group(1)), int(version.group(2))),
                    FIRST_NON_FOSS_EMQX,
                    "EMQX 5.9+ is BSL 1.1; see docs/operations/emqx-license.md",
                )

    def test_dependabot_never_proposes_a_bsl_emqx(self):
        config = yaml.safe_load((REPOSITORY / ".github/dependabot.yml").read_text())
        compose = [
            update
            for update in config["updates"]
            if update["package-ecosystem"] == "docker-compose"
        ]
        self.assertTrue(compose)
        for update in compose:
            rules = [
                rule
                for rule in update.get("ignore", [])
                if rule.get("dependency-name") == "emqx/emqx"
            ]
            self.assertEqual([rule.get("versions") for rule in rules], [[">= 5.9.0"]])


if __name__ == "__main__":
    unittest.main()
