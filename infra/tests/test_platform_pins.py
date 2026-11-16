"""Local stacks run the production platform images, except for listed drift."""

import json
import re
import unittest

import yaml
from support import ROOT

REPOSITORY = ROOT.parent
RELEASE = ROOT / "ansible/inventories/prod/group_vars/all/release.yml"
PLATFORM = ("postgres", "socket_proxy", "tailscale", "gost", "mosquitto")
COMPOSE_FILES = (
    "docker-compose.yml",
    "dev/local/compose.yml",
    "infra/stack/docker-compose.swarm.yml",
    "backend/tests/collection_integration/compose.yml",
)
# (file, platform image) -> the deliberately different repository:tag, and why.
ALLOWED_DRIFT = {}
# The internal broker's service. Other eclipse-mosquitto services are source
# brokers standing in for third-party ones, and keep their own version.
INTERNAL_BROKER = "mosquitto"
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


def platform_key(service, repository, release):
    for key, (expected, _) in release.items():
        if key == "mosquitto" and service != INTERNAL_BROKER:
            continue
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
                key = platform_key(service, repository, release)
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

    def test_every_stack_runs_the_internal_broker_as_mosquitto(self):
        for path in COMPOSE_FILES:
            with self.subTest(path=path):
                images = dict(compose_images(path))
                # dev/local/compose.yml overlays docker-compose.yml's broker.
                if path != "dev/local/compose.yml":
                    self.assertIn(INTERNAL_BROKER, images)
                self.assertFalse(
                    [image for image in images.values() if "emqx" in image],
                    "EMQX 5.9+ is BSL 1.1; the internal broker is Mosquitto",
                )

    def test_collection_suite_tests_the_production_broker(self):
        workflow = yaml.safe_load((REPOSITORY / ".github/workflows/ci.yml").read_text())
        steps = "\n".join(
            step.get("run", "") for step in workflow["jobs"]["collection"]["steps"]
        )
        self.assertIn("release_image.py mosquitto", steps)
        self.assertIn('MOSQUITTO_TEST_IMAGE=$image" >> "$GITHUB_ENV"', steps)


if __name__ == "__main__":
    unittest.main()
