"""Render the optional public deployment with real Ansible and Compose."""

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from support import ROOT, load_script, render, run


class PublicDemoTests(unittest.TestCase):
    def test_public_link_precedes_dashboard_and_is_not_hidden_on_mobile(self):
        templates = Environment(
            loader=FileSystemLoader(ROOT / "stack"), undefined=StrictUndefined
        )
        context = {
            "ingress_base_domain": "example.org",
            "frontend_base_url": "https://dashboard.example.org",
            "docs_base_url": "",
            "demo_base_url": "https://demo.example.org",
        }
        html = templates.get_template("landing.html.j2").render(context)
        self.assertIn(
            '<a class="nav-cta" href="https://demo.example.org/sources">Demo <svg', html
        )
        self.assertLess(html.index(">Demo <svg"), html.index(">Dashboard "))
        context["demo_base_url"] = ""
        self.assertNotIn(
            ">Demo <svg", templates.get_template("landing.html.j2").render(context)
        )
        for name in ("landing.md.j2", "landing-llms.txt.j2"):
            with self.subTest(template=name):
                template = templates.get_template(name)
                self.assertIn(
                    "[Public demo](https://demo.example.org/sources)",
                    template.render(context | {"demo_base_url": "https://demo.example.org"}),
                )
                self.assertNotIn("[Public demo](", template.render(context))

    def test_demo_uses_its_own_networks_credentials_and_ingress(self):
        demo = yaml.safe_load(
            (ROOT / "ansible/inventories/demo/group_vars/all/vars.yml").read_text()
        )
        demo.pop("stack_dir")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result, _ = render(
                directory, "demo", **demo, demo_viewer_password="viewer-" + "v" * 40
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            stack = directory / "stack"
            selected = json.loads((stack / "validation.json").read_text())
            args = [
                "docker",
                "compose",
                "--project-name",
                "off-key-demo",
                "--env-file",
                str(stack / ".env"),
            ]
            for file in selected["compose_files"]:
                args.extend(["-f", file])
            model = json.loads(run(*args, "config", "--format", "json").stdout)
            compiled = load_script("compile_stack").compile_stack(model)
            run("docker", "stack", "config", "-c", "-", input=json.dumps(compiled))
            services = model["services"]
            # One labelled worker runs the demo; only the socket proxy needs a manager.
            placed = {
                name: service["deploy"]["placement"]["constraints"]
                for name, service in services.items()
                if service.get("deploy", {}).get("placement")
            }
            self.assertEqual(placed.pop("socket-proxy"), ["node.role == manager"])
            self.assertTrue(placed)
            for name, constraints in placed.items():
                self.assertEqual(constraints, ["node.labels.offkey-demo == true"], name)
            self.assertTrue({"demo-relay", "demo-broker"} <= services.keys())
            self.assertTrue(
                {
                    "landing",
                    "docs",
                    "oauth2-proxy",
                    "broker-route",
                    "grafana",
                }.isdisjoint(services)
            )
            self.assertTrue(model["networks"]["demo-source-network"]["internal"])
            self.assertNotIn("ports", services["demo-broker"])
            self.assertEqual(services["api"]["environment"]["DEMO_MODE"], "true")
            self.assertNotIn("DEMO_VIEWER_PASSWORD", services["api"]["environment"])
            tactic = services["tactic"]["environment"]
            self.assertEqual(
                tactic["TACTIC_DOCKER_DEFAULT_NETWORK"], "off-key-demo_emqx-network"
            )
            self.assertEqual(
                tactic["TACTIC_DOCKER_ADDITIONAL_NETWORKS"], "off-key-demo_app-network"
            )
            self.assertNotIn("PONTOS_TOKEN", tactic)
            self.assertEqual(
                json.loads(tactic["DEMO_FEEDS_JSON"]), demo["demo_feed_selection"]
            )
            self.assertEqual(
                services["demo-relay"]["environment"]["DEMO_FEEDS_JSON"],
                tactic["DEMO_FEEDS_JSON"],
            )
            self.assertNotIn("PONTOS_TOKEN_FILE", services["demo-relay"]["environment"])
            self.assertNotIn("pontos_token", selected["deployment_secret_names"])
            routes = yaml.safe_load((stack / "traefik-dynamic.yml").read_text())["http"]
            self.assertEqual(set(routes["routers"]), {"frontend", "api"})
            self.assertEqual(set(routes["services"]), {"frontend", "api"})


if __name__ == "__main__":
    unittest.main()
