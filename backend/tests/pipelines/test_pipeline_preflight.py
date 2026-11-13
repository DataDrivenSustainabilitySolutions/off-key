"""Runtime preflight trusts only its own job and a matching report."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from off_key_core.models.pipelines import pipeline_catalog_id
from off_key_tactic_middleware.services.orchestration import workload_identity
from off_key_tactic_middleware.services.orchestration.radar_workloads import (
    PREFLIGHT_MODULE,
    Workload,
)
from off_key_tactic_middleware.services.pipelines import preflight
from off_key_tactic_middleware.services.pipelines.preflight import (
    PipelinePreflight,
    PreflightRejected,
)

IMAGE = "registry/radar@sha256:" + "a" * 64
EXECUTION = SimpleNamespace(fingerprint="f" * 64, model_dump_json=lambda: "{}")


def job(activation_id="a1", runtime=IMAGE, state="complete", output=""):
    """A preflight row as RadarWorkloadManager returns it."""
    return Workload(
        id=f"workload-{activation_id}",
        name=workload_identity.preflight_workload_name(activation_id),
        kind="preflight",
        runtime=runtime,
        labels=workload_identity.preflight_identity_labels(activation_id),
        state=state,
        output=output,
        detail="exit code 1" if state == "failed" else None,
    )


class Workloads:
    """RadarWorkloadManager over one in-memory row."""

    def __init__(self, existing=None, finished=None):
        self.existing = existing
        # What the pool reports once the job ended.
        self.finished = finished
        self.submitted = []
        self.removed = []

    async def submit(self, **spec):
        self.submitted.append(spec)
        if self.existing is None:
            self.existing = job(runtime=spec["runtime"])
        return self.existing

    async def get(self, workload_id):
        return self.finished or self.existing

    async def find_named(self, name):
        return self.existing

    async def remove(self, workload_id):
        self.removed.append(workload_id)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    config = SimpleNamespace(
        radar_image="registry/radar:1",
        pipeline_preflight_timeout_seconds=0.05,
        forecast_api_url="",
        radar_defaults=SimpleNamespace(memory_limit_mb=384),
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
    )


@pytest.mark.asyncio
async def test_a_new_activation_pins_the_runtime_the_pool_runs(settings):
    assert await PipelinePreflight(Workloads()).resolve_image() == "registry/radar:1"


@pytest.mark.asyncio
async def test_matching_report_is_accepted_and_the_job_removed():
    pending = job(state="pending")
    workloads = Workloads(
        existing=pending,
        finished=replace(pending, state="complete", output=f"progress\n{report()}\n"),
    )

    result = await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)

    assert result["ok"] is True
    assert workloads.removed == [pending.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "output", "message"),
    [
        ("failed", report(ok=False, errors=["bad n0"]), "bad n0"),
        ("failed", "", "exit code 1"),
        ("complete", "not json", "Runtime preflight failed"),
        ("shutdown", report(), "Runtime preflight failed"),
        ("complete", report(fingerprint="other"), "differs from the control plane"),
        ("complete", report(catalog_id="old"), "differs from the control plane"),
    ],
)
async def test_failed_or_foreign_reports_are_rejected(state, output, message):
    existing = job(state=state, output=output)
    workloads = Workloads(existing=existing)

    with pytest.raises(PreflightRejected, match=message):
        await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)
    assert workloads.removed == [existing.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "progress"),
    [("pending", "no RADAR pool replica has room"), ("running", "state=running")],
)
async def test_unfinished_job_times_out_with_its_progress(state, progress):
    existing = job(state=state)
    workloads = Workloads(existing=existing)

    with pytest.raises(PreflightRejected, match=f"timed out: {progress}"):
        await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)
    assert workloads.removed == [existing.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "message"),
    [
        ({"activation_id": "other"}, "belongs to a different owner"),
        ({"runtime": "registry/radar@sha256:" + "c" * 64}, "differs from persisted"),
    ],
)
async def test_a_job_with_another_identity_is_never_trusted(identity, message):
    workloads = Workloads(existing=job(**identity))

    with pytest.raises(RuntimeError, match=message):
        await PipelinePreflight(workloads).run("a1", EXECUTION, IMAGE)
    assert workloads.removed == []


@pytest.mark.asyncio
async def test_a_job_is_a_one_off_workload_of_the_pinned_runtime():
    workloads = Workloads()

    await PipelinePreflight(workloads)._ensure(
        "a1", SimpleNamespace(model_dump_json=lambda: "{}"), IMAGE
    )

    (spec,) = workloads.submitted
    assert spec["name"] == "radar-preflight-a1"
    assert spec["kind"] == "preflight"
    assert spec["module"] == PREFLIGHT_MODULE
    assert spec["runtime"] == IMAGE
    assert spec["restart"] is False
    assert spec["labels"] == workload_identity.preflight_identity_labels("a1")
    assert "FORECAST_API_URL" not in spec["environment"]


@pytest.mark.asyncio
async def test_a_job_learns_where_the_forecast_service_is(settings):
    """Preflight rejects a pretrained forecaster step where no service is named."""
    settings.forecast_api_url = "http://forecast:8020"
    workloads = Workloads()

    await PipelinePreflight(workloads)._ensure(
        "a1", SimpleNamespace(model_dump_json=lambda: "{}"), IMAGE
    )

    (spec,) = workloads.submitted
    assert set(spec["environment"]) == {
        "RADAR_PIPELINE_CONFIG",
        "RADAR_MEMORY_LIMIT_MB",
        "FORECAST_API_URL",
    }
    assert spec["environment"]["FORECAST_API_URL"] == "http://forecast:8020"


@pytest.mark.asyncio
async def test_cleanup_removes_only_its_own_job():
    workloads = Workloads(existing=job())
    await PipelinePreflight(workloads).remove_for("a1")
    assert workloads.removed == ["workload-a1"]

    with pytest.raises(RuntimeError, match="different owner"):
        await PipelinePreflight(Workloads(existing=job("other"))).remove_for("a1")
    absent = Workloads()
    await PipelinePreflight(absent).remove_for("a1")
    assert absent.removed == []
