"""Subscription-free constructor validation in the exact execution runtime.

A preflight is a one-off workload of the RADAR pool: a replica running the
requested runtime builds the pipeline, prints its report as the last line of
its standard output and exits. The pool keeps the tail of that output on the
row, and this reads the report from there.
"""

import asyncio
import json

from off_key_core.models.pipelines import pipeline_catalog_id
from off_key_core.schemas.pipelines import PipelineIssue

from ...config.config import get_tactic_settings
from ..orchestration.radar_workloads import PREFLIGHT_MODULE, Workload
from ..orchestration.workload_identity import (
    has_labels,
    preflight_identity_labels,
    preflight_workload_name,
)

PREFLIGHT_DONE = frozenset({"complete", "failed", "shutdown"})


class PreflightRejected(ValueError):
    def __init__(self, message: str, *, issues: list[PipelineIssue] | None = None):
        super().__init__(message)
        self.issues = issues or []


class PipelinePreflight:
    def __init__(self, workloads):
        self.workloads = workloads

    async def resolve_image(self) -> str:
        """The runtime a new activation pins: the one the pool runs now."""
        return get_tactic_settings().config.radar_image

    async def run(self, activation_id: str, execution, image: str):
        workload = await self._ensure(activation_id, execution, image)
        self._validate_identity(workload, activation_id, image)
        try:
            finished = await self._wait_for_completion(workload)
            return self._report(finished, execution)
        except TimeoutError as exc:
            raise PreflightRejected(
                f"Runtime preflight timed out: {await self._progress_detail(workload)}"
            ) from exc
        finally:
            # Preserve retryable remote uncertainty until shutdown is confirmed.
            await self.workloads.remove(workload.id)

    async def _progress_detail(self, workload: Workload) -> str:
        try:
            current = await self.workloads.get(workload.id)
        except Exception as error:
            return f"status unavailable ({type(error).__name__})"
        if current is None:
            return "workload disappeared"
        if current.state == "pending":
            return "no RADAR pool replica has room for it yet"
        return f"state={current.state}"

    async def _ensure(self, activation_id, execution, image) -> Workload:
        settings = get_tactic_settings().config
        environment = {
            "RADAR_PIPELINE_CONFIG": execution.model_dump_json(),
            "RADAR_MEMORY_LIMIT_MB": str(settings.radar_defaults.memory_limit_mb),
        }
        if settings.forecast_api_url:
            # A pretrained forecaster step is rejected where no service is named.
            # Preflight names it without connecting.
            environment["FORECAST_API_URL"] = settings.forecast_api_url
        return await self.workloads.submit(
            name=preflight_workload_name(activation_id),
            kind="preflight",
            module=PREFLIGHT_MODULE,
            runtime=image,
            environment=environment,
            labels=preflight_identity_labels(activation_id),
            restart=False,
        )

    async def remove_for(self, activation_id):
        """Remove the activation's preflight job when it is still ours."""
        workload = await self.workloads.find_named(
            preflight_workload_name(activation_id)
        )
        if workload is None:
            return
        self.validate_cleanup_identity(workload, activation_id)
        await self.workloads.remove(workload.id)

    @staticmethod
    def validate_cleanup_identity(workload, activation_id):
        if not has_labels(workload, preflight_identity_labels(activation_id)):
            raise RuntimeError("Preflight workload belongs to a different owner")

    @staticmethod
    def _validate_identity(workload: Workload, activation_id, image):
        PipelinePreflight.validate_cleanup_identity(workload, activation_id)
        if workload.runtime != image:
            raise RuntimeError(
                "Preflight workload identity differs from persisted intent"
            )

    async def _wait_for_completion(self, workload: Workload) -> Workload:
        settings = get_tactic_settings().config
        async with asyncio.timeout(settings.pipeline_preflight_timeout_seconds):
            while True:
                current = await self.workloads.get(workload.id)
                if current is None:
                    raise PreflightRejected("Preflight workload disappeared")
                if current.state in PREFLIGHT_DONE:
                    return current
                await asyncio.sleep(0.25)

    @staticmethod
    def _report(workload: Workload, execution):
        reports = []
        for line in (workload.output or "").splitlines():
            try:
                reports.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        report = reports[-1] if reports else {}
        if workload.state != "complete" or not report.get("ok"):
            fallback = workload.detail or "Runtime preflight failed"
            raise PreflightRejected(
                str(report.get("errors", report.get("error", fallback)))[:4000],
                issues=[
                    PipelineIssue.model_validate(issue)
                    for issue in report.get("issues", [])[:64]
                ],
            )
        if (
            report.get("fingerprint") != execution.fingerprint
            or report.get("catalog_id") != pipeline_catalog_id()
        ):
            raise PreflightRejected(
                "Runtime preflight catalogue or configuration differs "
                "from the control plane"
            )
        return report
