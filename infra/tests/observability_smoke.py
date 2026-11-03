"""Real worker-only logging, failure isolation and restart integration rehearsal."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.parse
import uuid
from pathlib import Path

from observability_lab import Lab, engine_environment, wait
from support import ROOT, render

sys.path.insert(0, str(ROOT / "scripts"))
import observability_runtime as runtime


def local_container(engine, service):
    ids = engine(
        "ps", "-q", "--filter", f"label=com.docker.swarm.service.name={service}"
    ).split()
    if len(ids) != 1:
        raise ValueError("Expected exactly one local task")
    return ids[0]


def query(engine, stack, marker):
    container = local_container(engine, f"{stack}_grafana")
    expression = f'{{stack="{stack}"}} |= "{marker}"'
    url = "http://loki:3100/loki/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": expression, "limit": 100}
    )
    return json.loads(
        engine("exec", container, "wget", "-q", "-T", "5", "-O", "-", url)
    )["data"]["result"]


def current_tasks(manager, name):
    return manager(
        "service", "ps", "-q", "--filter", "desired-state=running", name
    ).split()


def run_rehearsal(evidence_path):
    identity = uuid.uuid4().hex[:10]
    stack = f"offkey-obs-{identity}"
    images = json.loads(
        (ROOT / "ansible/inventories/prod/group_vars/all/release.yml").read_text()
    )["release"]["images"]
    lab = Lab(identity)
    report = {}
    try:
        lab.start()
        manager, data, worker = (lab.engines[k] for k in ("manager", "data", "worker"))
        lab.load_images(
            [images[k] for k in ("loki", "grafana", "alloy", "socket_proxy")], "data"
        )
        lab.load_images([images[k] for k in ("alloy", "socket_proxy")], "worker")
        fixture_image = lab.content_ids[images["socket_proxy"]]
        node_names = [f"{lab.network}-{suffix}" for suffix in ("data", "worker")]
        lab.outer(
            "exec",
            node_names[0],
            "mkdir",
            "-p",
            "/srv/offkey-observability/loki",
            "/srv/offkey-observability/grafana",
        )
        for directory, owner in (("loki", "10001:10001"), ("grafana", "472:0")):
            lab.outer(
                "exec",
                node_names[0],
                "chown",
                owner,
                f"/srv/offkey-observability/{directory}",
            )
        manager(
            "network",
            "create",
            "--driver",
            "overlay",
            "--internal",
            f"{stack}_emqx-network",
        )
        manager(
            "network",
            "create",
            "--driver",
            "overlay",
            "--internal",
            f"unrelated-{identity}",
        )
        markers = {
            kind: f"{kind}-{identity}" for kind in ("owned", "unrelated", "legacy")
        }
        for name, kind, labels, network in (
            (
                f"{stack}_api",
                "owned",
                ["com.docker.stack.namespace=" + stack],
                f"{stack}_emqx-network",
            ),
            (
                f"{stack}_frontend",
                "owned",
                ["com.docker.stack.namespace=" + stack],
                f"{stack}_emqx-network",
            ),
            (f"unrelated-{identity}", "unrelated", [], f"unrelated-{identity}"),
            ("radar-" + str(uuid.uuid4()), "legacy", [], f"{stack}_emqx-network"),
        ):
            args = [
                "service",
                "create",
                "--detach=true",
                "--name",
                name,
                "--constraint",
                f"node.hostname=={node_names[1]}",
                "--limit-memory",
                "16m",
                "--limit-cpu",
                "0.05",
            ]
            for label in labels:
                args += ["--label", label, "--container-label", label]
            if network:
                args += ["--network", network]
            manager(
                *args,
                "--entrypoint",
                "/bin/sh",
                fixture_image,
                "-ec",
                f"while :; do echo '{markers[kind]}'; sleep 2; done",
            )
        protected = wait(
            lambda: local_container(worker, f"unrelated-{identity}"),
            "unrelated fixture",
        )
        with tempfile.TemporaryDirectory(prefix="offkey-obs-render-") as temporary:
            directory = Path(temporary)
            with engine_environment(manager):
                result, _ = render(
                    directory,
                    "prod",
                    stack_name=stack,
                    observability_data_node=node_names[0],
                    observability_runtime_image=fixture_image,
                )
            if result.returncode:
                raise RuntimeError("Real Ansible observability rendering failed")
            model_path = directory / "stack/observability-model.json"
            model = json.loads(model_path.read_text())
            for service in model["services"].values():
                service["image"] = lab.content_ids[service["image"]]
            model_path.write_text(json.dumps(model))
            manager(
                "stack", "deploy", "--resolve-image", "never", "-c", model_path, stack
            )

            def verify():
                with engine_environment(manager):
                    topology = runtime.topology(stack, model)
                with engine_environment(data):
                    health = runtime.health(stack, node_names)
                return topology | health

            report.update(
                wait(verify, "worker topology and canary round trip", seconds=300)
            )
            for kind in ("owned", "legacy"):

                def present(kind=kind):
                    assert query(data, stack, markers[kind])

                wait(present, kind + " log delivery")
            assert not query(data, stack, markers["unrelated"])
            report.update(
                owned_logs=True, legacy_radar_logs=True, unrelated_logs_excluded=True
            )

            for engine in (data, worker):
                proxy = local_container(engine, f"{stack}_alloy-docker")
                for method, path in (
                    ("POST", "/containers/create"),
                    ("GET", "/containers/" + "a" * 64 + "/archive"),
                    ("GET", "/secrets"),
                ):
                    request = f"{method} {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                    response = engine(
                        "exec",
                        "-i",
                        proxy,
                        "socat",
                        "-",
                        "UNIX-CONNECT:/run/offkey-docker/docker.sock",
                        input=request,
                    )
                    assert response.startswith("HTTP/1.1 403"), (
                        "Restricted Docker API request was not denied"
                    )
            report["docker_control_and_file_apis_denied"] = True

            manager("service", "scale", "--detach=true", f"{stack}_loki=0")
            app_model = {
                "services": {
                    name: {"image": fixture_image, "deploy": {"replicas": 1}}
                    for name in ("api", "frontend")
                }
            }
            app_path = directory / "application.json"
            app_path.write_text(json.dumps(app_model))
            manager(
                "service",
                "update",
                "--detach=true",
                "--env-add",
                "OBSERVABILITY_TEST_REDEPLOY=1",
                f"{stack}_api",
            )

            def application_ready():
                process = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/check_swarm.py"),
                        stack,
                        str(app_path),
                        fixture_image,
                        "--backend-first",
                    ],
                    capture_output=True,
                    text=True,
                    env=manager.environment,
                    timeout=40,
                    check=False,
                )
                assert process.returncode == 0

            wait(application_ready, "application convergence while Loki is stopped")
            report["application_deploy_independent_of_loki"] = True
            manager("service", "scale", "--detach=true", f"{stack}_loki=1")
            wait(verify, "Loki restart and fresh delivery")
            assert query(data, stack, markers["owned"])
            report["logs_survive_loki_restart"] = True

            stable = {
                name: current_tasks(manager, f"{stack}_{name}")
                for name in ("loki", "alloy", "alloy-docker")
            }
            dashboard = directory / "stack/grafana-dashboard-logs.json"
            document = json.loads(dashboard.read_text())
            document["title"] += " integration refresh"
            dashboard.write_text(json.dumps(document))
            model["configs"]["grafana_dashboard_logs"]["name"] = (
                "grafana_dashboard_logs_"
                + hashlib.sha1(dashboard.read_bytes()).hexdigest()[:12]
            )
            model_path.write_text(json.dumps(model))
            manager(
                "stack", "deploy", "--resolve-image", "never", "-c", model_path, stack
            )
            wait(verify, "dashboard-only update")
            assert stable == {
                name: current_tasks(manager, f"{stack}_{name}") for name in stable
            }
            report["dashboard_edit_does_not_restart_collectors_or_loki"] = True
            assert local_container(worker, f"unrelated-{identity}") == protected
            with engine_environment(manager):
                runtime.pause(stack)
            wait(application_ready, "application convergence after monitoring pause")
            assert local_container(worker, f"unrelated-{identity}") == protected
            report["unrelated_application_unchanged"] = True
            report["pause_preserves_application"] = True
        report.update(lab_nodes=3, manager_cpu_limit=1, manager_memory_limit_mib=1024)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))
    finally:
        lab.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    run_rehearsal(parser.parse_args().evidence)
