"""Guard the two-release rehearsal's schema floor and coupled image selection."""

import json
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import rehearsal_releases
from rehearsal_releases import (
    MODEL_SERVICES,
    release_model,
    selected_release,
    validate_compatible_source,
)


class RehearsalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.object(
                rehearsal_releases.image_sources,
                "source_revision",
                side_effect=lambda name, revision, project=None: revision,
            )
        )

    def test_current_builds_only_read_caches_and_rollback_writes_its_own_scope(self):
        current = rehearsal_releases.build_cache_options(
            "off-key-api-gateway", "a" * 40
        )
        self.assertNotIn("--cache-to", current)
        self.assertIn("type=gha,version=2,scope=docker-validate-api-gateway", current)
        self.assertIn("type=gha,version=2,scope=docker-publish-api-gateway", current)
        rollback = rehearsal_releases.build_cache_options(
            "off-key-api-gateway", rehearsal_releases.COMPATIBLE_REVISION
        )
        destination = rollback[rollback.index("--cache-to") + 1]
        self.assertIn(
            f"scope=docker-rollback-{rehearsal_releases.COMPATIBLE_REVISION}-api-gateway",
            destination,
        )
        self.assertIn("mode=max", destination)
        self.assertIn("ignore-error=true", destination)

    def test_cached_and_local_builds_keep_the_same_production_inputs(self):
        revision = "a" * 40
        service = "off-key-api-gateway"
        reference = f"localhost:5010/{service}:sha-{revision[:12]}"
        digest = reference.rsplit(":", 1)[0] + "@sha256:" + "b" * 64
        with (
            patch.object(rehearsal_releases, "start_registry"),
            patch.object(
                rehearsal_releases, "BUILDS", {"api": (service, "services/api/gateway")}
            ),
            patch.object(
                rehearsal_releases,
                "run",
                return_value=SimpleNamespace(stdout=json.dumps([digest])),
            ) as docker,
        ):
            for cache in ("", "1"):
                with (
                    self.subTest(cache=cache),
                    patch.dict(
                        rehearsal_releases.os.environ, {"OFFKEY_BUILD_CACHE": cache}
                    ),
                ):
                    docker.reset_mock()
                    release = {"images": {}}
                    rehearsal_releases.build_local_images(
                        release, revision, Path("/source")
                    )
                    build = docker.call_args_list[0].args
                    self.assertEqual(
                        build[:2], ("docker", "buildx" if cache else "build")
                    )
                    self.assertEqual("--load" in build, bool(cache))
                    for argument in (
                        f"GIT_COMMIT={revision}",
                        f"SERVICE_NAME={service}",
                        "SERVICE_ROOT=services/api/gateway",
                        reference,
                    ):
                        self.assertIn(argument, build)
                    self.assertEqual(build[-1], "/source/backend")
                    self.assertEqual(release["images"], {"api": digest})

    def test_documentation_rollback_build_uses_the_selected_source_tree(self):
        digest = "localhost:5010/off-key-docs@sha256:" + "b" * 64
        with (
            patch.object(rehearsal_releases, "start_registry"),
            patch.object(
                rehearsal_releases, "BUILDS", {"docs": ("off-key-docs", "docs")}
            ),
            patch.object(
                rehearsal_releases,
                "run",
                return_value=SimpleNamespace(stdout=json.dumps([digest])),
            ) as docker,
        ):
            release = {"images": {}}
            rehearsal_releases.build_local_images(
                release, rehearsal_releases.COMPATIBLE_REVISION, Path("/older-source")
            )
            build = docker.call_args_list[0].args
            self.assertEqual(build[-1], "/older-source")
            self.assertEqual(
                build[build.index("-f") + 1],
                str(rehearsal_releases.ROOT.parent / "dev/docs/Dockerfile"),
            )
            self.assertEqual(release["images"]["docs"], digest)

    def test_reference_archive_refuses_missing_or_unreviewed_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                rehearsal_releases.archive_compatible_source(
                    directory, directory / "missing"
                )
            with self.assertRaisesRegex(ValueError, "reviewed compatible commit"):
                rehearsal_releases.archive_compatible_source(directory, directory)
            self.assertFalse((directory / "compatible-source").exists())

    def test_foreign_registry_name_is_never_deleted_even_after_prepare_rejection(self):
        inspected = SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"Config": {"Labels": {"off-key.ci": "someone-else"}}}]),
        )
        with patch.object(rehearsal_releases, "run", return_value=inspected) as docker:
            with self.assertRaisesRegex(ValueError, "belongs to another"):
                rehearsal_releases.start_registry()
            rehearsal_releases.stop_registry()
        self.assertEqual(docker.call_count, 2)
        self.assertTrue(
            all(
                call.args == ("docker", "inspect", rehearsal_releases.REGISTRY)
                for call in docker.call_args_list
            )
        )

    def test_owned_registry_cleanup_requires_the_exact_owner_label(self):
        inspected = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [{"Config": {"Labels": {"off-key.ci": "deployment-smoke"}}}]
            ),
        )
        with patch.object(rehearsal_releases, "run", return_value=inspected) as docker:
            rehearsal_releases.stop_registry()
        self.assertEqual(
            docker.call_args.args, ("docker", "rm", "-f", rehearsal_releases.REGISTRY)
        )

    def test_binary_selection_keeps_controller_worker_image_and_configuration_coherent(
        self,
    ):
        base = {
            "services": {
                name: {"image": "current", "environment": {"KEEP": "unchanged"}}
                for name in MODEL_SERVICES.values()
            }
        }
        base["services"]["postgres"] = {
            "image": "platform",
            "volumes": ["retained:/data"],
        }
        base["services"]["mqtt-radar"]["environment"]["RADAR_POOL_RUNTIME"] = "current"
        base["services"]["dojo-worker"] = {"image": "current"}
        snapshot = deepcopy(base)
        release = {
            "images": {name: f"older/{name}@sha256:target" for name in MODEL_SERVICES}
        }
        selected = release_model(base, release)
        self.assertEqual(base, snapshot)
        self.assertEqual(
            selected["services"]["postgres"], snapshot["services"]["postgres"]
        )
        self.assertEqual(
            selected["services"]["tactic"]["environment"],
            {
                "KEEP": "unchanged",
                "TACTIC_RADAR_IMAGE": release["images"]["mqtt_radar"],
            },
        )
        self.assertEqual(
            selected["services"]["db-sync"]["image"], release["images"]["db_sync"]
        )
        # The pool claims only workloads pinned to its own image.
        self.assertEqual(
            selected["services"]["mqtt-radar"]["environment"],
            {
                "KEEP": "unchanged",
                "RADAR_POOL_RUNTIME": release["images"]["mqtt_radar"],
            },
        )
        self.assertEqual(
            selected["services"]["dojo-worker"]["image"],
            release["images"]["mqtt_radar"],
        )

    def test_release_selection_reads_the_requested_immutable_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name, revision in (("production", "new"), ("compatible", "older")):
                (directory / f"{name}-release.json").write_text(
                    json.dumps({"release": {"application_revision": revision}})
                )
            self.assertEqual(
                selected_release(directory, "compatible")["application_revision"],
                "older",
            )
            self.assertEqual(
                selected_release(directory, "current")["application_revision"], "new"
            )
            with self.assertRaisesRegex(ValueError, "current or compatible"):
                selected_release(directory, "unreviewed")

    def test_changed_migration_or_numeric_dependency_rejects_the_rollback_reference(
        self,
    ):
        paths = [
            "backend/libs/core/src/off_key_core/models/adaptive_catalog.json",
            "backend/libs/core/src/off_key_core/db/migrations/010_monitoring_pipelines.sql",
            "backend/libs/core/src/off_key_core/db/catalogue_upgrade.py",
            "backend/libs/core/src/off_key_core/db/catalogue_v1.py",
            "backend/libs/core/src/off_key_core/db/catalogue_v1_models.py",
        ]

        def lock(aberrant, fastapi):
            return "".join(
                f'[[package]]\nname = "{name}"\nversion = "{version}"\n\n'
                for name, version in (("aberrant", aberrant), ("fastapi", fastapi))
            )

        with tempfile.TemporaryDirectory() as temporary:
            source, current = Path(temporary) / "older", Path(temporary) / "current"
            for root in (source, current):
                for name in paths:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("reviewed contract")
                (root / "backend/uv.lock").write_text(lock("1.3.0", "0.143.0"))
            validate_compatible_source(source, current)
            for name in paths:
                path = current / name
                path.write_text("unreviewed contract")
                with self.assertRaisesRegex(ValueError, "Review a new compatible"):
                    validate_compatible_source(source, current)
                path.write_text("reviewed contract")
            # Unrelated dependency bumps no longer require a new reference.
            locked = current / "backend/uv.lock"
            locked.write_text(lock("1.3.0", "0.143.2"))
            validate_compatible_source(source, current)
            locked.write_text(lock("1.4.0", "0.143.2"))
            with self.assertRaisesRegex(ValueError, "locked Aberrant differs"):
                validate_compatible_source(source, current)
            locked.write_text('[[package]]\nname = "fastapi"\nversion = "1"\n')
            with self.assertRaisesRegex(ValueError, "reviewed numerical libraries"):
                validate_compatible_source(source, current)
            locked.write_text(lock("1.3.0", "0.143.0"))
            (
                current
                / "backend/libs/core/src/off_key_core/db/migrations/011_future.sql"
            ).write_text("new schema")
            with self.assertRaisesRegex(ValueError, "different migration ledger"):
                validate_compatible_source(source, current)


REVISION = "c" * 40


def fake_docker(image_ids, labels=None):
    """A `run` stand-in that answers docker image inspect for loaded images."""

    def run(*args, **kwargs):
        if args[:3] == ("docker", "image", "inspect") and len(args) == 4:
            reference = args[3]
            service = reference.split("/", 1)[1].split(":", 1)[0]
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "Id": image_ids[service],
                            "Config": {
                                "Labels": {
                                    "org.opencontainers.image.revision": (
                                        labels or {}
                                    ).get(service, REVISION)
                                }
                            },
                        }
                    ]
                )
            )
        if args[:3] == ("docker", "image", "inspect"):
            reference = args[3]
            return SimpleNamespace(
                stdout=json.dumps([reference.rsplit(":", 1)[0] + "@sha256:" + "d" * 64])
            )
        return SimpleNamespace(stdout="")

    return run


class CiImageTests(unittest.TestCase):
    """One build per run; consumers use only the exact images that build produced."""

    def setUp(self):
        self.enterContext(
            patch.object(
                rehearsal_releases.image_sources,
                "source_revision",
                side_effect=lambda name, revision, project=None: revision,
            )
        )
        self.ids = {
            service: "sha256:" + format(index, "x") * 64
            for index, (service, _) in enumerate(
                rehearsal_releases.BUILDS.values(), start=1
            )
        }
        self.directory = tempfile.TemporaryDirectory()
        self.archive = Path(self.directory.name) / "images.tar.zst"
        self.archive.write_bytes(b"archive")
        self.digest = rehearsal_releases.sha256_file(self.archive)
        self.manifest = {
            "revision": REVISION,
            "archive_sha256": self.digest,
            "images": {
                name: {
                    "reference": rehearsal_releases.image_reference(service, REVISION),
                    "image_id": self.ids[service],
                }
                for name, (service, _) in rehearsal_releases.BUILDS.items()
            },
        }

    def tearDown(self):
        self.directory.cleanup()

    def load(self, manifest=None, digest=None, run=None):
        process = SimpleNamespace(stdout=SimpleNamespace(close=lambda: None))
        process.wait = lambda: 0
        with (
            patch.object(rehearsal_releases, "run", run or fake_docker(self.ids)),
            patch.object(rehearsal_releases.subprocess, "Popen", return_value=process),
            patch.object(
                rehearsal_releases.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as loader,
        ):
            result = rehearsal_releases.load_ci_images(
                self.archive,
                manifest or self.manifest,
                digest or self.digest,
                REVISION,
            )
        return result, loader

    def test_the_tested_images_load_with_their_recorded_identities(self):
        loaded, loader = self.load()
        self.assertEqual(loaded, self.manifest["images"])
        self.assertEqual(loader.call_args.args[0], ["docker", "load", "-q"])

    def test_any_identity_mismatch_rejects_the_images(self):
        other = deepcopy(self.manifest)
        other["revision"] = "e" * 40
        with self.assertRaisesRegex(ValueError, "belong to"):
            self.load(manifest=other)
        # The digest travels as a job output, apart from the artifact.
        with self.assertRaisesRegex(ValueError, "recorded digest"):
            self.load(digest="0" * 64)
        self.archive.write_bytes(b"replaced archive")
        with self.assertRaisesRegex(ValueError, "differs from the one"):
            self.load()
        self.archive.write_bytes(b"archive")
        partial = deepcopy(self.manifest)
        del partial["images"]["mqtt_radar"]
        with self.assertRaisesRegex(ValueError, "every application image"):
            self.load(manifest=partial)
        changed = dict(self.ids, **{"off-key-mqtt-radar": "sha256:" + "f" * 64})
        with self.assertRaisesRegex(ValueError, "mqtt_radar image differs"):
            self.load(run=fake_docker(changed))
        wrong_label = fake_docker(self.ids, {"off-key-frontend": "e" * 40})
        with self.assertRaisesRegex(ValueError, "frontend image belongs to"):
            self.load(run=wrong_label)

    def test_ci_and_rehearsal_builds_share_every_input(self):
        commands = []

        def run(*args, **kwargs):
            commands.append(args)
            return fake_docker(self.ids)(*args, **kwargs)

        process = SimpleNamespace(stdout=SimpleNamespace(close=lambda: None))
        process.wait = lambda: 0
        with (
            patch.object(rehearsal_releases, "run", run),
            patch.object(rehearsal_releases.shutil, "which", return_value="zstd"),
            patch.object(rehearsal_releases.subprocess, "Popen", return_value=process),
            patch.object(
                rehearsal_releases.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ),
        ):
            manifest = rehearsal_releases.build_ci_images(
                REVISION, Path("/source"), self.archive
            )
        builds = [
            args for args in commands if args[:3] == ("docker", "buildx", "build")
        ]
        self.assertEqual(len(builds), len(rehearsal_releases.BUILDS))
        for service, source in rehearsal_releases.BUILDS.values():
            expected = rehearsal_releases.build_arguments(
                service, source, REVISION, Path("/source")
            )
            (build,) = [
                args for args in builds if args[-len(expected) :] == tuple(expected)
            ]
            destinations = [
                build[index + 1]
                for index, value in enumerate(build)
                if value == "--cache-to"
            ]
            suffix = service.removeprefix("off-key-")
            self.assertEqual(
                destinations,
                [
                    f"type=gha,version=2,scope=docker-validate-{suffix},mode=max,ignore-error=true"
                ],
            )
        self.assertEqual(manifest["revision"], REVISION)
        self.assertEqual(
            manifest["archive_sha256"], rehearsal_releases.sha256_file(self.archive)
        )
        self.assertEqual(
            {name: item["image_id"] for name, item in manifest["images"].items()},
            {
                name: self.ids[service]
                for name, (service, _) in rehearsal_releases.BUILDS.items()
            },
        )

    def test_the_rehearsal_registry_serves_the_loaded_images(self):
        with (
            patch.object(rehearsal_releases, "start_registry"),
            patch.object(rehearsal_releases, "run", fake_docker(self.ids)),
        ):
            release = {"images": {}}
            rehearsal_releases.push_loaded_images(release, REVISION)
        self.assertEqual(set(release["images"]), set(rehearsal_releases.BUILDS))
        for reference in release["images"].values():
            self.assertRegex(reference, r"^localhost:5010/off-key-[\w-]+@sha256:d{64}$")

    def test_ci_rehearsals_never_rebuild_the_current_images(self):
        import swarm_smoke

        self.enterContext(
            patch.object(
                swarm_smoke,
                "revisions",
                return_value=dict.fromkeys(rehearsal_releases.BUILDS, REVISION),
            )
        )
        release = {"images": {}}
        for environment, expected in (
            ({"CI": "true", "OFFKEY_REHEARSAL_IMAGES": "loaded"}, "push_loaded_images"),
            ({"CI": "", "OFFKEY_REHEARSAL_IMAGES": ""}, "build_local_images"),
        ):
            with (
                self.subTest(environment=environment),
                patch.dict(
                    swarm_smoke.os.environ,
                    environment | {"GITHUB_EVENT_NAME": "pull_request"},
                ),
                patch.object(swarm_smoke, "push_loaded_images") as loaded,
                patch.object(swarm_smoke, "build_local_images") as built,
            ):
                swarm_smoke.images(release, REVISION)
                self.assertEqual(loaded.called, expected == "push_loaded_images")
                self.assertEqual(built.called, expected == "build_local_images")
        with (
            patch.dict(
                swarm_smoke.os.environ,
                {
                    "CI": "true",
                    "OFFKEY_REHEARSAL_IMAGES": "",
                    "GITHUB_EVENT_NAME": "pull_request",
                },
            ),
            patch.object(swarm_smoke, "build_local_images") as built,
            self.assertRaisesRegex(ValueError, "load them first"),
        ):
            swarm_smoke.images(release, REVISION)
        built.assert_not_called()


class PublishedImageTests(unittest.TestCase):
    def setUp(self):
        import swarm_smoke

        self.smoke = swarm_smoke
        self.reference = "ghcr.io/example/frontend:latest"
        self.release = {"images": {"frontend": self.reference}}
        self.source = "b" * 40
        self.elapsed = 0
        self.enterContext(patch.object(swarm_smoke, "APPLICATION_IMAGES", {"frontend"}))
        self.enterContext(
            patch.object(
                swarm_smoke, "revisions", return_value={"frontend": self.source}
            )
        )
        self.enterContext(
            patch.dict(
                swarm_smoke.os.environ,
                {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"},
            )
        )
        self.enterContext(
            patch.object(
                swarm_smoke.time, "monotonic", side_effect=lambda: self.elapsed
            )
        )
        self.enterContext(
            patch.object(swarm_smoke.time, "sleep", side_effect=self.advance)
        )

    def advance(self, seconds):
        self.elapsed += seconds

    def test_published_image_lookup_retries_after_a_request_timeout(self):
        pinned = self.reference + "@sha256:" + "c" * 64

        def lookup(*args):
            if self.elapsed == 0:
                self.advance(60)
                raise subprocess.TimeoutExpired(["docker", "buildx"], 60)
            return pinned

        with patch.object(self.smoke, "pin", side_effect=lookup) as pin:
            self.smoke.images(self.release, REVISION)
        self.assertEqual(pin.call_count, 2)
        for call in pin.call_args_list:
            self.assertEqual(call.args, (self.reference, REVISION, self.source))
        self.assertEqual(self.release["images"]["frontend"], pinned)

    def test_persistent_lookup_failure_never_accepts_an_unverified_image(self):
        for failure in (
            subprocess.TimeoutExpired(["docker", "buildx"], 60),
            ValueError("Image belongs to another revision"),
        ):
            with self.subTest(failure=type(failure).__name__):
                self.elapsed = 0

                def lookup(*args, failure=failure):
                    self.advance(60)
                    raise failure

                with (
                    patch.object(self.smoke, "pin", side_effect=lookup),
                    self.assertRaisesRegex(
                        AssertionError, "Timed out waiting for published frontend image"
                    ),
                ):
                    self.smoke.images(self.release, REVISION)
                self.assertLess(self.elapsed, 400)
                self.assertEqual(self.release["images"]["frontend"], self.reference)
