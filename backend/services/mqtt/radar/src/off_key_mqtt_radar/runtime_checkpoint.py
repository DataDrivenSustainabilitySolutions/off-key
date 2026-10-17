"""Authenticated database recovery envelopes, verified before deserialization."""

import hashlib
import hmac
import json
import pickle
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from .config.config import AnomalyDetectionConfig

_DOMAIN = b"OFFKEY-RADAR-RUNTIME-CHECKPOINT-V1\x00"


class ProcessorCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_message_count: int = Field(default=0, ge=0)
    message_count: int = Field(default=0, ge=0)
    anomaly_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)


class CoverageCheckpoint(BaseModel):
    """Versioned extension point for durable coverage and activity history."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    data: dict[str, Any] = Field(default_factory=dict)


class RuntimeCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detector: dict[str, Any]
    processor: ProcessorCheckpoint = Field(default_factory=ProcessorCheckpoint)
    coverage: CoverageCheckpoint = Field(default_factory=CoverageCheckpoint)
    observation_watermarks: dict[str, dict[str, FiniteFloat]] = Field(
        default_factory=dict
    )


class CheckpointHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str = Field(min_length=1)
    format_version: Literal[1] = 1
    configuration_fingerprint: str
    runtime_fingerprint: str
    processed_count: int = Field(ge=0)
    saved_at: datetime

    def signing_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()


class RuntimeCheckpointCodec:
    """Bind opaque model bytes to one monitor, configuration and runtime."""

    def __init__(
        self, service_id: str, config: AnomalyDetectionConfig, secret: bytes
    ) -> None:
        if not secret:
            raise ValueError("Database checkpoints require an authentication secret")
        self.service_id = service_id
        self.secret = secret
        configuration = {
            "monitoring": config.monitoring.model_dump(mode="json"),
            "subscription_topics": sorted(config.subscription_topics),
            "sensor_key_strategy": config.sensor_key_strategy,
            "sensor_freshness_seconds": config.sensor_freshness_seconds,
            "observation_max_age_seconds": config.observation_max_age_seconds,
            "observation_future_tolerance_seconds": (
                config.observation_future_tolerance_seconds
            ),
            "alignment_max_skew_seconds": config.alignment_max_skew_seconds,
        }
        if config.pipeline is not None:
            # Presentation metadata is deliberately absent from compatibility.
            configuration["pipeline_fingerprint"] = config.pipeline.fingerprint
        self.configuration_fingerprint = self._fingerprint(configuration)
        runtime = {
            "checkpoint_format": 1,
            "python": platform.python_version(),
            **{
                package: version(package)
                for package in (
                    "numpy",
                    "scipy",
                    "scikit-learn",
                    "pyod",
                    "nonconform",
                    "aberrant",
                )
            },
        }
        self.runtime_fingerprint = self._fingerprint(runtime)

    @staticmethod
    def _fingerprint(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def encode(self, snapshot: RuntimeCheckpoint) -> dict[str, Any]:
        header = CheckpointHeader(
            service_id=self.service_id,
            configuration_fingerprint=self.configuration_fingerprint,
            runtime_fingerprint=self.runtime_fingerprint,
            processed_count=snapshot.detector["processed_count"],
            saved_at=datetime.now(UTC),
        )
        # Freeze model objects before releasing the detector's serial owner.
        payload = pickle.dumps(snapshot.model_dump(), protocol=pickle.HIGHEST_PROTOCOL)
        signature = self._sign(header, payload)
        return {**header.model_dump(), "payload": payload, "signature": signature}

    def decode(self, record: dict[str, Any]) -> RuntimeCheckpoint:
        values = dict(record)
        payload = bytes(values.pop("payload"))
        signature = values.pop("signature")
        header = CheckpointHeader.model_validate(values)
        if not hmac.compare_digest(signature, self._sign(header, payload)):
            raise ValueError("Managed checkpoint authentication failed")
        expected = (
            self.service_id,
            self.configuration_fingerprint,
            self.runtime_fingerprint,
        )
        if (
            header.service_id,
            header.configuration_fingerprint,
            header.runtime_fingerprint,
        ) != expected:
            raise ValueError(
                "Managed checkpoint service, configuration or runtime is incompatible"
            )
        snapshot = RuntimeCheckpoint.model_validate(pickle.loads(payload))
        if snapshot.detector.get("processed_count") != header.processed_count:
            raise ValueError("Managed checkpoint count does not match its envelope")
        return snapshot

    def _sign(self, header: CheckpointHeader, payload: bytes) -> str:
        return hmac.new(
            self.secret,
            _DOMAIN + header.signing_bytes() + b"\x00" + payload,
            hashlib.sha256,
        ).hexdigest()
