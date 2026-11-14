"""Render the optional public deployment with real Ansible and Compose."""

import json
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from support import ROOT, ansible, load_script, render, run


class PublicDemoTests(unittest.TestCase):
    def test_public_probe_requires_the_configured_cloudflare_challenge(self):
        # Real HTTP responses exercise uri's header normalization and the task's
        # success conditions, including access-denied and missing-gate failures.
        cases = {
            # status, cf-mitigated, requires challenge, expected success
            "public": (200, None, False, True),
            "redirect": (302, None, False, True),
            "forbidden": (403, None, False, False),
            "challenge": (403, "challenge", True, True),
            "plain-denial": (403, None, True, False),
            "missing-gate": (200, None, True, False),
            "wrong-mitigation": (403, "block", True, False),
            "upstream-error": (503, "challenge", True, False),
            "docs-redirect": (302, None, False, False),
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, mitigation, _, _ = cases[self.path.strip("/")]
                self.send_response(status)
                if mitigation is not None:
                    self.send_header("cf-mitigated", mitigation)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                results = directory / "results.json"
                (probe,) = yaml.safe_load(
                    (
                        ROOT / "ansible/roles/stack_deploy/tasks/public_routes.yml"
                    ).read_text()
                )
                # Keep failed cases and exercise until; zero retries skips it.
                probe.update(ignore_errors=True, retries=1, delay=0)
                playbook = directory / "probe.yml"
                playbook.write_text(
                    yaml.safe_dump(
                        [
                            {
                                "hosts": "localhost",
                                "gather_facts": False,
                                "connection": "local",
                                "become": False,
                                "vars": {
                                    "ansible_python_interpreter": sys.executable,
                                    "release_public_urls": [
                                        f"{base}/{name}" for name in cases
                                    ],
                                    "release_public_challenge_urls": [
                                        f"{base}/{name}"
                                        for name, case in cases.items()
                                        if case[2]
                                    ],
                                    "ingress_base_domain": "unused.example.org",
                                    "frontend_base_url": f"{base}/public",
                                    "docs_base_url": f"{base}/docs-redirect",
                                },
                                "tasks": [
                                    probe,
                                    {
                                        "copy": {
                                            "dest": str(results),
                                            "content": "{{ public_route.results | to_json }}",
                                            "mode": "0600",
                                        }
                                    },
                                ],
                            }
                        ]
                    )
                )
                ansible("playbook", "-i", "localhost,", str(playbook))
                observed = {
                    result["item"].removeprefix(base + "/"): not result["failed"]
                    for result in json.loads(results.read_text())
                }
                self.assertEqual(
                    observed, {name: case[3] for name, case in cases.items()}
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

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
                    template.render(
                        context | {"demo_base_url": "https://demo.example.org"}
                    ),
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
