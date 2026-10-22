"""Subscription-free constructor validation in the exact execution image."""

import asyncio
import json

import docker
from docker.types import Resources, RestartPolicy, ServiceMode
from off_key_core.models.pipelines import pipeline_catalog_id

from ...config.config import get_tactic_settings
from ...facades.docker import SWARM_TASK_DONE
from ..orchestration.workload_identity import (
    has_labels,
    preflight_identity_labels,
    preflight_workload_name,
)


class PreflightRejected(ValueError):
    pass


class PipelinePreflight:
    def __init__(self, workloads):
        self.workloads = workloads
        self.docker = workloads.async_docker

    async def resolve_image(self) -> str:
        reference = get_tactic_settings().config.radar_image
        if "@sha256:" in reference:
            return reference
        image = await self.docker.run(self.docker.client.images.get, reference)
        digests = image.attrs.get("RepoDigests", [])
        return digests[0] if digests else image.id

    async def run(self, activation_id: str, execution, image: str):
        workload = await self._ensure(activation_id, execution, image)
        self._validate_identity(workload, activation_id, image)
        try:
            succeeded = await self._wait_for_completion(workload)
            return await self._report(workload, execution, succeeded)
        except TimeoutError as exc:
            try:
                detail = await self._progress_detail(workload)
            except Exception as diagnostic_error:
                detail = f"status unavailable ({type(diagnostic_error).__name__})"
            raise PreflightRejected(f"Runtime preflight timed out: {detail}") from exc
        finally:
            # Preserve retryable remote uncertainty until shutdown is confirmed.
            await self.workloads.remove(workload.id)

    async def _progress_detail(self, workload):
        tasks = await self.docker.run(workload.tasks)
        progress = [
            {
                "state": task.get("Status", {}).get("State"),
                "message": task.get("Status", {}).get("Err")
                or task.get("Status", {}).get("Message"),
            }
            for task in tasks[-4:]
        ]
        return json.dumps(progress, separators=(",", ":"))[:1500]

    async def _ensure(self, activation_id, execution, image):
        collection = self.docker.client.services
        name = preflight_workload_name(activation_id)
        try:
            return await self.docker.run(collection.get, name)
        except docker.errors.NotFound:
            pass
        try:
            return await self._create(activation_id, execution, image)
        except docker.errors.APIError as exc:
            if exc.status_code != 409:
                raise
            return await self.docker.run(collection.get, name)

    async def _create(self, activation_id, execution, image):
        settings = get_tactic_settings().config
        budget = settings.docker.resource_budget
        environment = {
            "RADAR_PIPELINE_CONFIG": execution.model_dump_json(),
            "RADAR_MEMORY_LIMIT_MB": str(settings.radar_defaults.memory_limit_mb),
        }
        command = ["/app/bin/python", "-m", "off_key_mqtt_radar.preflight"]
        return await self.docker.run(
            self.docker.client.services.create,
            image=image,
            name=preflight_workload_name(activation_id),
            command=command,
            env=environment,
            labels=preflight_identity_labels(activation_id),
            mode=ServiceMode("replicated", replicas=1),
            restart_policy=RestartPolicy(condition="none"),
            resources=Resources(
                cpu_limit=budget.cpu_limit_nanos,
                mem_limit=budget.memory_limit_bytes,
            ),
            constraints=settings.docker.default_constraints,
        )

    async def remove_for(self, activation_id):
        """Remove the activation's preflight job when it is still ours."""
        try:
            workload = await self.docker.run(
                self.docker.client.services.get, preflight_workload_name(activation_id)
            )
        except docker.errors.NotFound:
            return
        self.validate_cleanup_identity(workload, activation_id)
        await self.workloads.remove(workload.id)

    @staticmethod
    def validate_cleanup_identity(workload, activation_id):
        if not has_labels(workload, preflight_identity_labels(activation_id)):
            raise RuntimeError("Preflight workload belongs to a different owner")

    @staticmethod
    def _validate_identity(workload, activation_id, image):
        PipelinePreflight.validate_cleanup_identity(workload, activation_id)
        actual_image = (
            workload.attrs.get("Spec", {})
            .get("TaskTemplate", {})
            .get("ContainerSpec", {})
            .get("Image")
        )
        if actual_image != image:
            raise RuntimeError(
                "Preflight workload identity differs from persisted intent"
            )

    async def _wait_for_completion(self, workload):
        settings = get_tactic_settings().config
        async with asyncio.timeout(settings.pipeline_preflight_timeout_seconds):
            while True:
                tasks = await self.docker.run(workload.tasks)
                states = [task.get("Status", {}).get("State") for task in tasks]
                if states and all(state in SWARM_TASK_DONE for state in states):
                    return all(state == "complete" for state in states)
                await asyncio.sleep(0.25)

    async def _report(self, workload, execution, succeeded):
        output = await self.docker.run(self._read_report, workload)
        reports = []
        for line in output.decode("utf-8", errors="replace").splitlines():
            try:
                reports.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        report = reports[-1] if reports else {}
        if not succeeded or not report.get("ok"):
            raise PreflightRejected(
                str(
                    report.get(
                        "errors", report.get("error", "Runtime preflight failed")
                    )
                )[:4000]
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

    @staticmethod
    def _read_report(workload):
        """Read Swarm's lazy log chunks on the Docker thread."""
        output = workload.logs(stdout=True, stderr=False, tail=100)
        chunks = (output,) if isinstance(output, bytes) else output
        result = bytearray()
        try:
            for chunk in chunks:
                if len(result) + len(chunk) > 131072:
                    raise PreflightRejected(
                        "Preflight report exceeds its bounded response budget"
                    )
                result.extend(chunk)
        finally:
            close = getattr(output, "close", None)
            if close is not None:
                close()
        return bytes(result)
