"""Disposable multi-node Docker lab; never initializes the caller's Swarm."""

import json
import os
import subprocess
import time
from contextlib import contextmanager

DIND_IMAGE = "docker:29-dind@sha256:9e79b879b177fbd72c34376a3dd3d91747da5db49e1f560f76aea59561471977"


class Docker:
    def __init__(self, environment=None):
        self.environment = dict(environment or os.environ)

    def __call__(self, *args, input=None, timeout=90):
        try:
            result = subprocess.run(
                ["docker", *map(str, args)],
                check=False,
                input=input,
                capture_output=True,
                text=True,
                env=self.environment,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Docker {args[0]} operation timed out") from None
        if result.returncode:
            # Swarm commands may include join tokens: never print argv/results.
            if args[0] == "stack":
                # The lab stack contains only public configuration and synthetic
                # records; its schema errors are safe and necessary diagnostics.
                raise RuntimeError(
                    "Non-secret lab stack rejected: " + result.stderr.strip()
                )
            if args[:2] == ("swarm", "init"):
                # Join credentials are printed on stdout only, which stays private.
                raise RuntimeError(
                    "Disposable Swarm init rejected: " + result.stderr.strip()
                )
            raise RuntimeError(
                f"Docker {args[0]} operation failed ({result.returncode})"
            )
        return result.stdout

    def json(self, *args):
        return json.loads(self(*args))


def wait(probe, description, seconds=180):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            return probe()
        except (
            ValueError,
            RuntimeError,
            subprocess.SubprocessError,
            AssertionError,
        ) as error:
            last = type(error).__name__
            time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {description} ({last})")


@contextmanager
def engine_environment(engine):
    previous = os.environ.copy()
    os.environ.clear()
    os.environ.update(engine.environment)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


class Lab:
    def __init__(self, identity):
        self.outer = Docker()
        self.identity = identity
        self.network = f"offkey-obs-{identity}"
        self.containers = []
        self.engines = {}
        self.image_tags = {}
        self.content_ids = {}

    def start(self):
        try:
            self.outer("image", "inspect", DIND_IMAGE)
        except RuntimeError:
            self.outer("pull", DIND_IMAGE, timeout=180)
        self.outer(
            "network",
            "create",
            "--label",
            f"off-key.observability-test={self.identity}",
            self.network,
        )
        for suffix, memory, cpus in (
            ("manager", "1g", "1"),
            ("data", "3g", "2"),
            ("worker", "2g", "2"),
        ):
            name = f"{self.network}-{suffix}"
            self.outer(
                "run",
                "-d",
                "--privileged",
                "--name",
                name,
                "--hostname",
                name,
                "--label",
                f"off-key.observability-test={self.identity}",
                "--network",
                self.network,
                "--memory",
                memory,
                "--cpus",
                cpus,
                "-e",
                "DOCKER_TLS_CERTDIR=",
                DIND_IMAGE,
                "--storage-driver=overlay2",
                "--bridge=none",
                "--ip6tables=false",
            )
            self.containers.append(name)
            address = self.outer.json("inspect", name)[0]["NetworkSettings"][
                "Networks"
            ][self.network]["IPAddress"]
            environment = self.outer.environment | {
                "DOCKER_HOST": f"tcp://{address}:2375"
            }
            for key in ("DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "DOCKER_CONTEXT"):
                environment.pop(key, None)
            engine = Docker(environment)

            def identified_engine(engine=engine, name=name):
                if engine("info", "--format", "{{.Name}}").strip() != name:
                    raise RuntimeError(
                        "Refusing to initialize an engine outside this lab"
                    )

            wait(
                identified_engine,
                f"{suffix} engine",
            )
            self.engines[suffix] = engine
        manager = self.engines["manager"]
        address = (
            manager.environment["DOCKER_HOST"].removeprefix("tcp://").split(":")[0]
        )
        manager(
            "swarm",
            "init",
            "--advertise-addr",
            address,
            "--data-path-addr",
            address,
            "--data-path-port",
            "4799",
            "--default-addr-pool",
            "10.241.0.0/16",
        )
        token = manager("swarm", "join-token", "-q", "worker").strip()
        for suffix in ("data", "worker"):
            self.engines[suffix]("swarm", "join", "--token", token, f"{address}:2377")
        return self

    def load_images(self, images, suffix):
        destination = f"{self.network}-{suffix}"
        for image in images:
            if image not in self.image_tags:
                try:
                    metadata = self.outer.json("image", "inspect", image)[0]
                except RuntimeError:
                    self.outer("pull", image, timeout=240)
                    metadata = self.outer.json("image", "inspect", image)[0]
                tag = f"offkey-observability-test/{self.identity}-{len(self.image_tags)}:verified"
                self.outer("image", "tag", image, tag)
                self.image_tags[image] = tag
                self.content_ids[image] = metadata["Id"]
        # Docker archives do not preserve registry manifest references. Temporary
        # tags retain the verified images; the offline Swarm uses their immutable
        # content IDs, checked after import, without contacting a registry.
        source = subprocess.Popen(
            ["docker", "save", *[self.image_tags[image] for image in images]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.outer.environment,
        )
        target = subprocess.Popen(
            ["docker", "exec", "-i", destination, "docker", "load"],
            stdin=source.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.outer.environment,
        )
        source.stdout.close()
        source.stdout = None
        target.communicate(timeout=300)
        source.communicate(timeout=300)
        if target.returncode or source.returncode:
            raise RuntimeError("Pinned test image transfer failed")
        for image in images:
            actual = self.engines[suffix].json(
                "image", "inspect", self.content_ids[image]
            )[0]["Id"]
            if actual != self.content_ids[image]:
                raise RuntimeError(
                    "Imported image content differs from the pinned source"
                )

    def close(self):
        for name in reversed(self.containers):
            metadata = self.outer.json("inspect", name)[0]
            if (
                metadata["Config"].get("Labels", {}).get("off-key.observability-test")
                != self.identity
            ):
                raise RuntimeError(
                    "Refusing cleanup of a container owned by another task"
                )
            self.outer("rm", "-f", "-v", name, timeout=120)
        if self.containers:
            self.outer("network", "rm", self.network)
        for tag in self.image_tags.values():
            self.outer("image", "rm", tag)
