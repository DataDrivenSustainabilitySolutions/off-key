"""Policy and lifecycle checks alongside the real multi-node smoke rehearsal."""

import unittest

from support import load_script

configuration = load_script("observability_config")
compiler = load_script("compile_stack")


class ObservabilityPolicyTests(unittest.TestCase):
    def test_rejects_foreign_storage_paths_and_unsafe_reservations(self):
        inputs = {"stack_name": "off-key", "data_node": "DDSS-2"}
        for override in (
            {"data_root": "/var/lib/docker"},
            {"storage_root": "/srv/offkey-observability"},
            {"data_root": "/srv/offkey-observability/../application"},
            {"data_node": ""},
            {"storage_size_gib": 0},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                configuration.ObservabilitySettings.model_validate(inputs | override)
        with self.assertRaises(ValueError):
            configuration.ServiceBudget(
                memory_mib=64, reserved_memory_mib=128, cpus=1, reserved_cpus=0.1
            )

    def test_component_split_never_carries_application_credentials_into_monitoring(
        self,
    ):
        model = {
            "services": {
                "api": {
                    "image": "api",
                    "environment": {"POSTGRES_PASSWORD": "synthetic-test-only"},
                },
                "loki": {
                    "image": "loki",
                    "deploy": {"labels": {"off-key.component": "observability"}},
                    "configs": [{"source": "loki-config"}],
                    "volumes": [{"type": "volume", "source": "logs"}],
                },
            },
            "configs": {
                "loki-config": {"file": "loki.yml"},
                "application-config": {"file": "app.yml"},
            },
            "secrets": {"database-password": {"external": True}},
            "volumes": {"logs": {}, "database": {}},
        }
        observed = compiler.select_component(model, "observability")
        self.assertEqual(set(observed["services"]), {"loki"})
        self.assertEqual(set(observed["configs"]), {"loki-config"})
        self.assertEqual(set(observed["volumes"]), {"logs"})
        self.assertFalse(observed["secrets"])
        self.assertEqual(
            set(compiler.select_component(model, "application")["services"]), {"api"}
        )
