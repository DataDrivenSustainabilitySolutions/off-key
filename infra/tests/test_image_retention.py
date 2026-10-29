"""Old application images leave GHCR and the nodes; recent, pinned and used ones stay."""

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from support import ROOT, load_script

retention = load_script("ghcr_retention")
prune = load_script("prune_images")
REPOSITORY = ROOT.parent
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
OWNER = "ghcr.io/datadrivensustainabilitysolutions"


def version(number, tags=(), age=timedelta(days=30), digest=None):
    return {
        "id": number,
        "name": digest or f"sha256:{number:064x}",
        "created_at": (NOW - age).isoformat().replace("+00:00", "Z"),
        "metadata": {"container": {"tags": list(tags)}},
    }


def release(number, age_days):
    """One published image and its attestation, as a main push leaves them."""
    image = version(number, [f"sha-{number:07x}"], timedelta(days=age_days))
    attestation = version(number + 1000, age=timedelta(days=age_days))
    return image, attestation, {attestation["name"]: image["name"]}


class GhcrRetentionTests(unittest.TestCase):
    def plan(self, versions, subjects, keep=2, pinned=()):
        kept, deleted = retention.plan(
            versions, keep, set(pinned), lambda v: subjects.get(v["name"]), NOW
        )
        return sorted(v["id"] for v in kept), sorted(v["id"] for v in deleted)

    def test_keeps_the_newest_releases_with_their_attestations(self):
        versions, subjects = [], {}
        for number in range(1, 6):
            image, attestation, subject = release(number, 10 - number)
            versions += [image, attestation]
            subjects |= subject
        kept, deleted = self.plan(versions, subjects)
        self.assertEqual(kept, [4, 5, 1004, 1005])
        self.assertEqual(deleted, [1, 2, 3, 1001, 1002, 1003])

    def test_latest_pinned_and_unknown_tags_are_never_deleted(self):
        versions = [
            version(1, ["sha-0000001", "latest"], timedelta(days=90)),
            version(2, ["sha-0000002"], timedelta(days=80)),
            version(3, ["v1.0"], timedelta(days=70)),
            version(4, ["sha-0000004"], timedelta(days=2)),
            version(5, ["sha-0000005"], timedelta(days=1)),
            version(6, ["sha-0000006"], timedelta(days=60)),
        ]
        kept, deleted = self.plan(versions, {}, pinned=[versions[1]["name"]])
        self.assertEqual(kept, [1, 2, 3, 4, 5])
        self.assertEqual(deleted, [6])

    def test_tagged_attestations_follow_their_image(self):
        old = version(1, ["sha-0000001"], timedelta(days=9))
        new = version(2, ["sha-0000002"], timedelta(days=1))
        versions = [
            old,
            new,
            version(3, ["sha256-" + old["name"].removeprefix("sha256:")]),
            version(4, ["sha256-" + new["name"].removeprefix("sha256:")]),
        ]
        kept, deleted = self.plan(versions, {}, keep=1)
        self.assertEqual(kept, [2, 4])
        self.assertEqual(deleted, [1, 3])

    def test_orphans_wait_out_the_grace_period_and_unreadable_ones_stay(self):
        versions = [
            version(1, ["sha-0000001"], timedelta(days=1)),
            version(2, age=timedelta(days=3)),  # orphan
            version(3, age=timedelta(hours=2)),  # a publish still pushing
            version(4, age=timedelta(days=3)),  # unreadable manifest
        ]
        subjects = {versions[1]["name"]: "", versions[2]["name"]: ""}
        kept, deleted = self.plan(versions, subjects)
        self.assertEqual(kept, [1, 3, 4])
        self.assertEqual(deleted, [2])

    def test_the_committed_release_pins_are_kept(self):
        pinned = retention.pinned_digests()
        images = json.loads(retention.RELEASE.read_text())["release"]["images"]
        self.assertEqual(pinned, {image.split("@", 1)[1] for image in images.values()})

    def test_every_published_image_is_covered(self):
        workflow = yaml.safe_load(
            (REPOSITORY / ".github/workflows/docker-images.yml").read_text()
        )
        matrix = workflow["jobs"]["build-images"]["strategy"]["matrix"]["include"]
        self.assertEqual(
            sorted(retention.PACKAGES), sorted(e["image_name"] for e in matrix)
        )

    def test_only_a_scheduled_run_with_the_switch_or_a_manual_choice_deletes(self):
        workflow = yaml.load(
            (REPOSITORY / ".github/workflows/ghcr-retention.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        job = workflow["jobs"]["retention"]
        self.assertEqual(workflow["permissions"], {})
        self.assertEqual(job["permissions"], {"contents": "read", "packages": "write"})
        self.assertIn("vars.GHCR_RETENTION_ENABLED == 'true'", job["env"]["DELETE"])
        self.assertIn("inputs.delete", job["env"]["DELETE"])


def image(identifier, tags=(), digests=()):
    return {"Id": identifier, "RepoTags": list(tags), "RepoDigests": list(digests)}


class NodeImagePruneTests(unittest.TestCase):
    def test_removes_only_application_images_nothing_names(self):
        radar = f"{OWNER}/off-key-mqtt-radar"
        api = f"{OWNER}/off-key-api-gateway"
        application = [
            f"{radar}:sha-0000002@sha256:{'2' * 64}",
            f"{api}:sha-0000002@sha256:{'b' * 64}",
        ]
        demo_radar = f"{radar}:sha-0000001@sha256:{'1' * 64}"
        keep = application + [demo_radar, "emqx/emqx:5.8.7@sha256:" + "e" * 64]
        images = [
            # Pulled by digest, so untagged: the current and demo RADAR images.
            image("current", digests=[f"{radar}@sha256:{'2' * 64}"]),
            image("demo", digests=[f"{radar}@sha256:{'1' * 64}"]),
            image("old-radar", digests=[f"{radar}@sha256:{'0' * 64}"]),
            image("old-api", [f"{api}:sha-0000001"], [f"{api}@sha256:{'a' * 64}"]),
            image("emqx", digests=["emqx/emqx@sha256:" + "f" * 64]),
            image("local-build", ["off-key-frontend:validation"]),
            image("dangling-layer"),
        ]
        self.assertEqual(
            prune.stale(images, application, keep), ["old-radar", "old-api"]
        )

    def test_repository_names_ignore_tags_digests_and_registry_ports(self):
        self.assertEqual(
            prune.repository(f"{OWNER}/off-key-db-sync:sha-1@sha256:{'c' * 64}"),
            f"{OWNER}/off-key-db-sync",
        )
        self.assertEqual(
            prune.repository("registry:5000/team/app"), "registry:5000/team/app"
        )
        self.assertEqual(prune.repository("postgres:16"), "postgres")

    def test_deploy_prunes_after_verification_without_failing_the_release(self):
        plays = yaml.safe_load((ROOT / "ansible/deploy.yml").read_text())
        cleanup = plays[-1]
        self.assertEqual(cleanup["hosts"], "swarm_manager:swarm_worker")
        self.assertIn("Verify and record", json.dumps(plays[-2]))
        for task in cleanup["tasks"]:
            self.assertTrue(task["ignore_errors"])
        self.assertTrue(Path(ROOT / "scripts/prune_images.py").exists())


if __name__ == "__main__":
    unittest.main()
