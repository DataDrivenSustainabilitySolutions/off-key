"""The public demo is a second, small stack that production's Traefik serves."""

import json
import tempfile
import unittest
from pathlib import Path

import test_deployment
import yaml
from support import ROOT, render

INVENTORIES = ROOT / "ansible/inventories"
# Settings the demo may set differently from production; everything else is shared.
DEMO_ONLY = {
    "offkey_env",
    "stack_name",
    "stack_dir",
    "demo_mode",
    "release_bootstrap_new_stack",
    "ambibox_ingress_enabled",
    "ingress_enabled",
    "ingress_admin_enabled",
    "landing_enabled",
    "release_public_urls",
    "system_live_enabled",
    "system_live_allowed_hosts",
    "demo_catalogue_file",
    "frontend_hostname",
    "frontend_base_url",
    "cors_allowed_origins",
    "tactic_docker_default_network",
    "tactic_docker_additional_networks",
    "tactic_radar_max_active_monitors",
    "telemetry_retention_days",
    # Production routes and links the demo; the demo routes nothing.
    "demo_hostname",
    "demo_stack_name",
    "demo_base_url",
}
LEFT_OUT = {
    "tailscale-ambibox",
    "mqtt-tailscale-bridge",
    "oauth2-proxy",
    "landing",
    "traefik",
    "cloudflared",
}


def settings(environment):
    path = INVENTORIES / environment / "group_vars/all/vars.yml"
    return yaml.safe_load(path.read_text())


class DemoInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="offkey-demo-")
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        (directory / "stack").mkdir()
        result, cls.inputs = render(directory, "demo")
        if result.returncode:
            raise AssertionError(f"Rendering the demo failed:\n{result.stdout}")
        cls.result = test_deployment.read_configuration(directory)
        cls.swarm = cls.result["swarm_config"]
        cls.services = cls.swarm["services"]

    def test_only_named_settings_differ_from_production(self):
        prod, demo = settings("prod"), settings("demo")
        differing = {
            key
            for key in prod.keys() | demo.keys()
            if prod.get(key, object()) != demo.get(key, object())
        }
        self.assertEqual(differing, DEMO_ONLY)
        self.assertNotIn("demo_hostname", demo)

    def test_only_application_services_run_in_their_own_stack(self):
        self.assertEqual(LEFT_OUT & self.services.keys(), set())
        for service in ("frontend", "api", "tactic", "postgres", "emqx-main"):
            self.assertIn(service, self.services)
        self.assertNotIn(
            "tailscale-ambibox-state", self.result["config"].get("volumes", {})
        )
        self.assertIsNone(self.result["landing_html"])
        self.assertIsNone(self.result["export"])
        names = self.result["deployment_secret_names"]
        self.assertNotIn("cloudflared_tunnel_token", names)
        self.assertEqual([key for key in names if "ambibox" in key], [])
        for name in names.values():
            self.assertTrue(name.startswith("off-key-demo_"), name)
        # Swarm config names are cluster-wide; production keeps the unprefixed ones.
        configs = [config["name"] for config in self.swarm["configs"].values()]
        self.assertEqual(len(configs), 1)
        self.assertTrue(configs[0].startswith("off-key-demo_emqx_security_cfg_"))

    def test_only_frontend_and_api_join_the_shared_demo_network(self):
        self.assertEqual(
            self.swarm["networks"]["demo-network"],
            {"external": True, "name": "aberration-demo"},
        )
        joined = {
            name
            for name, service in self.services.items()
            if "demo-network" in service.get("networks", {})
        }
        self.assertEqual(joined, {"frontend", "api"})
        tactic = self.services["tactic"]["environment"]
        self.assertEqual(
            tactic["TACTIC_DOCKER_DEFAULT_NETWORK"], "off-key-demo_emqx-network"
        )
        self.assertEqual(
            tactic["TACTIC_RADAR_SECRET_SERVICE"], "off-key-demo_mqtt-radar"
        )
        self.assertEqual(tactic["TACTIC_RADAR_MAX_ACTIVE_MONITORS"], "2")

    def test_guests_and_the_viewer_bootstrap_receive_the_viewer_account(self):
        api = self.services["api"]["environment"]
        tactic = self.services["tactic"]["environment"]
        self.assertEqual(api["DEMO_MODE"], "true")
        for environment in (api, tactic):
            self.assertEqual(
                environment["DEMO_VIEWER_EMAIL"], self.inputs["demo_viewer_email"]
            )
            self.assertEqual(
                environment["DEMO_VIEWER_PASSWORD"],
                self.inputs["demo_viewer_password"],
            )
        self.assertEqual(tactic["AMBIBOX_INGRESS_ENABLED"], "false")
        self.assertEqual(
            json.loads(tactic["SYSTEM_LIVE_ALLOWED_HOSTS"]),
            ["tie.digitraffic.fi", "meri.digitraffic.fi"],
        )
        self.assertEqual(api["FRONTEND_BASE_URL"], "https://demo.aberration.app")

    def test_a_weak_viewer_password_stops_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "stack").mkdir()
            result, _ = render(Path(directory), "demo", demo_viewer_password="short")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("demo_viewer_password", result.stdout)


if __name__ == "__main__":
    unittest.main()
