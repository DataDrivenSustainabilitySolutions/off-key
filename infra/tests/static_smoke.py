"""Rehearse the static cutover over a running production Swarm and active worker.

A disposable LABEL creates distinct variants of the exact tested frontend and
documentation images. These are never published or included in production-release.json.
Update to them and back through the production tasks, proving backend tasks stay put.
"""

import argparse
import json
from copy import deepcopy
from pathlib import Path

from rehearsal_releases import push_local, start_registry
from support import load_script, run
from swarm_smoke import STACK, deploy, ready

static = load_script("static_release")


def running_backends():
    names = run("docker", "service", "ls", "--format", "{{.Name}}").stdout.splitlines()
    return {
        name: {
            "spec": json.loads(run("docker", "service", "inspect", name).stdout)[0][
                "Spec"
            ],
            "tasks": run(
                "docker",
                "service",
                "ps",
                "--quiet",
                "--no-trunc",
                "--filter",
                "desired-state=running",
                name,
            ).stdout.splitlines(),
        }
        for name in names
        if name not in {f"{STACK}_frontend", f"{STACK}_docs"}
    }


def rehearse(directory):
    model_file = directory / "stack/deployment-model.json"
    original_model = json.loads(model_file.read_text())
    inputs_file = directory / "inputs.json"
    inputs = json.loads(inputs_file.read_text())
    original_release = inputs["release"]
    before = running_backends()
    start_registry()
    originals = {
        name: original_release["images"][name] for name in ("frontend", "docs")
    }
    variants = {}
    for name, original in originals.items():
        tag = f"localhost:5010/off-key-{name}:static-rehearsal"
        run(
            "docker",
            "build",
            "--tag",
            tag,
            "-",
            input=f"FROM {original}\nLABEL off-key.ci.static-rehearsal=true\n",
            timeout=300,
        )
        variants[name] = push_local(tag)
    paths = ["frontend/src/static-rehearsal.tsx", "docs/static-rehearsal.md"]
    for images in (variants, originals):
        model = deepcopy(original_model)
        for name, image in images.items():
            model["services"][name]["image"] = image
        model_file.write_text(json.dumps(model))
        selected = static.decision(directory / "stack", STACK, paths)
        if selected != images:
            raise AssertionError(
                "The static cutover did not select only the changed static images"
            )
        release = deepcopy(original_release)
        release["images"].update(images)
        inputs_file.write_text(json.dumps(inputs | {"release": release}))
        deploy(
            directory,
            "static",
            release_static_only=True,
            static_source_diff={"stdout_lines": paths},
            static_previous={
                "stdout": json.loads((directory / "stack" / static.STATE).read_text())[
                    "revision"
                ]
            },
        )
        ready(directory)
        if running_backends() != before:
            raise AssertionError(
                "A static update changed a backend spec or replaced a running task"
            )
    inputs_file.write_text(json.dumps(inputs))
    (directory / "static-release-evidence.json").write_text(
        json.dumps(
            {
                "backend_specs_and_tasks_preserved": True,
                "services": sorted(before),
                "static_images_restored": originals,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    rehearse(parser.parse_args().directory)
