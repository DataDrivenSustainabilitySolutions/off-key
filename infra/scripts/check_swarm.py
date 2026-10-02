"""Verify the stack's tasks have converged without accepting an automatic rollback."""

import json
import subprocess
import sys
from pathlib import Path


def check_services(services, expected, replicas):
    actual = {service["Spec"]["Name"]: service for service in services}
    if not expected:
        raise ValueError("The deployment model contains no services")
    missing, unexpected = (
        expected.keys() - actual.keys(),
        actual.keys() - expected.keys(),
    )
    if missing or unexpected:
        raise ValueError(
            f"Stack service set differs: missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    for name, target in expected.items():
        service = actual[name]
        spec = service["Spec"]
        image = spec["TaskTemplate"]["ContainerSpec"]["Image"]
        if image != target["image"]:
            raise ValueError(f"{name}: image differs from its intended release image")
        update = service.get("UpdateStatus", {}).get("State")
        if update not in (None, "completed"):
            raise ValueError(f"{name}: update state {update}")
        running, desired = map(int, replicas[name].split("/"))
        configured = spec["Mode"]["Replicated"]["Replicas"]
        if (
            running != target["replicas"]
            or desired != target["replicas"]
            or configured != target["replicas"]
        ):
            raise ValueError(
                f"{name}: {replicas[name]} tasks running, expected {target['replicas']}"
            )


def main():
    listing = subprocess.check_output(
        [
            "docker",
            "service",
            "ls",
            "--format",
            "{{json .}}",
            "--filter",
            f"label=com.docker.stack.namespace={sys.argv[1]}",
        ],
        text=True,
        timeout=15,
    )
    rows = [json.loads(line) for line in listing.splitlines()]
    if not rows:
        raise ValueError("No stack services exist")
    # Only service state is printed, never environment variables or credentials.
    services = json.loads(
        subprocess.check_output(
            ["docker", "service", "inspect", *[row["ID"] for row in rows]],
            text=True,
            timeout=15,
        )
    )
    model = json.loads(Path(sys.argv[2]).read_text())
    expected = {
        f"{sys.argv[1]}_{name}": {
            "image": service["image"],
            "replicas": service.get("deploy", {}).get("replicas", 1),
        }
        for name, service in model["services"].items()
    }
    # Runtime workers can share the stack namespace, but have a separate lifecycle.
    stack_services = [
        service
        for service in services
        if not (
            service["Spec"].get("Labels", {}).get("managed_by") == "tactic"
            and service["Spec"].get("Labels", {}).get("service_type") == "radar"
        )
    ]
    check_services(
        stack_services, expected, {row["Name"]: row["Replicas"] for row in rows}
    )
    # TACTIC may create a persistent worker during the stack update. Check again
    # after convergence instead of relying only on the pre-deployment guard.
    radar_listing = subprocess.check_output(
        [
            "docker",
            "service",
            "ls",
            "--format",
            "{{json .}}",
            "--filter",
            "label=managed_by=tactic",
            "--filter",
            "label=service_type=radar",
        ],
        text=True,
        timeout=15,
    )
    radar_rows = [json.loads(line) for line in radar_listing.splitlines()]
    if radar_rows:
        radars = json.loads(
            subprocess.check_output(
                ["docker", "service", "inspect", *[row["ID"] for row in radar_rows]],
                text=True,
                timeout=15,
            )
        )
        expected = sys.argv[3].split("@")[-1]
        for radar in radars:
            spec = radar["Spec"]
            if (
                spec["TaskTemplate"]["ContainerSpec"]["Image"].split("@")[-1]
                != expected
            ):
                raise ValueError(
                    f"{spec['Name']}: stop and recreate this RADAR worker with the intended release"
                )
        check_services(
            radars,
            {
                radar["Spec"]["Name"]: {
                    "image": radar["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"],
                    "replicas": 1,
                }
                for radar in radars
            },
            {row["Name"]: row["Replicas"] for row in radar_rows},
        )
    print(f"All {len(stack_services)} stack services have converged")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        sys.exit(str(exc))
