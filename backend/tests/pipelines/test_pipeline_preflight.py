"""Runtime preflight trusts only its own job and a matching, bounded report."""

import json
from types import SimpleNamespace

import docker.errors
import pytest
from off_key_core.models.pipelines import pipeline_catalog_id
from off_key_tactic_middleware.services.orchestration import workload_identity
from off_key_tactic_middleware.services.pipelines import preflight
from off_key_tactic_middleware.services.pipelines.preflight import (
    PipelinePreflight,
    PreflightRejected,
)

IMAGE = "registry/radar@sha256:" + "a" * 64
EXECUTION = SimpleNamespace(fingerprint="f" * 64)


class Job:
    """A Swarm service as docker-py returns it."""

    def __init__(self, activation_id="a1", image=IMAGE, states=("complete",), log=b""):
        self.id = f"service-{activation_id}"
        self.attrs = {
            "Spec": {
                "Labels": workload_identity.preflight_identity_labels(activation_id),
                "TaskTemplate": {"ContainerSpec": {"Image": image}},
            }
        }
        self.states = states
        self.log = log

    def tasks(self):
        return [{"Status": {"State": state, "Err": "boom"}} for state in self.states]

    def logs(self, **_):
        return self.log


class Docker:
    """AsyncDocker over an in-memory services collection."""

    def __init__(self, existing=None, create_error=None):
        self.existing = existing
        self.create_error = create_error
        self.created = []
        self.client = SimpleNamespace(
            services=SimpleNamespace(get=self._get, create=self._create),
            images=SimpleNamespace(
                get=lambda reference: SimpleNamespace(
                    attrs={"RepoDigests": [f"{reference}@sha256:{'b' * 64}"]},
                    id="sha256:local",
                )
            ),
        )

    async def run(self, function, *args, **kwargs):
        return function(*args, **kwargs)

    def _get(self, name):
        if self.existing is None:
            raise docker.errors.NotFound(name)
        return self.existing

    def _create(self, **spec):
        self.created.append(spec)
        if self.create_error is not None:
            self.existing = Job()
            raise self.create_error
        self.existing = Job()
        return self.existing


class Workloads:
    def __init__(self, docker):
        self.async_docker = docker
        self.removed = []

    async def remove(self, workload_id):
        self.removed.append(workload_id)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(workload_identity, "controller_id", lambda: "controller")
    config = SimpleNamespace(
        radar_image="registry/radar:1",
        pipeline_preflight_timeout_seconds=0.05,
        radar_defaults=SimpleNamespace(memory_limit_mb=384),
        docker=SimpleNamespace(
            resource_budget=SimpleNamespace(
                cpu_limit_nanos=500_000_000, memory_limit_bytes=512 * 2**20
            ),
            default_constraints=[],
        ),
    )
    monkeypatch.setattr(
        preflight, "get_tactic_settings", lambda: SimpleNamespace(config=config)
    )
    return config


def report(**fields):
    return json.dumps(
        {"ok": True, "fingerprint": EXECUTION.fingerprint}
        | {"catalog_id": pipeline_catalog_id()}
        | fields
    ).encode()


@pytest.mark.asyncio
async def test_tag_resolves_to_its_repository_digest_and_digests_pass_through(
    settings,
):
    runner = PipelinePreflight(Workloads(Docker()))
    assert await runner.resolve_image() == f"registry/radar:1@sha256:{'b' * 64}"
    settings.radar_image = IMAGE
    assert await runner.resolve_image() == IMAGE


@pytest.mark.asyncio
async def test_matching_report_is_accepted_and_the_job_removed():
    job = Job(log=b"progress line\n" + report() + b"\n")
    workloads = Workloads(Docker(existing=job))

    result = await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)

    assert result["ok"] is True
    assert workloads.removed == [job.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("states", "log", "message"),
    [
        (("failed",), report(ok=False, errors=["bad n0"]), "bad n0"),
        (("complete",), b"not json", "Runtime preflight failed"),
        (("complete",), report(fingerprint="other"), "differs from the control plane"),
        (("complete",), report(catalog_id="old"), "differs from the control plane"),
    ],
)
async def test_failed_or_foreign_reports_are_rejected(states, log, message):
    job = Job(states=states, log=log)
    workloads = Workloads(Docker(existing=job))

    with pytest.raises(PreflightRejected, match=message):
        await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)
    assert workloads.removed == [job.id]


@pytest.mark.asyncio
async def test_unfinished_job_times_out_with_its_task_progress():
    job = Job(states=("running",))
    workloads = Workloads(Docker(existing=job))

    with pytest.raises(PreflightRejected, match=r'timed out:.*"state":"running"'):
        await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)
    assert workloads.removed == [job.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "message"),
    [
        ({"activation_id": "other"}, "belongs to a different owner"),
        (
            {"image": "registry/radar@sha256:" + "c" * 64},
            "differs from persisted intent",
        ),
    ],
)
async def test_a_job_with_another_identity_is_never_trusted(identity, message):
    workloads = Workloads(Docker(existing=Job(**identity)))

    with pytest.raises(RuntimeError, match=message):
        await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)
    assert workloads.removed == []


@pytest.mark.asyncio
async def test_a_concurrent_create_adopts_the_job_that_won():
    docker_ = Docker(
        create_error=docker.errors.APIError("exists", SimpleNamespace(status_code=409))
    )
    runner = PipelinePreflight(Workloads(docker_))

    job = await runner._ensure(
        "a1", SimpleNamespace(model_dump_json=lambda: "{}"), IMAGE
    )

    assert job is docker_.existing
    (spec,) = docker_.created
    assert spec["name"] == "radar-preflight-a1"
    assert spec["command"] == ["/app/bin/python", "-m", "off_key_mqtt_radar.preflight"]


def test_report_reading_is_bounded_and_closes_the_stream():
    closed = []

    class Stream:
        def __iter__(self):
            yield b"x" * 131072
            yield b"y"

        def close(self):
            closed.append(True)

    job = Job()
    job.logs = lambda **_: Stream()
    with pytest.raises(PreflightRejected, match="bounded response budget"):
        PipelinePreflight._read_report(job)
    assert closed == [True]
