"""Every copy of the service-to-image map and the rollback revision agrees.

pin_release.APPLICATION_IMAGES and rehearsal_releases.BUILDS are canonical;
the image workflow, both Compose files, dev/local/run.py and the docs follow.
"""

import json
import re
import unittest

import yaml
from rehearsal_releases import BUILDS, COMPATIBLE_REVISION, MODEL_SERVICES
from support import ROOT, load_script
from test_platform_pins import ComposeLoader

REPOSITORY = ROOT.parent
WORKFLOWS = REPOSITORY / ".github/workflows"
# Built for local stacks and validated in CI, never published or deployed.
BUILD_ONLY = {"off-key-mqtt-simulator": "services/mqtt/simulator"}
IMAGE_DEFAULT = re.compile(r"^\$\{([A-Z_]+_IMAGE):-([\w.-]+):[\w.-]+\}$")


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def matrix_builds():
    """image_name -> SERVICE_ROOT (None for the frontend) from docker-images.yml."""
    builds = {}
    for entry in workflow("docker-images.yml")["jobs"]["build-images"]["strategy"][
        "matrix"
    ]["include"]:
        args = dict(
            line.split("=", 1) for line in entry["build_args"].split("\n") if line
        )
        if entry["context"] == "./frontend":
            builds[entry["image_name"]] = None
        else:
            assert args["SERVICE_NAME"] == entry["image_name"], entry
            builds[entry["image_name"]] = args["SERVICE_ROOT"]
    return builds


def compose_builds(path):
    """image_name -> (SERVICE_ROOT, image variable) for backend Compose builds."""
    document = yaml.load((REPOSITORY / path).read_text(), Loader=ComposeLoader)
    builds = {}
    for service in document["services"].values():
        args = (service.get("build") or {}).get("args") or {}
        if "SERVICE_NAME" in args:
            variable, image = IMAGE_DEFAULT.match(service["image"]).groups()
            assert image == args["SERVICE_NAME"], service
            builds[image] = (args["SERVICE_ROOT"], variable)
    return builds


class ServiceRegistryTests(unittest.TestCase):
    def test_release_keys_builds_and_model_services_name_the_same_images(self):
        pin_release = load_script("pin_release")
        images = json.loads(pin_release.RELEASE.read_text())["release"]["images"]
        self.assertEqual(set(BUILDS), pin_release.APPLICATION_IMAGES)
        self.assertEqual(set(MODEL_SERVICES), pin_release.APPLICATION_IMAGES)
        for key, (image_name, _) in BUILDS.items():
            with self.subTest(key=key):
                repository = images[key].split("@", 1)[0].rsplit(":", 1)[0]
                self.assertTrue(repository.endswith("/" + image_name), repository)

    def test_image_workflow_builds_every_release_image_from_its_root(self):
        expected = dict(BUILDS.values()) | BUILD_ONLY
        self.assertEqual(matrix_builds(), expected)

    def test_publishing_skips_the_build_only_images(self):
        job = workflow("docker-images.yml")["jobs"]["build-images"]
        build_only = {
            entry["image_name"]
            for entry in job["strategy"]["matrix"]["include"]
            if entry.get("build_only")
        }
        self.assertEqual(build_only, set(BUILD_ONLY))
        self.assertEqual(
            job["env"]["PUBLISH"], "${{ inputs.publish && !matrix.build_only }}"
        )
        publishing = [
            step
            for step in job["steps"]
            if "inputs.publish" in json.dumps(step)
            and "!inputs.publish" not in json.dumps(step)
        ]
        self.assertEqual(publishing, [])

    def test_compose_builds_match_the_image_workflow(self):
        matrix = matrix_builds()
        run_py = (REPOSITORY / "dev/local/run.py").read_text()
        local_images = dict(re.findall(r'\("([A-Z_]+_IMAGE)", "([\w-]+)"\)', run_py))
        for path in ("docker-compose.yml", "dev/local/compose.yml"):
            for image, (root, variable) in compose_builds(path).items():
                with self.subTest(path=path, image=image):
                    self.assertEqual(matrix[image], root)
                    self.assertEqual(
                        f"off-key-{local_images[variable]}", image, variable
                    )

    def test_rollback_revision_is_the_same_everywhere(self):
        steps = workflow("deployment-smoke.yml")["jobs"]["deployment-smoke"]["steps"]
        (checkout,) = [
            step
            for step in steps
            if step.get("name")
            == "Check out the immutable pipeline-compatible rollback reference"
        ]
        self.assertEqual(checkout["with"]["ref"], COMPATIBLE_REVISION)
        docs = (REPOSITORY / "docs/development/monitoring-pipelines.md").read_text()
        self.assertIn(f"`{COMPATIBLE_REVISION}`", docs)


if __name__ == "__main__":
    unittest.main()
