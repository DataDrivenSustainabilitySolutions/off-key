"""Validate the non-secret observability policy on the Ansible controller."""

import json
import sys
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class ServiceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_mib: Annotated[int, Field(gt=0)]
    reserved_memory_mib: Annotated[int, Field(gt=0)]
    cpus: Annotated[float, Field(gt=0)]
    reserved_cpus: Annotated[float, Field(gt=0)]

    @model_validator(mode="after")
    def reservations_fit(self):
        if self.reserved_memory_mib > self.memory_mib or self.reserved_cpus > self.cpus:
            raise ValueError("A reservation cannot exceed its service limit")
        return self


class ObservabilitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stack_name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")
    data_node: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
    storage_size_gib: int = Field(default=20, ge=4, le=100)
    data_root: str = "/srv/aberration-observability"
    storage_root: str = "/var/lib/aberration-observability"
    loki: ServiceBudget = ServiceBudget(
        memory_mib=1024, reserved_memory_mib=512, cpus=1, reserved_cpus=0.25
    )
    grafana: ServiceBudget = ServiceBudget(
        memory_mib=512, reserved_memory_mib=256, cpus=0.5, reserved_cpus=0.1
    )
    alloy: ServiceBudget = ServiceBudget(
        memory_mib=256, reserved_memory_mib=64, cpus=0.5, reserved_cpus=0.1
    )
    alloy_docker: ServiceBudget = ServiceBudget(
        memory_mib=64, reserved_memory_mib=16, cpus=0.25, reserved_cpus=0.05
    )
    log_canary: ServiceBudget = ServiceBudget(
        memory_mib=16, reserved_memory_mib=4, cpus=0.05, reserved_cpus=0.01
    )

    @field_validator("data_root", "storage_root")
    @classmethod
    def owned_absolute_path(cls, value, info: ValidationInfo):
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or str(path) != value:
            raise ValueError("Storage paths must be normalized absolute paths")
        # The host helper owns these dedicated directories, never application data.
        expected = {
            "data_root": "/srv/aberration-observability",
            "storage_root": "/var/lib/aberration-observability",
        }
        if value != expected[info.field_name]:
            raise ValueError("Use the dedicated Aberration observability directories")
        return value

    def environment(self):
        values = {
            "OBSERVABILITY_NODE": self.data_node,
            "OBSERVABILITY_DATA_ROOT": self.data_root,
            "OBSERVABILITY_STACK": self.stack_name,
        }
        for name in ("loki", "grafana", "alloy", "alloy_docker", "log_canary"):
            budget = getattr(self, name)
            prefix = name.upper()
            values.update(
                {
                    f"{prefix}_MEMORY_LIMIT": f"{budget.memory_mib}M",
                    f"{prefix}_MEMORY_RESERVATION": f"{budget.reserved_memory_mib}M",
                    f"{prefix}_CPU_LIMIT": str(budget.cpus),
                    f"{prefix}_CPU_RESERVATION": str(budget.reserved_cpus),
                }
            )
        return values


if __name__ == "__main__":
    settings = ObservabilitySettings.model_validate_json(sys.stdin.read())
    print(
        json.dumps(
            {"settings": settings.model_dump(), "environment": settings.environment()}
        )
    )
