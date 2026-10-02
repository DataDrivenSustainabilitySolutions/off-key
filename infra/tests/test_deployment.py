"""Integration checks for actual Ansible rendering and Docker config parsing."""

import importlib.util
import ipaddress
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

import yaml
from support import ROOT, ansible, run

spec = importlib.util.spec_from_file_location(
    "compile_stack", ROOT / "scripts/compile_stack.py"
)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)

CLIENTS = ("100.100.10.2", "100.100.10.3")
TOKEN = "eyJ" + "validation-only-not-a-real-token-" * 3
MOUNTS = {
    "persist_postgres": ("postgres", "/var/lib/postgresql/data"),
    "persist_emqx_data": ("emqx-main", "/opt/emqx/data"),
    "persist_emqx_log": ("emqx-main", "/opt/emqx/log"),
}


def discovery(addresses):
    return {
        "results": [
            {
                "item": f"backend-{i}",
                "stdout": address,
                "stdout_lines": address.splitlines(),
            }
            for i, address in enumerate(addresses)
        ]
    }


def render(directory, environment, **overrides):
    variables = {
        "validation_environment": environment,
        "internal_api_secret": "validation-internal-service-secret-123456789",
        "stack_dir": str(directory / "stack"),
        "stack_file_owner": str(os.getuid()),
        "stack_file_group": str(os.getgid()),
        "ansible_python_interpreter": sys.executable,
        "ambibox_nfs_addr": "100.100.10.1",
        "ambibox_nfs_backend_ips": discovery(CLIENTS),
        "cloudflare_tunnel_token": TOKEN,
        "ambibox_access": {
            "mqtt_username": "fixture-vendor",
            "mqtt_password": "fixture-vendor-password",
            "api_key": "fixture-controller",
            "api_secret": "a" * 64,
            "gost_password": "g" * 64,
        },
    } | overrides
    if environment == "prod":
        variables = {
            "emqx_ca_cert": (
                "-----BEGIN CERTIFICATE-----\n"
                + "A" * 120
                + "\n-----END CERTIFICATE-----\n"
            ),
            "emqx_server_cert": (
                "-----BEGIN CERTIFICATE-----\n"
                + "B" * 120
                + "\n-----END CERTIFICATE-----\n"
            ),
            "emqx_server_key": (
                "-----BEGIN "
                + "PRIVATE KEY-----\n"
                + "C" * 120
                + "\n-----END PRIVATE KEY-----\n"
            ),
            "mqtt_proxy_password": "proxy-" + "p" * 32,
            "mqtt_radar_password": "radar-" + "r" * 32,
            "radar_checkpoint_secret": "checkpoint-" + "c" * 32,
            "email_password": "re_validation_only_not_a_real_key",
        } | variables
    inputs = directory / "inputs.json"
    inputs.write_text(json.dumps(variables))
    result = ansible(
        "playbook",
        "-i",
        "localhost,",
        str(ROOT / "tests/render-deployment.yml"),
        "--extra-vars",
        f"@{inputs}",
        check=False,
    )
    return result, variables


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
        "ambibox_api_bootstrap": manifest["ambibox_api_bootstrap"],
        "routes": yaml.safe_load((stack / "traefik-dynamic.yml").read_text())["http"],
        "landing_html": (stack / "landing.html").read_text()
        if (stack / "landing.html").exists()
        else None,
        "export": (stack / "ambibox.exports").read_text().strip(),
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
                "literal-credentials",
                "prod",
                {
                    "postgres_password": "literal-$OFFKEY_REVIEW_SENTINEL-${OFFKEY_REVIEW_SENTINEL}-'\"\\#=\n-trailing\\",
                    "jwt_secret": "synthetic-jwt-$OFFKEY_REVIEW_SENTINEL-'\"\\#=\n-tail",
                    "oauth2_client_secret": "literal-${OFFKEY_REVIEW_SENTINEL}-'\"\\#=\n-tail",
                    "tailscale_ambibox_authkey": "tskey-${OFFKEY_REVIEW_SENTINEL}-'\"\\#=\n-tail",
                },
            ),
            ("prod-moved", "prod", {"ambibox_nfs_addr": "100.100.10.99"}),
            ("prod-rotated", "prod", {"cloudflare_tunnel_token": TOKEN + "rotated"}),
            ("prod-ephemeral", "prod", all_off | {"persist_mailpit": True}),
            ("prod-mixed", "prod", all_off | {"persist_emqx_log": True}),
            ("prod-collection-disabled", "prod", {"mqtt_telemetry_enabled": "false"}),
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
        for service in ("postgres", "tactic", "db-sync", "mqtt-proxy", "mqtt-radar"):
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
        self.assertNotIn("TS_AUTHKEY", services["tailscale-ambibox"]["environment"])

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
            "POSTGRES_PASSWORD": {
                "postgres",
                "tactic",
                "db-sync",
                "mqtt-proxy",
                "mqtt-radar",
            },
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
            self.assertTrue(
                all(
                    key.startswith(("VITE_", "__VITE_"))
                    for key in services["frontend"]["environment"]
                )
            )

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

    def test_deployment_retires_only_production_mailpit_and_can_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            services = root / "services.json"
            original = [
                "off-key_api",
                "off-key_mailpit",
                "off-key_mailpit-other",
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
                "    assert args == ['service', 'rm', 'off-key_mailpit'], args\n"
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
            for environment in ("prod", "prod"):
                with self.subTest(environment=environment):
                    ansible(
                        "playbook",
                        "-i",
                        "localhost,",
                        str(playbook),
                        "-e",
                        f"offkey_env={environment}",
                    )
                    expected = [name for name in original if name != "off-key_mailpit"]
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
            with self.subTest(case=name):
                volume = result["config"]["volumes"]["tailscale-ambibox-state"]
                path, *entries = result["export"].split()
                self.assertEqual(volume["driver_opts"]["device"], f":{path}")
                self.assertIn(
                    f"addr={result['inputs']['ambibox_nfs_addr']},",
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
            return self.results[case]["config"]["volumes"]["tailscale-ambibox-state"]

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
                if result["inputs"]["validation_environment"] != "prod":
                    self.assertNotIn("cloudflared", config["services"])
                    continue
                tunnel = config["services"]["cloudflared"]
                secret = tunnel["secrets"][0]
                target = PurePosixPath("/run/secrets") / secret["target"]
                self.assertEqual(str(target), "/run/secrets/cloudflared_tunnel_token")
                token_argument = tunnel["command"].index("--token-file") + 1
                self.assertEqual(tunnel["command"][token_argument], str(target))
                self.assertTrue(config["secrets"][secret["source"]]["external"])
                self.assertNotIn(
                    result["inputs"]["cloudflare_tunnel_token"], json.dumps(config)
                )
        original = self.results["prod"]["config"]["secrets"]
        rotated = self.results["prod-rotated"]["config"]["secrets"]
        self.assertNotEqual(original, rotated)

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

        landing = config["services"]["landing"]
        self.assertEqual(set(landing["networks"]), {"public-network"})
        self.assertFalse(landing.get("environment"))
        self.assertFalse(landing.get("secrets"))
        self.assertEqual(
            landing["configs"][0]["target"], "/usr/share/nginx/html/index.html"
        )
        self.assertRegex(
            config["configs"]["landing_page"]["name"], r"^landing_page_[0-9a-f]{12}$"
        )
        headers = routes["middlewares"]["landing-headers"]["headers"]
        self.assertEqual(
            headers["customRequestHeaders"], {"Cookie": "", "Authorization": ""}
        )
        self.assertIn("default-src 'none'", headers["contentSecurityPolicy"])

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
        self.assertEqual(radar["environment"]["ENVIRONMENT"], "production")
        self.assertEqual(radar["environment"]["RADAR_MQTT_USE_AUTH"], "true")
        self.assertNotIn("RADAR_MQTT_API_KEY", radar["environment"])
        self.assertEqual(
            radar["environment"]["RADAR_MQTT_CA_FILE"], "/run/secrets/EMQX_CA_CERT"
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
                "ambibox_api_bootstrap",
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
        self.assertEqual(controller["environment"]["AMBIBOX_INGRESS_ENABLED"], "true")
        self.assertNotIn("MQTT_SOURCE_TOPICS", proxy["environment"])
        self.assertNotIn("TAILSCALE_AMBIBOX_UPSTREAM_HOST", proxy["environment"])
        self.assertEqual(
            config["services"]["mqtt-tailscale-bridge"]["image"],
            yaml.safe_load(
                (
                    ROOT / "ansible/inventories/prod/group_vars/all/release.yml"
                ).read_text()
            )["release"]["images"]["gost"],
        )
        for value in self.results["prod"]["inputs"]["ambibox_access"].values():
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
                    controller["environment"]["AMBIBOX_INGRESS_ENABLED"], "true"
                )
                self.assertEqual(
                    {secret["target"] for secret in controller["secrets"]},
                    {
                        "AMBIBOX_EMQX_API_KEY",
                        "AMBIBOX_EMQX_API_SECRET",
                        "AMBIBOX_GOST_PASSWORD",
                        "AMBIBOX_MQTT_USERNAME",
                        "AMBIBOX_MQTT_PASSWORD",
                    },
                )
                broker = services["emqx-main"]
                self.assertEqual(
                    broker["environment"]["EMQX_API_KEY__BOOTSTRAP_FILE"],
                    "/run/secrets/ambibox_api_bootstrap",
                )
                self.assertIn(
                    "ambibox_api_bootstrap",
                    {secret["target"] for secret in broker["secrets"]},
                )
                access = self.results[environment]["inputs"]["ambibox_access"]
                self.assertEqual(
                    self.results[environment]["ambibox_api_bootstrap"]
                    .strip()
                    .split(":"),
                    [access["api_key"], access["api_secret"]],
                )
                forwarder = services["mqtt-tailscale-bridge"]
                self.assertEqual(
                    forwarder["command"],
                    ["-C", "/run/secrets/ambibox_gost_config.json"],
                )
                self.assertEqual(
                    forwarder["secrets"][0]["target"], "ambibox_gost_config.json"
                )
                if environment != "prod":
                    self.assertNotIn("emqx_security_cfg", config.get("configs", {}))
                rendered = json.dumps(config)
                for value in self.results[environment]["inputs"][
                    "ambibox_access"
                ].values():
                    self.assertNotIn(value, rendered)

    def test_explicitly_disabled_collection_is_preserved(self):
        config = self.results["prod-collection-disabled"]["config"]
        self.assertEqual(
            config["services"]["mqtt-proxy"]["environment"]["MQTT_TELEMETRY_ENABLED"],
            "false",
        )

    @unittest.skipUnless(
        os.environ.get("OFFKEY_GOST_SMOKE") == "1",
        "Set OFFKEY_GOST_SMOKE=1 for the container check",
    )
    def test_bridge_accepts_the_mounted_config_filename(self):
        forwarder = self.results["prod"]["config"]["services"]["mqtt-tailscale-bridge"]
        target = PurePosixPath("/run/secrets") / forwarder["secrets"][0]["target"]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"api": {"addr": ":18080"}}))
            # GOST chooses its parser from the mounted filename, not the contents.
            result = run(
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--mount",
                f"type=bind,source={config},target={target},readonly",
                forwarder["image"],
                *forwarder["command"],
                "-O",
                "json",
            )
        self.assertEqual(json.loads(result.stdout)["api"]["addr"], ":18080")

    def test_invalid_nfs_addresses_fail_before_rendering(self):
        for addresses in ([], ["100.100.10.999"], ["100.100.10.2\n100.100.10.3"]):
            with (
                self.subTest(addresses=addresses),
                tempfile.TemporaryDirectory() as directory,
            ):
                result, _ = render(
                    Path(directory),
                    "prod",
                    ambibox_nfs_backend_ips=discovery(addresses),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((Path(directory) / "stack/ambibox.exports").exists())
                self.assertIn("NFS", result.stdout)
