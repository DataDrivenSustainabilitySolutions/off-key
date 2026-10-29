"""Integration checks for actual Ansible rendering and Docker config parsing."""

import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

import yaml
from support import CLIENTS, ROOT, TOKEN, ansible, discovery, load_script, render, run

compiler = load_script("compile_stack")

MOUNTS = {
    "persist_postgres": ("postgres", "/var/lib/postgresql/data"),
    "persist_emqx_data": ("emqx-main", "/opt/emqx/data"),
    "persist_emqx_log": ("emqx-main", "/opt/emqx/log"),
}


def read_configuration(directory):
    stack = directory / "stack"
    manifest = json.loads((stack / "validation.json").read_text())
    command = ["docker", "compose", "--env-file", str(stack / ".env")]
    for path in manifest["compose_files"]:
        command += ["-f", path]
    # Shell variables outrank --env-file. Keep local credentials/settings out of
    # the rendered model, which must depend only on the supplied example inputs.
    env = os.environ | {"OFFKEY_REVIEW_SENTINEL": "unexpected-expansion"}
    for line in (stack / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            env.pop(line.split("=", 1)[0], None)
    config = json.loads(run(*command, "config", "--format", "json", env=env).stdout)
    # Submit the exact resolved JSON model through the same boundary as deployment.
    compatible = json.dumps(compiler.compile_stack(json.loads(json.dumps(config))))
    swarm_config = yaml.safe_load(
        run("docker", "stack", "config", "-c", "-", input=compatible, env=env).stdout
    )
    return {
        "config": config,
        "swarm_config": swarm_config,
        "deployment_secret_material": manifest["deployment_secret_material"],
        "deployment_secret_names": manifest["deployment_secret_names"],
        "routes": yaml.safe_load((stack / "traefik-dynamic.yml").read_text())["http"],
        "landing_html": (stack / "landing.html").read_text()
        if (stack / "landing.html").exists()
        else None,
        "landing_llms": (stack / "landing-llms.txt").read_text()
        if (stack / "landing-llms.txt").exists()
        else None,
        "landing_markdown": (stack / "landing.md").read_text()
        if (stack / "landing.md").exists()
        else None,
        "export": (stack / "broker-route.exports").read_text().strip()
        if (stack / "broker-route.exports").exists()
        else None,
        "persistence_file": (stack / "docker-compose.persistence.yml").exists(),
        "mailpit_files": [
            path.name for path in stack.iterdir() if "mailpit" in path.name
        ],
    }


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="offkey-validation-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / "stack").mkdir()
        (directory / "stack/.env.mailpit").write_text("MP_UI_AUTH=legacy-fixture\n")
        all_off = dict.fromkeys(MOUNTS, False)
        # Reuse the destination to exercise removal of stale overlays and keep
        # the export path constant while checking volume identity/rotation.
        cases = [
            ("prod", "prod", {}),
            ("prod-repeat", "prod", {}),
            (
                "prod-token-whitespace",
                "prod",
                {"cloudflare_tunnel_token": " \t" + TOKEN + "\r\n"},
            ),
            (
                "literal-credentials",
                "prod",
                {
                    "postgres_password": "literal-$OFFKEY_REVIEW_SENTINEL-${OFFKEY_REVIEW_SENTINEL}-'\"\\#=\n-trailing\\",
                    "jwt_secret": "synthetic-jwt-$OFFKEY_REVIEW_SENTINEL-'\"\\#=\n-tail",
                    "oauth2_client_secret": "literal-${OFFKEY_REVIEW_SENTINEL}-'\"\\#=\n-tail",
                    "broker_route_login": {
                        "username": "route-${OFFKEY_REVIEW_SENTINEL}",
                        "password": "literal-${OFFKEY_REVIEW_SENTINEL}-'\"\\#=\n-tail",
                    },
                },
            ),
            ("prod-moved", "prod", {"broker_route_nfs_addr": "100.100.10.99"}),
            ("prod-rotated", "prod", {"cloudflare_tunnel_token": TOKEN + "rotated"}),
            ("prod-ephemeral", "prod", all_off),
            ("prod-mixed", "prod", all_off | {"persist_emqx_log": True}),
            ("prod-collection-disabled", "prod", {"mqtt_telemetry_enabled": "false"}),
            (
                "prod-ingress-disabled",
                "prod",
                {
                    "broker_route_enabled": False,
                    "system_collection_enabled": False,
                },
            ),
        ]
        cls.results = {}
        for name, environment, overrides in cases:
            result, inputs = render(directory, environment, **overrides)
            if result.returncode:
                raise AssertionError(
                    f"Rendering {name} failed:\n{result.stdout}\n{result.stderr}"
                )
            cls.results[name] = read_configuration(directory) | {
                "inputs": inputs,
                "log": result.stdout,
            }

    def test_credentials_remain_literal_through_compose_and_swarm(self):
        result = self.results["literal-credentials"]
        services, inputs = result["swarm_config"]["services"], result["inputs"]
        for service in ("postgres", "tactic", "db-sync", "mqtt-proxy"):
            self.assertEqual(
                services[service]["environment"]["POSTGRES_PASSWORD"],
                inputs["postgres_password"],
            )
        for service in ("api", "tactic"):
            self.assertEqual(
                services[service]["environment"]["JWT_SECRET"], inputs["jwt_secret"]
            )
        self.assertEqual(
            services["oauth2-proxy"]["environment"]["OAUTH2_PROXY_CLIENT_SECRET"],
            inputs["oauth2_client_secret"],
        )
        self.assertNotIn("TS_AUTHKEY", services["broker-route"]["environment"])
        routes = json.loads(
            result["deployment_secret_material"]["system_broker_routes"]
        )
        self.assertEqual(routes[0]["credential"], inputs["broker_route_login"])

    def test_route_node_settings_reach_compose_and_swarm(self):
        for name, result in self.results.items():
            if result["inputs"].get("broker_route_enabled") is False:
                # Without a broker route its overlay is left out entirely.
                self.assertNotIn("broker-route", result["config"]["services"])
                self.assertNotIn(
                    "broker-route-state", result["config"].get("volumes", {})
                )
                self.assertNotIn(
                    "system_broker_routes", result["deployment_secret_material"]
                )
                continue
            for model in ("config", "swarm_config"):
                with self.subTest(case=name, model=model):
                    environment = result[model]["services"]["broker-route"][
                        "environment"
                    ]
                    self.assertEqual(
                        environment["TS_EXTRA_ARGS"],
                        result["inputs"]["broker_route_tailscale_extra_args"],
                    )
                    self.assertEqual(
                        environment["TS_HOSTNAME"],
                        result["inputs"]["broker_route_tailscale_hostname"],
                    )

    def test_production_route_identity_changes_only_on_purpose(self):
        # These values decide which node identity production uses and how it
        # joins the source network. A change re-registers or strands the live
        # node, so update the digest only together with a planned migration.
        values = yaml.safe_load(
            (ROOT / "ansible/inventories/prod/group_vars/all/vars.yml").read_text()
        )
        identity = {
            key: values.get(key)
            for key in (
                "broker_route_name",
                "broker_route_host_suffixes",
                "broker_route_hosts",
                "broker_route_require_tls",
                "broker_route_tailscale_extra_args",
                "broker_route_tailscale_hostname",
                "broker_route_state_dir",
                "broker_route_seed_dir",
            )
        }
        self.assertEqual(
            hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
            "357272cb54061246f437fd3ffa11854eb334459b15b62787209400e523aa3a72",
        )

    def test_production_route_covers_the_inventory_hosts_through_the_node(self):
        inventory = yaml.safe_load(
            (ROOT / "ansible/inventories/prod/group_vars/all/vars.yml").read_text()
        )
        result = self.results["prod"]
        routes = json.loads(
            result["deployment_secret_material"]["system_broker_routes"]
        )
        self.assertEqual(
            routes,
            [
                {
                    "name": inventory["broker_route_name"],
                    "hosts": [],
                    "host_suffixes": inventory["broker_route_host_suffixes"],
                    "socks_proxy": {"host": "broker-route", "port": 1055},
                    "require_tls": False,
                    "credential": result["inputs"]["broker_route_login"],
                }
            ],
        )
        # The route secret alone carries hosts and login; TACTIC reaches the
        # SOCKS proxy over the network both services share.
        services = result["config"]["services"]
        self.assertTrue(
            set(services["broker-route"]["networks"])
            & set(services["tactic"]["networks"])
        )

    def test_every_production_image_is_immutable_and_radar_matches_runtime(self):
        config = self.results["prod"]["config"]
        release = yaml.safe_load(
            (ROOT / "ansible/inventories/prod/group_vars/all/release.yml").read_text()
        )["release"]
        for name, service in config["services"].items():
            with self.subTest(service=name):
                self.assertRegex(service["image"], r"@sha256:[0-9a-f]{64}$")
                self.assertIn(service["image"], release["images"].values())
        self.assertEqual(
            config["services"]["tactic"]["environment"]["TACTIC_RADAR_IMAGE"],
            release["images"]["mqtt_radar"],
        )

    def test_credentials_are_scoped_to_the_services_that_need_them(self):
        allowed = {
            "JWT_SECRET": {"api", "tactic"},
            "INTERNAL_API_SECRET": {"api", "tactic"},
            "POSTGRES_PASSWORD": {"postgres", "tactic", "db-sync", "mqtt-proxy"},
            "EMAIL_PASSWORD": {"api", "tactic"},
            "OAUTH2_PROXY_CLIENT_SECRET": {"oauth2-proxy"},
            "OAUTH2_PROXY_COOKIE_SECRET": {"oauth2-proxy"},
        }
        for case, result in self.results.items():
            services = result["config"]["services"]
            for key, expected in allowed.items():
                actual = {
                    name
                    for name, service in services.items()
                    if key in service.get("environment", {})
                }
                with self.subTest(case=case, credential=key):
                    self.assertEqual(actual, expected)
            self.assertEqual(
                services["api"]["environment"]["INTERNAL_API_SECRET"],
                services["tactic"]["environment"]["INTERNAL_API_SECRET"],
            )
            self.assertEqual(services["frontend"].get("environment", {}), {})
            # The secret template never runs; TACTIC copies only its secrets.
            self.assertEqual(services["mqtt-radar"].get("environment", {}), {})

    def test_production_uses_resend(self):
        expected = {
            "SMTP_SERVER": "smtp.resend.com",
            "SMTP_PORT": "587",
            "EMAIL_USERNAME": "resend",
            "EMAIL_FROM": "no-reply@aberration.app",
            "MAIL_STARTTLS": "True",
            "MAIL_SSL_TLS": "False",
            "USE_CREDENTIALS": "True",
            "VALIDATE_CERTS": "True",
            "EMAIL_PASSWORD": self.results["prod"]["inputs"]["email_password"],
        }
        for service in ("api", "tactic"):
            settings = self.results["prod"]["config"]["services"][service][
                "environment"
            ]
            for key, value in expected.items():
                self.assertEqual(settings[key], value)

    def test_production_retires_mailpit(self):
        for name, result in self.results.items():
            with self.subTest(case=name):
                config = result["config"]
                routes = result["routes"]
                self.assertNotIn("mailpit", config["services"])
                self.assertNotIn("mailpit", routes["routers"])
                self.assertNotIn("mailpit", routes["services"])
                self.assertEqual(result["mailpit_files"], [])
                self.assertNotIn("mailpit_data", config.get("volumes", {}))
        release = yaml.safe_load(
            (ROOT / "ansible/inventories/prod/group_vars/all/release.yml").read_text()
        )["release"]
        self.assertNotIn("mailpit", release["images"])

    def test_deployment_retires_only_named_production_services_and_can_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            services = root / "services.json"
            original = [
                "off-key_api",
                "off-key_mailpit",
                "off-key_mailpit-other",
                "off-key_tailscale-dev-proxy",
                "off-key_tailscale-dev-proxy-other",
                "radar-runtime",
            ]
            services.write_text(json.dumps(original))
            docker = root / "docker"
            docker.write_text(
                f"#!{sys.executable}\n"
                "import json, pathlib, sys\n"
                f"state = pathlib.Path({str(services)!r})\n"
                "args = sys.argv[1:]\n"
                "if args[:2] == ['service', 'ls']:\n"
                "    if 'label=managed_by=tactic' not in args:\n"
                "        print('\\n'.join(json.loads(state.read_text())))\n"
                "elif args[:2] == ['service', 'rm']:\n"
                "    assert args[:2] == ['service', 'rm'] and len(args) == 3, args\n"
                "    assert args[2] in {'off-key_mailpit', 'off-key_tailscale-dev-proxy'}, args\n"
                "    current = json.loads(state.read_text())\n"
                "    current.remove(args[2])\n"
                "    state.write_text(json.dumps(current))\n"
                "elif args[:2] == ['service', 'inspect']: sys.exit(1)\n"
                "elif args[0] == 'compose':\n"
                "    print(json.dumps({'services': {}}) if args[-2:] == ['--format', 'json'] else 'services: {}')\n"
                "elif args[:2] == ['stack', 'deploy']:\n"
                "    assert '--prune' not in args\n"
                "    assert json.loads(pathlib.Path(args[args.index('-c') + 1]).read_text()) == {'services': {}}\n"
                "else: raise AssertionError(args)\n"
            )
            docker.chmod(0o755)
            playbook = root / "deploy.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "connection": "local",
                            "gather_facts": False,
                            "become": False,
                            "environment": {"PATH": f"{root}:{os.environ['PATH']}"},
                            "vars": {
                                "ansible_python_interpreter": sys.executable,
                                "stack_name": "off-key",
                                "stack_dir": directory,
                                "stack_compose_files": ["fixture.yml"],
                            },
                            "tasks": [
                                {
                                    "include_role": {
                                        "name": "stack_deploy",
                                        "tasks_from": "retire",
                                    }
                                }
                            ],
                        }
                    ]
                )
            )
            # Retiring twice must be idempotent: the repeat finds nothing to remove.
            for attempt in ("first", "repeat"):
                with self.subTest(attempt=attempt):
                    ansible(
                        "playbook",
                        "-i",
                        "localhost,",
                        str(playbook),
                        "-e",
                        "offkey_env=prod",
                    )
                    expected = [
                        name
                        for name in original
                        if name
                        not in {"off-key_mailpit", "off-key_tailscale-dev-proxy"}
                    ]
                    self.assertEqual(json.loads(services.read_text()), expected)

    def test_resend_rejects_placeholder_credentials_and_insecure_transport(self):
        for overrides, expected_error in (
            ({"email_password": ""}, "effective email_password"),
            ({"email_password": "re_xxxxxxxxx"}, "effective email_password"),
            (
                {"email_password": "invalid-secret-must-stay-hidden"},
                "effective email_password",
            ),
            ({"email_username": ""}, "email_username == 'resend'"),
            ({"mail_starttls": "False"}, "mail_starttls | bool"),
            ({"validate_certs": "False"}, "validate_certs | bool"),
            ({"use_credentials": "False"}, "use_credentials | bool"),
        ):
            with (
                self.subTest(overrides=overrides),
                tempfile.TemporaryDirectory() as directory,
            ):
                result, inputs = render(Path(directory), "prod", **overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stdout)
                if inputs["email_password"]:
                    self.assertNotIn(
                        inputs["email_password"], result.stdout + result.stderr
                    )
                self.assertFalse((Path(directory) / "stack").exists())

    def test_nfs_clients_can_mount_the_rendered_export(self):
        for name, result in self.results.items():
            if result["inputs"].get("broker_route_enabled") is False:
                continue
            with self.subTest(case=name):
                volume = result["config"]["volumes"]["broker-route-state"]
                path, *entries = result["export"].split()
                self.assertEqual(volume["driver_opts"]["device"], f":{path}")
                self.assertIn(
                    f"addr={result['inputs']['broker_route_nfs_addr']},",
                    volume["driver_opts"]["o"],
                )
                allowed = []
                for entry in entries:
                    match = re.fullmatch(r"([^()]+)\(([^()]+)\)", entry)
                    self.assertIsNotNone(match, entry)
                    network = ipaddress.ip_network(match[1])
                    self.assertEqual(network.prefixlen, 32)
                    self.assertIn("rw", match[2].split(","))
                    self.assertIn("no_root_squash", match[2].split(","))
                    allowed.append(str(network.network_address))
                self.assertCountEqual(allowed, CLIENTS)

    def test_nfs_volume_is_stable_until_endpoint_changes(self):
        def volume(case):
            return self.results[case]["config"]["volumes"]["broker-route-state"]

        self.assertEqual(volume("prod"), volume("prod-repeat"))
        self.assertIn("changed=0", self.results["prod-repeat"]["log"])
        self.assertNotEqual(volume("prod")["name"], volume("prod-moved")["name"])
        self.assertEqual(
            volume("prod")["driver_opts"]["device"],
            volume("prod-moved")["driver_opts"]["device"],
        )

    def test_persistence_toggles_control_mounts_and_overlay_removal(self):
        expected = {
            "prod": set(MOUNTS),
            "prod-ephemeral": set(),
            "prod-mixed": {"persist_emqx_log"},
        }
        for name, enabled in expected.items():
            with self.subTest(case=name):
                result = self.results[name]
                self.assertEqual(result["persistence_file"], bool(enabled))
                for toggle, (service, target) in MOUNTS.items():
                    mounts = result["config"]["services"][service].get("volumes", [])
                    self.assertEqual(
                        any(m["target"] == target for m in mounts), toggle in enabled
                    )

    def test_tunnel_uses_a_versioned_secret_only_in_production(self):
        for name, result in self.results.items():
            with self.subTest(case=name):
                config = result["config"]
                tunnel = config["services"]["cloudflared"]
                secret = tunnel["secrets"][0]
                target = PurePosixPath("/run/secrets") / secret["target"]
                self.assertEqual(str(target), "/run/secrets/cloudflared_tunnel_token")
                token_argument = tunnel["command"].index("--token-file") + 1
                self.assertEqual(tunnel["command"][token_argument], str(target))
                self.assertTrue(config["secrets"][secret["source"]]["external"])
                token = result["inputs"]["cloudflare_tunnel_token"].strip()
                expected_name = (
                    "off-key_cloudflared_tunnel_token_"
                    + hashlib.sha256(token.encode()).hexdigest()[:12]
                )
                self.assertEqual(
                    config["secrets"][secret["source"]]["name"], expected_name
                )
                self.assertEqual(
                    result["deployment_secret_material"]["cloudflared_tunnel_token"],
                    token,
                )
                self.assertNotIn(
                    result["inputs"]["cloudflare_tunnel_token"], json.dumps(config)
                )
        original = self.results["prod"]["config"]["secrets"]
        rotated = self.results["prod-rotated"]["config"]["secrets"]
        self.assertNotEqual(original, rotated)

    def test_deployment_secret_creation_preserves_bytes_and_is_idempotent(self):
        rendered = self.results["prod-token-whitespace"]
        material = rendered["deployment_secret_material"]
        names = rendered["deployment_secret_names"]
        expected = {
            f"off-key_{key}_{hashlib.sha256(value.encode()).hexdigest()[:12]}": value
            for key, value in material.items()
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "secrets.json"
            state.write_text("{}")
            docker = root / "docker"
            docker.write_text(
                f"#!{sys.executable}\n"
                "import json, pathlib, sys\n"
                f"state = pathlib.Path({str(state)!r})\n"
                "args = sys.argv[1:]\n"
                "secrets = json.loads(state.read_text())\n"
                "if args[:2] == ['secret', 'inspect']:\n"
                "    sys.exit(0 if args[2] in secrets else 1)\n"
                "assert args[:2] == ['secret', 'create'] and args[3:] == ['-'], args\n"
                "assert args[2] not in secrets, 'secret was recreated'\n"
                "secrets[args[2]] = sys.stdin.read()\n"
                "state.write_text(json.dumps(secrets))\n"
            )
            docker.chmod(0o755)
            playbook = root / "secrets.yml"
            playbook.write_text(
                """- hosts: localhost
  connection: local
  gather_facts: false
  become: false
  environment:
    PATH: "{{ fixture_path }}"
  tasks:
    - include_role:
        name: stack_prepare
        tasks_from: secrets
"""
            )
            variables = {
                "ansible_python_interpreter": sys.executable,
                "deployment_secret_material": material,
                "deployment_secret_names": names,
                "fixture_path": f"{root}:{os.environ['PATH']}",
            }
            args = (
                "playbook",
                "-i",
                "localhost,",
                str(playbook),
                "-e",
                json.dumps(variables),
            )
            ansible(*args)
            repeated = ansible(*args)
            self.assertIn("changed=0", repeated.stdout)
            self.assertEqual(json.loads(state.read_text()), expected)

    def test_production_secrets_are_scoped_to_the_services_that_need_them(self):
        expected = {
            "cloudflared": {
                "cloudflared_tunnel_token": "/run/secrets/cloudflared_tunnel_token",
            },
            "emqx-main": {
                "emqx_server_cert": "emqx_server_cert.pem",
                "emqx_server_key": "emqx_server_key.pem",
                "emqx_auth_users": "emqx_auth_users.json",
            },
            "mqtt-proxy": {
                "emqx_ca_cert": "EMQX_CA_CERT",
                "mqtt_proxy_password": "MQTT_APIKEY",
            },
            "mqtt-radar": {
                "emqx_ca_cert": "EMQX_CA_CERT",
                "mqtt_radar_password": "RADAR_MQTT_API_KEY",
                "radar_checkpoint_secret": "RADAR_CHECKPOINT_SECRET",
            },
            "tactic": {
                "emqx_ca_cert": "EMQX_CA_CERT",
                "mqtt_proxy_password": "SYSTEM_COLLECTION_MQTT_API_KEY",
                "system_broker_routes": "SYSTEM_BROKER_ROUTES",
            },
        }
        result = self.results["prod"]
        self.assertEqual(
            set(result["config"]["secrets"]), set(result["deployment_secret_material"])
        )
        for model in ("config", "swarm_config"):
            for service, definition in result[model]["services"].items():
                with self.subTest(model=model, service=service):
                    actual = {
                        secret["source"]: secret["target"]
                        for secret in definition.get("secrets", [])
                    }
                    self.assertEqual(actual, expected.get(service, {}))

    def test_public_site_and_dashboard_are_separate(self):
        result = self.results["prod"]
        config = result["config"]
        routes = result["routes"]
        routers = routes["routers"]
        dashboard = "https://dashboard.aberration.app"
        self.assertEqual(routers["landing"]["rule"], "Host(`aberration.app`)")
        self.assertEqual(routers["landing"]["service"], "landing")
        self.assertEqual(
            routers["frontend"]["rule"], "Host(`dashboard.aberration.app`)"
        )
        self.assertEqual(
            routers["api"]["rule"],
            "Host(`dashboard.aberration.app`) && PathPrefix(`/api`)",
        )
        for path_router, fallback in (("api", "frontend"), ("legacy-app", "landing")):
            # Traefik uses rule length when priority is omitted.
            self.assertGreater(
                routers[path_router].get("priority", len(routers[path_router]["rule"])),
                routers[fallback].get("priority", len(routers[fallback]["rule"])),
            )
        api_env = config["services"]["api"]["environment"]
        self.assertEqual(api_env["FRONTEND_BASE_URL"], dashboard)
        self.assertEqual(json.loads(api_env["CORS_ALLOWED_ORIGINS"]), [dashboard])
        self.assertIn(f'href="{dashboard}/"', result["landing_html"])
        self.assertNotIn("{{", result["landing_html"])
        # Production links the public demo from the landing page.
        self.assertIn('href="https://demo.aberration.app/"', result["landing_html"])

        landing = config["services"]["landing"]
        self.assertEqual(set(landing["networks"]), {"public-network"})
        self.assertFalse(landing.get("environment"))
        self.assertFalse(landing.get("secrets"))
        self.assertEqual(
            {item["source"]: item["target"] for item in landing["configs"]},
            {
                "landing_page": "/usr/share/nginx/html/index.html",
                "landing_markdown": "/usr/share/nginx/html/index.md",
                "landing_llms": "/usr/share/nginx/html/llms.txt",
                "landing_nginx": "/etc/nginx/conf.d/default.conf",
            },
        )
        for name in ("page", "markdown", "llms", "nginx"):
            self.assertRegex(
                config["configs"][f"landing_{name}"]["name"],
                rf"^landing_{name}_[0-9a-f]{{12}}$",
            )
        headers = routes["middlewares"]["landing-headers"]["headers"]
        self.assertEqual(
            headers["customRequestHeaders"], {"Cookie": "", "Authorization": ""}
        )
        self.assertIn("default-src 'none'", headers["contentSecurityPolicy"])

    def test_landing_page_publishes_llms_txt_and_markdown(self):
        result = self.results["prod"]
        llms, markdown = result["landing_llms"], result["landing_markdown"]
        # llmstxt.org: an H1 name, then a blockquote summary.
        self.assertTrue(llms.startswith("# Aberration\n\n> "))
        for text in (llms, markdown):
            self.assertNotIn("{{", text)
            self.assertIn("https://dashboard.aberration.app/api/openapi.json", text)
            self.assertIn("https://demo.aberration.app/api/v1/monitors", text)
        self.assertIn("(https://aberration.app/index.md)", llms)
        self.assertIn(
            "https://datadrivensustainabilitysolutions.github.io/off-key/llms.txt",
            llms,
        )
        html = result["landing_html"]
        self.assertIn('id="agents"', html)
        self.assertIn('href="/llms.txt"', html)
        self.assertIn('type="text/markdown" href="/index.md"', html)

    def test_old_account_links_redirect_to_the_dashboard(self):
        routes = self.results["prod"]["routes"]
        router = routes["routers"]["legacy-app"]
        self.assertEqual(router["middlewares"], ["dashboard-redirect"])
        pattern = re.search(r"PathRegexp\(`(.*?)`\)", router["rule"]).group(1)
        for path in ("/login", "/verify", "/reset-password", "/details/charger-1"):
            self.assertIsNotNone(re.search(pattern, path))
        for path in ("/", "/api/v1/auth/login", "/assets/index.js", "/verification"):
            self.assertIsNone(re.search(pattern, path))
        redirect = routes["middlewares"]["dashboard-redirect"]["redirectRegex"]
        self.assertEqual(
            redirect["replacement"], "https://dashboard.aberration.app/${1}"
        )
        match = re.search(
            redirect["regex"], "https://aberration.app/verify?token=a%2Fb&next=%2F"
        )
        self.assertEqual(match.group(1), "verify?token=a%2Fb&next=%2F")
        self.assertTrue(redirect["permanent"])

    def test_production_mqtt_clients_use_tls_and_targeted_secrets(self):
        config = self.results["prod"]["config"]
        proxy = config["services"]["mqtt-proxy"]
        radar = config["services"]["mqtt-radar"]
        tactic = config["services"]["tactic"]
        broker = config["services"]["emqx-main"]
        self.assertEqual(proxy["environment"]["ENVIRONMENT"], "production")
        self.assertEqual(proxy["environment"]["MQTT_BROKER_PORT"], "8883")
        self.assertEqual(proxy["environment"]["MQTT_USE_TLS"], "true")
        self.assertEqual(proxy["environment"]["MQTT_USE_AUTH"], "true")
        self.assertEqual(proxy["environment"]["MQTT_USERNAME"], "offkey-proxy")
        self.assertNotIn("MQTT_APIKEY", proxy["environment"])
        self.assertEqual(
            proxy["environment"]["MQTT_CA_FILE"], "/run/secrets/EMQX_CA_CERT"
        )
        self.assertNotIn("environment", radar)
        self.assertEqual(
            tactic["environment"]["SYSTEM_COLLECTION_MQTT_USERNAME"], "offkey-proxy"
        )
        self.assertNotIn("SYSTEM_COLLECTION_MQTT_API_KEY", tactic["environment"])
        self.assertEqual(
            tactic["environment"]["SYSTEM_COLLECTION_MQTT_CA_FILE"],
            "/run/secrets/EMQX_CA_CERT",
        )
        self.assertEqual(
            tactic["environment"]["TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT"], "8883"
        )
        self.assertEqual(
            tactic["environment"]["TACTIC_RADAR_DEFAULT_MQTT_USE_TLS"], "true"
        )
        self.assertEqual(
            {secret["target"] for secret in radar["secrets"]},
            {"EMQX_CA_CERT", "RADAR_MQTT_API_KEY", "RADAR_CHECKPOINT_SECRET"},
        )
        self.assertEqual(
            {secret["target"] for secret in broker["secrets"]},
            {
                "emqx_server_cert.pem",
                "emqx_server_key.pem",
                "emqx_auth_users.json",
            },
        )
        rendered = json.dumps(config)
        self.assertNotIn(
            self.results["prod"]["inputs"]["mqtt_proxy_password"], rendered
        )
        self.assertNotIn(
            self.results["prod"]["inputs"]["mqtt_radar_password"], rendered
        )
        controller = config["services"]["tactic"]
        self.assertIn("emqx-network", controller["networks"])
        self.assertEqual(controller["environment"]["SYSTEM_LIVE_ENABLED"], "true")
        self.assertIn("app-network", config["services"]["broker-route"]["networks"])
        self.assertNotIn("MQTT_SOURCE_TOPICS", proxy["environment"])
        self.assertEqual(
            config["services"]["broker-route"]["image"],
            yaml.safe_load(
                (
                    ROOT / "ansible/inventories/prod/group_vars/all/release.yml"
                ).read_text()
            )["release"]["images"]["tailscale"],
        )
        for value in self.results["prod"]["inputs"]["broker_route_login"].values():
            self.assertNotIn(value, rendered)

    def test_collection_controller_is_provisioned_in_every_environment(self):
        for environment in ("prod",):
            with self.subTest(environment=environment):
                config = self.results[environment]["config"]
                services = config["services"]
                self.assertEqual(
                    services["mqtt-proxy"]["environment"]["MQTT_TELEMETRY_ENABLED"],
                    "true",
                )
                controller = services["tactic"]
                self.assertEqual(
                    {secret["target"] for secret in controller["secrets"]},
                    {
                        "EMQX_CA_CERT",
                        "SYSTEM_BROKER_ROUTES",
                        "SYSTEM_COLLECTION_MQTT_API_KEY",
                    },
                )
                # The collection controller needs no EMQX management API.
                self.assertNotIn(
                    "EMQX_API_KEY__BOOTSTRAP_FILE",
                    services["emqx-main"].get("environment", {}),
                )
                rendered = json.dumps(config)
                for value in self.results[environment]["inputs"][
                    "broker_route_login"
                ].values():
                    self.assertNotIn(value, rendered)

    def test_service_environment_is_read(self):
        """Every key a first-party service receives is read by code it runs."""
        backend = ROOT.parent / "backend"
        sources = {
            "api": [backend / "services/api/gateway/src"],
            "tactic": [backend / "services/middleware/tactic/src"],
            "db-sync": [backend / "services/db/sync/src"],
            # The deploy readiness probe runs inside the proxy container.
            "mqtt-proxy": [
                backend / "services/mqtt/proxy/src",
                ROOT / "scripts/check_application.py",
            ],
        }
        shared = [backend / "libs/core/src"]

        def text(paths):
            files = (
                [path] if path.is_file() else sorted(path.rglob("*")) for path in paths
            )
            return "\n".join(
                file.read_text()
                for group in files
                for file in group
                if file.suffix in {".py", ".yaml", ".yml"}
            )

        services = self.results["prod"]["config"]["services"]
        for service, paths in sources.items():
            code = text(paths + shared)
            for key in services[service]["environment"]:
                with self.subTest(service=service, key=key):
                    self.assertRegex(code, rf"\b{re.escape(key)}\b")

    def test_traefik_reaches_production_and_the_demo_by_stack_qualified_names(self):
        result = self.results["prod"]
        urls = {
            name: service["loadBalancer"]["servers"][0]["url"]
            for name, service in result["routes"]["services"].items()
        }
        self.assertEqual(urls["demo-frontend"], "http://off-key-demo_frontend:5173")
        self.assertEqual(urls["demo-api"], "http://off-key-demo_api:8000")
        for name, url in urls.items():
            if not name.startswith("demo-"):
                self.assertTrue(url.startswith("http://off-key_"), url)
        routers = result["routes"]["routers"]
        self.assertEqual(
            routers["demo-frontend"]["rule"], "Host(`demo.aberration.app`)"
        )
        self.assertEqual(routers["demo-api"]["middlewares"], ["api-strip"])
        swarm = result["swarm_config"]
        self.assertEqual(swarm["networks"]["demo-network"]["name"], "aberration-demo")
        # Only Traefik of production joins the network the demo shares.
        joined = [
            name
            for name, service in swarm["services"].items()
            if "demo-network" in service.get("networks", {})
        ]
        self.assertEqual(joined, ["traefik"])
        configs = [config["name"] for config in swarm["configs"].values()]
        self.assertTrue(any(name.startswith("emqx_security_cfg_") for name in configs))

    def test_production_has_no_public_demo_settings(self):
        services = self.results["prod"]["swarm_config"]["services"]
        for service in ("api", "tactic"):
            demo = [key for key in services[service]["environment"] if "DEMO" in key]
            self.assertEqual(demo, [], service)

    def test_explicitly_disabled_collection_is_preserved(self):
        config = self.results["prod-collection-disabled"]["config"]
        self.assertEqual(
            config["services"]["mqtt-proxy"]["environment"]["MQTT_TELEMETRY_ENABLED"],
            "false",
        )

    def test_readiness_receives_the_same_collection_switch_as_the_controller(self):
        for name in ("prod", "prod-ingress-disabled"):
            services = self.results[name]["swarm_config"]["services"]
            expected = "false" if name == "prod-ingress-disabled" else "true"
            for service in ("tactic", "mqtt-proxy"):
                self.assertEqual(
                    services[service]["environment"]["SYSTEM_COLLECTION_ENABLED"],
                    expected,
                )

    def test_invalid_nfs_addresses_fail_before_rendering(self):
        for addresses in ([], ["100.100.10.999"], ["100.100.10.2\n100.100.10.3"]):
            with (
                self.subTest(addresses=addresses),
                tempfile.TemporaryDirectory() as directory,
            ):
                result, _ = render(
                    Path(directory),
                    "prod",
                    broker_route_nfs_backend_ips=discovery(addresses),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    (Path(directory) / "stack/broker-route.exports").exists()
                )
                self.assertIn("NFS", result.stdout)
