"""Build and select two real, schema-compatible rehearsal releases.

The reference is the commit that completes the Timestral forecaster step,
carrying migration 025 and Aberrant 1.5.0 numerics. It is not
an eligible production release and proves no pre-feature compatibility.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from support import ROOT, load_script, run

image_sources = load_script("image_sources")

COMPATIBLE_REVISION = "ad919d98e56a4e0e3dbcb8c3254f51e034d38251"
REGISTRY = "offkey-smoke-registry"
# Detector numerics; other locked packages may differ as in a real rollback.
NUMERICAL_LIBRARIES = ("aberrant",)
BUILDS = {
    "api": ("off-key-api-gateway", "services/api/gateway"),
    "tactic": ("off-key-tactic-middleware", "services/middleware/tactic"),
    "mqtt_proxy": ("off-key-mqtt-proxy", "services/mqtt/proxy"),
    "mqtt_radar": ("off-key-mqtt-radar", "services/mqtt/radar"),
    "db_sync": ("off-key-db-sync", "services/db/sync"),
    "forecast": ("off-key-forecast", "services/forecast/service"),
    "frontend": ("off-key-frontend", None),
    "docs": ("off-key-docs", "docs"),
}
MODEL_SERVICES = {
    "api": "api",
    "tactic": "tactic",
    "mqtt_proxy": "mqtt-proxy",
    "mqtt_radar": "mqtt-radar",
    "db_sync": "db-sync",
    "forecast": "forecast",
    "frontend": "frontend",
    "docs": "docs",
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


def build_cache_options(service, revision, write=False):
    """The CI image job owns current caches; rollback has its own immutable scope."""
    suffix = service.removeprefix("off-key-")
    scopes = [f"docker-validate-{suffix}", f"docker-publish-{suffix}"]
    options = []
    if revision == COMPATIBLE_REVISION:
        rollback = f"docker-rollback-{revision}-{suffix}"
        scopes.insert(0, rollback)
        # Failure to save an optional cache must not invalidate a real image build.
        options += [
            "--cache-to",
            f"type=gha,version=2,scope={rollback},mode=max,ignore-error=true",
        ]
    elif write:
        options += [
            "--cache-to",
            f"type=gha,version=2,scope=docker-validate-{suffix},mode=max,ignore-error=true",
        ]
    for scope in scopes:
        options += ["--cache-from", f"type=gha,version=2,scope={scope}"]
    return options


def image_reference(service, revision):
    return f"localhost:5010/{service}:sha-{revision[:12]}"


def build_arguments(service, source, revision, project):
    """The one set of image inputs every pre-release CI job tests."""
    image_revision = revision
    if revision != COMPATIBLE_REVISION:
        image_revision = image_sources.source_revision(service, revision, project)
    args = [
        "--label",
        f"org.opencontainers.image.revision={image_revision}",
        "--label",
        "org.opencontainers.image.source=https://github.com/DataDrivenSustainabilitySolutions/off-key",
        "--label",
        f"org.opencontainers.image.version=sha-{image_revision}",
        "-t",
        image_reference(service, revision),
    ]
    if source == "docs":
        # The rollback source predates this hosting recipe but contains its own
        # docs, generator and requirements. Build only that revision's content.
        return args + ["-f", str(ROOT.parent / "dev/docs/Dockerfile"), str(project)]
    if source is None:
        return args + ["--target", "production", str(Path(project) / "frontend")]
    return args + [
        "--build-arg",
        f"SERVICE_NAME={service}",
        "--build-arg",
        f"SERVICE_ROOT={source}",
        "--build-arg",
        f"GIT_COMMIT={image_revision}",
        str(Path(project) / "backend"),
    ]


def push_local(reference):
    """Push to the rehearsal registry and return the digest it now serves."""
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
    return next(
        value
        for value in references
        if value.startswith(reference.rsplit(":", 1)[0] + "@")
    )


def build_local_images(release, revision, project):
    start_registry()

    def build(item):
        name, (service, source) = item
        args = ["docker", "build"]
        if os.getenv("OFFKEY_BUILD_CACHE") == "1":
            args = ["docker", "buildx", "build", "--load"]
            args += build_cache_options(service, revision)
        args += build_arguments(service, source, revision, project)
        print(f"Building production {name} at {revision}", flush=True)
        run(*args, timeout=900)
        return name, push_local(image_reference(service, revision))

    with ThreadPoolExecutor(max_workers=3) as pool:
        release["images"].update(pool.map(build, BUILDS.items()))
    if revision != COMPATIBLE_REVISION:
        release["image_revisions"] = image_sources.revisions(revision, project)


def loaded_identities(revision):
    """Image IDs of this revision's loaded images; each must carry its revision."""
    identities = {}
    sources = image_sources.revisions(revision)
    for name, (service, _) in BUILDS.items():
        reference = image_reference(service, revision)
        data = json.loads(run("docker", "image", "inspect", reference).stdout)[0]
        label = (data["Config"].get("Labels") or {}).get(
            "org.opencontainers.image.revision"
        )
        if label != sources[name]:
            raise ValueError(f"{name} image belongs to {label}, not {sources[name]}")
        identities[name] = {"reference": reference, "image_id": data["Id"]}
    return identities


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_ci_images(revision, project, archive):
    """Build each current image once per CI run, with the rehearsal's inputs.

    The archive travels only inside this run, as an artifact; its digest and the
    image IDs travel as job outputs, so a consumer verifies both before use.
    """
    if not shutil.which("zstd"):
        raise ValueError("zstd is required to export the CI images")

    def build(item):
        _, (service, source) = item
        run(
            "docker",
            "buildx",
            "build",
            "--load",
            *build_cache_options(service, revision, write=True),
            *build_arguments(service, source, revision, project),
            timeout=1800,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(build, BUILDS.items()))
    identities = loaded_identities(revision)
    references = [item["reference"] for item in identities.values()]
    with Path(archive).open("wb") as output:
        save = subprocess.Popen(["docker", "save", *references], stdout=subprocess.PIPE)
        compress = subprocess.run(
            ["zstd", "-T0", "-3", "-q", "-c"],
            stdin=save.stdout,
            stdout=output,
            check=False,
        )
        save.stdout.close()
        if save.wait() or compress.returncode:
            raise AssertionError("Exporting the CI images failed")
    return {
        "revision": revision,
        "archive_sha256": sha256_file(archive),
        "images": identities,
    }


def load_ci_images(archive, manifest, expected_sha256, revision):
    """Load exactly the images this run's image job built and tested."""
    if manifest["revision"] != revision:
        raise ValueError(f"CI images belong to {manifest['revision']}, not {revision}")
    if manifest["archive_sha256"] != expected_sha256:
        raise ValueError("The CI image manifest does not match its recorded digest")
    if sha256_file(archive) != expected_sha256:
        raise ValueError(
            "The CI image archive differs from the one the image job built"
        )
    if set(manifest["images"]) != set(BUILDS):
        raise ValueError("The CI image manifest does not cover every application image")
    decompress = subprocess.Popen(
        ["zstd", "-d", "-q", "-c", str(archive)], stdout=subprocess.PIPE
    )
    loaded = subprocess.run(
        ["docker", "load", "-q"], stdin=decompress.stdout, check=False
    )
    decompress.stdout.close()
    if decompress.wait() or loaded.returncode:
        raise AssertionError("Loading the CI images failed")
    actual = loaded_identities(revision)
    for name, identity in manifest["images"].items():
        if actual[name] != identity:
            raise ValueError(f"Loaded {name} image differs from the tested build")
    return actual


def push_loaded_images(release, revision):
    """Serve this run's verified images from the rehearsal registry."""
    start_registry()
    for name, identity in loaded_identities(revision).items():
        release["images"][name] = push_local(identity["reference"])


def compatible_release(directory, project, reference_repository=None):
    """Build actual older source; refuse unnoticed schema/numerical changes."""
    current = json.loads((directory / "production-release.json").read_text())["release"]
    if current["application_revision"] == COMPATIBLE_REVISION:
        raise ValueError("Binary rollback requires two different source revisions")
    source = archive_compatible_source(directory, reference_repository or project)
    validate_compatible_source(source, project)
    release = deepcopy(current)
    release.pop("image_revisions", None)
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
    sources = image_sources.expected_revisions(release)
    for name in BUILDS:
        reference = release["images"][name]
        data = json.loads(run("docker", "image", "inspect", reference).stdout)[0]
        revision = (
            data["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
        )
        if revision != sources[name]:
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


def main():
    parser = argparse.ArgumentParser(description="Build or load this run's CI images")
    parser.add_argument("action", choices=("build-ci-images", "load-ci-images"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if args.action == "build-ci-images":
        project = Path(__file__).resolve().parents[2]
        manifest = build_ci_images(args.revision, project, args.archive)
        args.manifest.write_text(json.dumps(manifest, sort_keys=True))
    else:
        if not args.sha256:
            parser.error("load-ci-images requires --sha256")
        manifest = json.loads(args.manifest.read_text())
        load_ci_images(args.archive, manifest, args.sha256, args.revision)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
