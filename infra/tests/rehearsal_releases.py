"""Build and select two real, schema-compatible rehearsal releases.

The reference is the previous platform code with reviewed Aberrant 1.4.0 numerics.
It is not an eligible production release and proves no pre-feature compatibility.
"""

import json
import tarfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from support import run

COMPATIBLE_REVISION = "9c010bda9831648f1db8c395dc0633f1302df757"
REGISTRY = "offkey-smoke-registry"
# Detector numerics; other locked packages may differ as in a real rollback.
NUMERICAL_LIBRARIES = ("aberrant",)
BUILDS = {
    "api": ("off-key-api-gateway", "services/api/gateway"),
    "tactic": ("off-key-tactic-middleware", "services/middleware/tactic"),
    "mqtt_proxy": ("off-key-mqtt-proxy", "services/mqtt/proxy"),
    "mqtt_radar": ("off-key-mqtt-radar", "services/mqtt/radar"),
    "db_sync": ("off-key-db-sync", "services/db/sync"),
    "frontend": ("off-key-frontend", None),
}
MODEL_SERVICES = {
    "api": "api",
    "tactic": "tactic",
    "mqtt_proxy": "mqtt-proxy",
    "mqtt_radar": "mqtt-radar",
    "db_sync": "db-sync",
    "frontend": "frontend",
}


def start_registry():
    existing = run("docker", "inspect", REGISTRY, check=False)
    if existing.returncode == 0:
        data = json.loads(existing.stdout)[0]
        labels = data["Config"].get("Labels") or {}
        if labels.get("off-key.ci") != "deployment-smoke":
            raise ValueError("The rehearsal registry name belongs to another workload")
        if not data["State"]["Running"]:
            run("docker", "start", REGISTRY)
        return
    run(
        "docker",
        "run",
        "-d",
        "--name",
        REGISTRY,
        "--label",
        "off-key.ci=deployment-smoke",
        "-p",
        "127.0.0.1:5010:5000",
        "registry:3",
    )


def stop_registry():
    existing = run("docker", "inspect", REGISTRY, check=False)
    if existing.returncode == 0:
        labels = json.loads(existing.stdout)[0]["Config"].get("Labels") or {}
        if labels.get("off-key.ci") == "deployment-smoke":
            run("docker", "rm", "-f", REGISTRY)


def build_local_images(release, revision, project):
    start_registry()

    def build(item):
        name, (service, source) = item
        reference = f"localhost:5010/{service}:sha-{revision[:12]}"
        args = [
            "docker",
            "build",
            "--label",
            f"org.opencontainers.image.revision={revision}",
            "-t",
            reference,
        ]
        if source is None:
            args += ["--target", "production", str(project / "frontend")]
        else:
            args += [
                "--build-arg",
                f"SERVICE_NAME={service}",
                "--build-arg",
                f"SERVICE_ROOT={source}",
                "--build-arg",
                f"GIT_COMMIT={revision}",
                str(project / "backend"),
            ]
        print(f"Building production {name} at {revision}", flush=True)
        run(*args, timeout=900)
        run("docker", "push", reference, timeout=300)
        references = json.loads(
            run(
                "docker",
                "image",
                "inspect",
                reference,
                "--format",
                "{{json .RepoDigests}}",
            ).stdout
        )
        return name, next(
            value
            for value in references
            if value.startswith(reference.rsplit(":", 1)[0] + "@")
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        release["images"].update(pool.map(build, BUILDS.items()))


def compatible_release(directory, project, reference_repository=None):
    """Build actual older source; refuse unnoticed schema/numerical changes."""
    current = json.loads((directory / "production-release.json").read_text())["release"]
    if current["application_revision"] == COMPATIBLE_REVISION:
        raise ValueError("Binary rollback requires two different source revisions")
    source = archive_compatible_source(directory, reference_repository or project)
    validate_compatible_source(source, project)
    release = deepcopy(current)
    build_local_images(release, COMPATIBLE_REVISION, source)
    release["application_revision"] = COMPATIBLE_REVISION
    (directory / "compatible-release.json").write_text(
        json.dumps({"release": release}, indent=2)
    )
    image_identities(release)
    print(f"Prepared test-only compatible release {COMPATIBLE_REVISION}", flush=True)


def archive_compatible_source(directory, reference_repository):
    """Use the exact authenticated fixture checkout, even after a squash merge."""
    repository = Path(reference_repository).resolve()
    if not repository.is_dir():
        raise ValueError("Compatible reference repository does not exist")
    result = run(
        "git",
        "rev-parse",
        "--verify",
        f"{COMPATIBLE_REVISION}^{{commit}}",
        cwd=repository,
        check=False,
    )
    if result.returncode or result.stdout.strip() != COMPATIBLE_REVISION:
        raise ValueError(
            "Reference repository must contain the reviewed compatible commit"
        )
    archive = directory / "compatible-source.tar"
    source = directory / "compatible-source"
    source.mkdir(exist_ok=True)
    run(
        "git",
        "archive",
        "--format=tar",
        "--output",
        archive,
        COMPATIBLE_REVISION,
        cwd=repository,
    )
    with tarfile.open(archive) as files:
        files.extractall(source, filter="data")
    return source


def validate_compatible_source(source, project):
    """A binary rollback never bypasses a changed migration or numeric contract."""
    compatibility = [
        Path("backend/libs/core/src/off_key_core/models/adaptive_catalog.json"),
        # Migration 005's checksum covers these converter modules too.
        *(
            Path("backend/libs/core/src/off_key_core/db") / name
            for name in (
                "catalogue_upgrade.py",
                "catalogue_v1.py",
                "catalogue_v1_models.py",
            )
        ),
    ]
    migrations = Path("backend/libs/core/src/off_key_core/db/migrations")
    compatibility.extend(
        path.relative_to(project) for path in (project / migrations).glob("*.sql")
    )
    if {path.name for path in (source / migrations).glob("*.sql")} != {
        path.name for path in (project / migrations).glob("*.sql")
    }:
        raise ValueError(
            "Compatible rollback reference has a different migration ledger"
        )
    for path in compatibility:
        if (source / path).read_text() != (project / path).read_text():
            raise ValueError(
                f"Review a new compatible rollback reference: {path} differs"
            )
    lock = Path("backend/uv.lock")
    if locked_numerical_libraries(source / lock) != locked_numerical_libraries(
        project / lock
    ):
        raise ValueError(
            "Review a new compatible rollback reference: locked Aberrant differs"
        )


def locked_numerical_libraries(lock):
    locked = sorted(
        (package["name"], package.get("version"))
        for package in tomllib.loads(lock.read_text()).get("package", [])
        if package["name"] in NUMERICAL_LIBRARIES
    )
    if {name for name, _ in locked} != set(NUMERICAL_LIBRARIES):
        raise ValueError(f"{lock} does not lock the reviewed numerical libraries")
    return locked


def selected_release(directory, target):
    names = {
        "compatible": "compatible-release.json",
        "current": "production-release.json",
    }
    if target not in names:
        raise ValueError("Select current or compatible rehearsal release")
    name = names[target]
    return json.loads((directory / name).read_text())["release"]


def release_model(base, release):
    """Change binaries while retaining real production configuration/secrets."""
    model = deepcopy(base)
    for name, service in MODEL_SERVICES.items():
        if service in model["services"]:
            model["services"][service]["image"] = release["images"][name]
    model["services"]["tactic"]["environment"]["TACTIC_RADAR_IMAGE"] = release[
        "images"
    ]["mqtt_radar"]
    return model


def image_identities(release):
    identities = {}
    for name in BUILDS:
        reference = release["images"][name]
        data = json.loads(run("docker", "image", "inspect", reference).stdout)[0]
        revision = (
            data["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
        )
        if revision != release["application_revision"]:
            raise ValueError(
                f"{name} image belongs to {revision}, not the selected release"
            )
        identities[name] = {
            "reference": reference,
            "image_id": data["Id"],
            "revision": revision,
        }
    return identities


def record_cutover(directory, release, target, restored, stack):
    """Only non-secret, verifiable identities enter the uploaded evidence."""
    path = directory / "binary-rollback-evidence.json"
    evidence = json.loads(path.read_text()) if path.exists() else {"cutovers": []}
    model = json.loads((directory / "stack/deployment-model.json").read_text())
    deployed = {}
    for name, service in MODEL_SERVICES.items():
        if service not in model["services"]:
            continue
        actual = run(
            "docker",
            "service",
            "inspect",
            "--format",
            "{{.Spec.TaskTemplate.ContainerSpec.Image}}",
            f"{stack}_{service}",
        ).stdout.strip()
        if actual.split("@")[-1] != release["images"][name].split("@")[-1]:
            raise ValueError(f"Deployed {service} does not use the selected binary")
        deployed[service] = actual
    evidence["cutovers"].append(
        {
            "target": target,
            "restored_database": restored,
            "revision": release["application_revision"],
            "images": image_identities(release),
            "deployed_service_images": deployed,
        }
    )
    path.write_text(json.dumps(evidence, indent=2))
