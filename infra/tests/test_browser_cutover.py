"""Backend readiness is a real fence before a changed browser bundle can start."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import swarm_smoke
from jinja2 import Environment
from support import ROOT


class BrowserCutoverTests(unittest.TestCase):
    def test_intermediate_model_keeps_every_backend_service_and_omits_frontend(self):
        model = {
            "services": {
                "api": {"image": "api:new", "deploy": {"replicas": 2}},
                "frontend": {"image": "frontend:new"},
            },
            "networks": {"app": {}},
        }
        environment = Environment()
        environment.filters["to_nice_json"] = json.dumps
        environment.filters["combine"] = lambda original, update: original | update
        template = environment.from_string(
            (
                ROOT / "ansible/roles/stack_deploy/templates/backend-first.json.j2"
            ).read_text()
        )
        staged = json.loads(template.render(stack_compose_model=model))
        self.assertEqual(
            staged,
            {
                "services": {"api": model["services"]["api"]},
                "networks": model["networks"],
            },
        )
        self.assertIn("frontend", model["services"])

    def check_fence(self, *, previous, replicas, started):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "stack").mkdir()
            fence = {
                "backend_ready": True,
                "backend_ready_at": "2026-10-30T12:00:00Z",
                "previous_frontend_image": previous,
                "previous_frontend_replicas": replicas,
                "target_frontend_image": "frontend:new",
            }
            (directory / "stack/browser-cutover.json").write_text(json.dumps(fence))
            inspected = [
                {"Config": {"Image": "frontend:new"}, "State": {"StartedAt": started}}
            ]

            def run(*args):
                return SimpleNamespace(
                    stdout="container\n" if args[1] == "ps" else json.dumps(inspected)
                )

            with patch.object(swarm_smoke, "run", side_effect=run):
                swarm_smoke.verify_browser_cutover(directory)
            self.assertTrue((directory / "browser-cutover-evidence.json").exists())

    def test_new_bundle_must_start_after_backend_readiness(self):
        with self.assertRaises(AssertionError):
            self.check_fence(
                previous="frontend:old", replicas=1, started="2026-10-30T11:59:59Z"
            )
        self.check_fence(
            previous="frontend:old", replicas=1, started="2026-10-30T12:00:01Z"
        )

    def test_persistence_cutover_at_zero_replicas_still_requires_a_fresh_start(self):
        with self.assertRaises(AssertionError):
            self.check_fence(
                previous="frontend:new", replicas=0, started="2026-10-30T11:59:59Z"
            )

    def test_same_running_bundle_can_remain_active_during_an_idempotent_retry(self):
        self.check_fence(
            previous="frontend:new", replicas=1, started="2026-10-30T11:59:59Z"
        )
