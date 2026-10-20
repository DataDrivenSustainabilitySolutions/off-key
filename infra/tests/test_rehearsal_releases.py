"""Guard the two-release rehearsal's schema floor and coupled image selection."""

import json
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
