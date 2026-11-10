"""Independent, non-secret checks and narrowly scoped pause for observability."""

import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

COMPONENT = "off-key.component=observability"


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=15)


def owned_services(stack):
    ids = docker(
        "service",
        "ls",
        "-q",
        "--filter",
        f"label=com.docker.stack.namespace={stack}",
        "--filter",
        f"label={COMPONENT}",
    ).split()
    services = json.loads(docker("service", "inspect", *ids)) if ids else []
    for service in services:
        spec = service["Spec"]
        labels = spec.get("Labels", {})
        if (
            not spec["Name"].startswith(stack + "_")
            or labels.get("com.docker.stack.namespace") != stack
            or labels.get("off-key.component") != "observability"
        ):
            raise ValueError("Refusing a service outside this observability component")
    return services


def nodes():
    return json.loads(docker("node", "inspect", *docker("node", "ls", "-q").split()))


def preflight(model):
    constraints = model["services"]["loki"]["deploy"]["placement"]["constraints"]
    target = next(
        c.split("==", 1)[1].strip()
        for c in constraints
        if c.startswith("node.hostname")
    )
    selected = [n for n in nodes() if n["Description"]["Hostname"] == target]
    if len(selected) != 1:
        raise ValueError("The data-node hostname must identify exactly one Swarm node")
    node = selected[0]
    if (
        node["Spec"]["Role"] != "worker"
        or node["Spec"]["Availability"] != "active"
        or node["Status"]["State"] != "ready"
    ):
        raise ValueError("The data node must be an active, ready worker")
    if node["Description"]["Resources"]["MemoryBytes"] < 3 * 1024**3:
        raise ValueError(
            "The data worker needs at least 3 GiB RAM, including host headroom"
        )
    return {"data_node": target, "worker_only": True}


def verify_config_mounts(task, wanted, model):
    """A running container is insufficient when its dashboard configs are stale."""
    actual = {
        (item["ConfigName"], item.get("File", {}).get("Name"))
        for item in task["ContainerSpec"].get("Configs", [])
    }
    expected = {
        (model["configs"][item["source"]]["name"], item["target"])
        for item in wanted.get("configs", [])
    }
    if actual != expected:
        raise ValueError("Mounted configuration differs from the independent model")


def topology(stack, model):
    actual = {s["Spec"]["Name"]: s for s in owned_services(stack)}
    expected = {
        f"{stack}_{name}": service for name, service in model["services"].items()
    }
    if actual.keys() != expected.keys():
        raise ValueError("Observability service set differs from its independent model")
    by_id = {n["ID"]: n for n in nodes()}
    eligible = {
        n["ID"]
        for n in by_id.values()
        if n["Spec"]["Role"] == "worker"
        and n["Spec"]["Availability"] == "active"
        and n["Status"]["State"] == "ready"
    }
    if not eligible:
        raise ValueError("No ready workers")
    result = {}
    for name, wanted in expected.items():
        service = actual[name]
        spec = service["Spec"]
        task = spec["TaskTemplate"]
        verify_config_mounts(task, wanted, model)
        if task["ContainerSpec"]["Image"] != wanted["image"]:
            raise ValueError(f"{name}: image differs from the pinned model")
        if service.get("UpdateStatus", {}).get("State") not in (None, "completed"):
            raise ValueError(f"{name}: update is not complete")
        if "node.role == worker" not in task.get("Placement", {}).get(
            "Constraints", []
        ):
            raise ValueError(f"{name}: missing worker-only placement")
        if not all(
            task.get("Resources", {}).get(kind, {}).get(key, 0) > 0
            for kind in ("Limits", "Reservations")
            for key in ("MemoryBytes", "NanoCPUs")
        ):
            raise ValueError(f"{name}: missing CPU or memory bounds/reservations")
        for kind, model_kind in (
            ("Limits", "limits"),
            ("Reservations", "reservations"),
        ):
            wanted_budget = wanted["deploy"]["resources"][model_kind]
            actual_budget = task["Resources"][kind]
            if actual_budget["MemoryBytes"] != int(
                wanted_budget["memory"]
            ) or actual_budget["NanoCPUs"] != round(
                float(wanted_budget["cpus"]) * 10**9
            ):
                raise ValueError(
                    f"{name}: resource policy differs from the independent model"
                )
        ids = docker("service", "ps", "-q", "--no-trunc", name).split()
        tasks = json.loads(docker("inspect", *ids)) if ids else []
        running = [t for t in tasks if t["Status"]["State"] == "running"]
        if any(by_id[t["NodeID"]]["Spec"]["Role"] != "worker" for t in running):
            raise ValueError(f"{name}: a live monitoring task is on a manager")
        global_mode = wanted.get("deploy", {}).get("mode") == "global"
        if global_mode:
            if (
                "Global" not in spec["Mode"]
                or len(running) != len(eligible)
                or {t["NodeID"] for t in running} != eligible
            ):
                raise ValueError(f"{name}: expected one live task per eligible worker")
        else:
            configured = spec["Mode"].get("Replicated", {}).get("Replicas")
            target = wanted["deploy"]["replicas"]
            if configured != target or len(running) != target:
                raise ValueError(f"{name}: expected {target} live tasks")
            required = next(
                c.split("==", 1)[1].strip()
                for c in wanted["deploy"]["placement"]["constraints"]
                if c.startswith("node.hostname")
            )
            if any(
                by_id[t["NodeID"]]["Description"]["Hostname"] != required
                for t in running
            ):
                raise ValueError(f"{name}: data is not on its explicit worker")
        result[name] = len(running)
    return {
        "worker_only": True,
        "running": result,
        "eligible_workers": len(eligible),
        "eligible_worker_names": sorted(
            by_id[node]["Description"]["Hostname"] for node in eligible
        ),
    }


def health(stack, expected_nodes):
    ids = docker(
        "ps", "-q", "--filter", f"label=com.docker.swarm.service.name={stack}_grafana"
    ).split()
    if len(ids) != 1:
        raise ValueError("Expected exactly one local Grafana task on the data worker")

    def get(url):
        return docker("exec", ids[0], "wget", "-q", "-T", "5", "-O", "-", url)

    if get("http://loki:3100/ready").strip() != "ready":
        raise ValueError("Loki is not ready")
    if json.loads(get("http://127.0.0.1:3000/api/health")).get("database") != "ok":
        raise ValueError("Grafana database health failed")
    query = (
        f'count_over_time({{stack="{stack}",service="{stack}_log-canary"}} '
        '| json event="event" | event="observability_canary" | __error__="" [2m])'
    )
    response = json.loads(
        get(
            "http://loki:3100/loki/api/v1/query?"
            + urllib.parse.urlencode({"query": query})
        )
    )
    rows = response.get("data", {}).get("result", [])
    observed = {row["metric"].get("node") for row in rows if float(row["value"][1]) > 0}
    if observed != set(expected_nodes):
        raise ValueError("Fresh log delivery is missing for one or more workers")
    return {
        "loki_ready": True,
        "grafana_database": "ok",
        "fresh_log_delivery_nodes": sorted(observed),
    }


def pause(stack):
    services = owned_services(stack)
    for service in services:
        service_id = service["ID"]
        if "Global" in service["Spec"]["Mode"]:
            docker("service", "rm", service_id)
        else:
            docker("service", "scale", "--detach=true", f"{service_id}=0")
    return {"paused_services": len(services), "data_preserved": True}


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "health":
        answer = health(sys.argv[2], json.loads(sys.argv[3]))
    elif action == "pause":
        answer = pause(sys.argv[2])
    elif action in ("preflight", "topology"):
        model = json.loads(Path(sys.argv[3]).read_text())
        answer = (
            preflight(model) if action == "preflight" else topology(sys.argv[2], model)
        )
    else:
        raise SystemExit("Expected preflight, topology, health or pause")
    print(json.dumps(answer))
