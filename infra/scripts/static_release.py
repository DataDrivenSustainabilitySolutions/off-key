"""Update static images only when the verified runtime is otherwise identical.

The verified model also covers configuration, secrets, mounts and platform
images; the recorded Docker specs fence live drift. Any uncertainty selects a
full cutover. This program never clears recovery or records release success.
"""

import argparse
import json
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

STATIC = {"frontend", "docs"}
STATE = "verified-deployment.json"


def docker(*args):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=300
    ).stdout


def specs(stack):
    services = docker(
        "service",
        "ls",
        "--quiet",
        "--filter",
        f"label=com.docker.stack.namespace={stack}",
    ).split()
    if not services:
        raise ValueError("No deployed services")
    return {
        item["Spec"]["Name"]: item["Spec"]
        for item in json.loads(docker("service", "inspect", *services))
    }


def static_paths(paths):
    return bool(paths) and all(
        path
        and ".." not in Path(path).parts
        and (
            path.startswith(("frontend/", "docs/", "dev/docs/"))
            or path in {"requirements-docs.txt", "zensical.toml"}
            or ("/" not in path and path.endswith(".md"))
        )
        for path in paths
    )


def changed_images(previous, desired):
    """Return static image changes only if every other model field is equal."""
    old, new = deepcopy(previous), deepcopy(desired)
    changed = {}
    for name in STATIC:
        before = old.get("services", {}).get(name)
        after = new.get("services", {}).get(name)
        if before is None or after is None:
            continue
        if before.get("image") != after.get("image"):
            changed[name] = after["image"]
        before.pop("image", None)
        after.pop("image", None)
    return changed if old == new else {}


def decision(
    directory,
    stack,
    paths,
    current_specs=None,
    maintenance_revision=None,
    baseline_revision=None,
):
    try:
        directory = Path(directory)
        if not static_paths(paths) or (directory / "recovery-pending.json").exists():
            return {}
        maintenance = directory / "release-maintenance.json"
        if maintenance_revision is not None and not maintenance.exists():
            return {}
        if maintenance.exists() and (
            maintenance_revision is None
            or json.loads(maintenance.read_text())["revision"] != maintenance_revision
        ):
            return {}
        saved = json.loads((directory / STATE).read_text())
        if baseline_revision is not None and saved["revision"] != baseline_revision:
            return {}
        verified = json.loads((directory / "release.json").read_text())
        desired = json.loads((directory / "deployment-model.json").read_text())
        if (
            saved["version"] != 1
            or saved["revision"] != verified["application_revision"]
        ):
            return {}
        changed = changed_images(saved["model"], desired)
        if not changed or saved["specs"] != (
            specs(stack) if current_specs is None else current_specs
        ):
            return {}
        return changed
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {}


def write_private(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        json.dump(value, output, sort_keys=True)
    Path(output.name).replace(path)


def record_browser_fence(directory):
    """Retain the readiness fence established before this static image update."""
    saved = json.loads((directory / STATE).read_text())
    desired = json.loads((directory / "deployment-model.json").read_text())
    if "frontend" not in desired["services"]:
        return
    previous = saved["model"]["services"]["frontend"]
    write_private(
        directory / "browser-cutover.json",
        {
            "backend_ready": True,
            # This script also runs under the remote host's system Python.
            "backend_ready_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            "previous_frontend_image": previous["image"],
            "previous_frontend_replicas": previous.get("deploy", {}).get("replicas", 1),
            "target_frontend_image": desired["services"]["frontend"]["image"],
        },
    )


def record(directory, stack):
    directory = Path(directory)
    verified = json.loads((directory / "release.json").read_text())
    state = {
        "version": 1,
        "revision": verified["application_revision"],
        "model": json.loads((directory / "deployment-model.json").read_text()),
        "specs": specs(stack),
    }
    write_private(directory / STATE, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("previous", "select", "apply", "record"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("stack")
    parser.add_argument("paths", nargs="?", default="[]")
    parser.add_argument("--revision")
    parser.add_argument("--baseline-revision")
    args = parser.parse_args()
    if args.action == "previous":
        try:
            print(json.loads((args.directory / STATE).read_text())["revision"])
        except (OSError, ValueError, KeyError, TypeError):
            print()
    elif args.action == "record":
        record(args.directory, args.stack)
    else:
        if args.action == "apply" and (not args.revision or not args.baseline_revision):
            parser.error(
                "static application requires its reservation and verified baseline revisions"
            )
        changed = decision(
            args.directory,
            args.stack,
            json.loads(args.paths),
            maintenance_revision=args.revision if args.action == "apply" else None,
            baseline_revision=args.baseline_revision
            if args.action == "apply"
            else None,
        )
        if args.action == "apply":
            if not changed:
                raise SystemExit(
                    "Static release no longer matches the verified runtime"
                )
            # The production caller has verified API/catalogue readiness and the
            # migration ledger. The exact live specs were rechecked above; keep
            # a new fence before either static service can start its new image.
            record_browser_fence(args.directory)
            for name, image in sorted(changed.items()):
                docker(
                    "service",
                    "update",
                    "--detach=false",
                    "--with-registry-auth",
                    "--image",
                    image,
                    f"{args.stack}_{name}",
                )
        print(json.dumps(changed, sort_keys=True))


if __name__ == "__main__":
    main()
