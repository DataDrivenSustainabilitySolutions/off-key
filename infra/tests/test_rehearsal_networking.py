"""Rehearsal endpoints must allow the production service's rolling updates."""

import unittest
from copy import deepcopy

import yaml
from support import ROOT
from swarm_smoke import expose_rehearsal_ports


class RehearsalNetworkingTests(unittest.TestCase):
    def test_documentation_replacements_can_share_the_single_rehearsal_node(self):
        production = yaml.safe_load(
            (ROOT / "stack/docker-compose.docs.yml").read_text()
        )["services"]["docs"]
        services = {
            name: {}
            for name in ("frontend", "api", "tactic", "emqx-main", "smtp-fixture")
        }
        services["docs"] = deepcopy(production)
        model = {"services": services}

        expose_rehearsal_ports(model)

        docs = model["services"]["docs"]
        self.assertEqual(
            {key: value for key, value in docs.items() if key != "ports"}, production
        )
        self.assertEqual(docs["deploy"]["update_config"]["order"], "start-first")
        self.assertTrue(
            any(
                port["target"] == 80 and port["published"] == 8087
                for port in docs["ports"]
            )
        )
        for name, service in model["services"].items():
            if (
                service.get("deploy", {}).get("update_config", {}).get("order")
                == "start-first"
            ):
                self.assertFalse(
                    any(port["mode"] == "host" for port in service.get("ports", [])),
                    f"{name}: a start-first replacement cannot reserve the old task's host port",
                )
