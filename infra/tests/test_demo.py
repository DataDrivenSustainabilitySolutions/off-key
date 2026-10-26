"""The public demo inventory renders production's stack minus vendor and admin ingress."""

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
    "demo_mode",
    "ambibox_ingress_enabled",
    "ingress_admin_enabled",
    "landing_enabled",
    "release_public_urls",
    "system_live_enabled",
    "system_live_allowed_hosts",
    "frontend_hostname",
    "frontend_base_url",
    "cors_allowed_origins",
    "tactic_radar_max_active_monitors",
    "telemetry_retention_days",
}
LEFT_OUT = {"tailscale-ambibox", "mqtt-tailscale-bridge", "oauth2-proxy", "landing"}


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
        cls.services = cls.result["swarm_config"]["services"]

    def test_only_named_settings_differ_from_production(self):
        prod, demo = settings("prod"), settings("demo")
        differing = {
            key
            for key in prod.keys() | demo.keys()
            if prod.get(key, object()) != demo.get(key, object())
        }
        self.assertEqual(differing, DEMO_ONLY)

    def test_vendor_admin_and_landing_services_are_left_out(self):
        self.assertEqual(LEFT_OUT & self.services.keys(), set())
        for service in ("traefik", "cloudflared", "frontend", "api", "tactic"):
            self.assertIn(service, self.services)
        self.assertNotIn(
            "tailscale-ambibox-state", self.result["config"].get("volumes", {})
        )
        self.assertIsNone(self.result["landing_html"])
        self.assertIsNone(self.result["export"])
        secrets = self.result["deployment_secret_names"]
        self.assertEqual([name for name in secrets if "ambibox" in name], [])

    def test_only_the_demo_hostname_is_routed(self):
        routers = self.result["routes"]["routers"]
        self.assertEqual(set(routers), {"frontend", "api"})
        self.assertEqual(routers["frontend"]["rule"], "Host(`demo.aberration.app`)")
        self.assertTrue(
            routers["api"]["rule"].startswith("Host(`demo.aberration.app`)")
        )
        self.assertEqual(set(self.result["routes"]["services"]), {"frontend", "api"})

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
