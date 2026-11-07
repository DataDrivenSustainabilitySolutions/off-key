"""Devices, measurements and evidence addressed by catalogue id."""

from datetime import UTC, datetime
from typing import Any

from off_key_core.db.models import Charger
from off_key_core.schemas.collection_activity import reading_is_receiving
from off_key_core.schemas.system import SystemSnapshot, SystemStream
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import ValidationError
from ...repositories import MonitoringEvidenceRepository, TelemetryRepository
from .catalogue_ids import CatalogueIds
from .telemetry import TelemetryQueryService


class CatalogueDataService:
    def __init__(self, session: AsyncSession, snapshot: SystemSnapshot):
        self._session = session
        self._ids = CatalogueIds(snapshot)
        self._runtime = snapshot.runtime
        self._telemetry = TelemetryQueryService(TelemetryRepository(session))
        self._evidence = MonitoringEvidenceRepository(session)

    async def _statuses(self, entities: set[str]) -> dict[str, Charger]:
        if not entities:
            return {}
        result = await self._session.execute(
            select(Charger).where(Charger.charger_id.in_(sorted(entities)))
        )
        return {charger.charger_id: charger for charger in result.scalars().all()}

    async def devices(self, *, active: bool | None) -> list[dict[str, Any]]:
        devices = self._ids.devices()
        readings = {
            device.id: self._ids.device_streams(device.id) for device in devices
        }
        entities = {
            device.id: set(self._ids.device_scope(device.id)) for device in devices
        }
        statuses = await self._statuses(set().union(*entities.values()))
        listed = []
        now = datetime.now(UTC)
        for device in devices:
            recorded = [
                statuses[entity] for entity in entities[device.id] if entity in statuses
            ]
            online = any(
                reading_is_receiving(self._runtime, stream.id, now)
                for stream in readings[device.id]
            )
            if active is not None and online != active:
                continue
            seen = [charger.last_seen for charger in recorded if charger.last_seen]
            listed.append(
                {
                    "id": device.id,
                    "label": device.label,
                    "kind": device.kind,
                    "broker_id": device.connection_id,
                    "parent_id": device.parent_id,
                    "reading_ids": [stream.id for stream in readings[device.id]],
                    "online": online,
                    "last_seen": max(seen) if seen else None,
                }
            )
        return listed

    def device_readings(self, device_id: str) -> list[SystemStream]:
        return self._ids.device_streams(device_id)

    async def measurements(self, stream_id: str, **page: Any):
        entity, key = self._ids.recorded(stream_id)
        return await self._telemetry.get_telemetry_data(
            charger_id=entity, telemetry_type=key, **page
        )

    async def measurement_buckets(self, stream_id: str, **window: Any):
        entity, key = self._ids.recorded(stream_id)
        return await self._telemetry.get_telemetry_range(
            charger_id=entity, telemetry_type=key, **window
        )

    async def evidence(self, stream_id: str, *, limit: int) -> list[dict[str, Any]]:
        rows = await self._evidence.list_by_scope(
            scope=self._ids.scope([stream_id]), limit=limit
        )
        return [self._full(row) for row in reversed(rows)]

    async def chart_evidence(
        self,
        *,
        device_id: str | None,
        stream_ids: list[str] | None,
        service_id: str | None,
        after_created: datetime | None,
        after_timestamp: datetime | None,
        after_service_id: str | None,
        after_sequence_number: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if device_id is not None and not stream_ids:
            scope = self._ids.device_scope(device_id)
        elif stream_ids and device_id is None:
            scope = self._ids.scope(stream_ids)
        else:
            raise ValidationError("Name either a device or readings")
        if not scope:
            return []
        rows = await self._evidence.list_chart(
            scope=scope,
            service_id=service_id,
            after_created=after_created,
            after_timestamp=after_timestamp,
            after_service_id=after_service_id,
            after_sequence_number=after_sequence_number,
            limit=limit,
        )
        return [self._chart(row) for row in rows]

    def _readings(self, entity: str, sensor_set, input_timestamps):
        reading_ids = self._ids.stream_ids(entity, sensor_set)
        timestamps = {
            stream_id: value
            for key, value in input_timestamps.items()
            for stream_id in self._ids.stream_ids(entity, [key])
        }
        return reading_ids, timestamps

    def _chart(self, row) -> dict[str, Any]:
        reading_ids, timestamps = self._readings(
            row.charger_id, row.sensor_set, row.input_timestamps
        )
        return {
            "monitor_id": row.service_id,
            "timestamp": row.timestamp,
            "sequence_number": row.sequence_number,
            "reading_ids": reading_ids,
            "input_timestamps": timestamps,
            "strategy": row.strategy or "static_baseline",
            "model_type": row.model_type,
            "anomaly_score": row.anomaly_score,
            "restarted_martingale": row.restarted_martingale,
            "tracker_results": row.tracker_results or [],
            "detector_results": row.detector_results or [],
            "detector_inputs": row.detector_inputs or [],
            "threshold": row.threshold,
            "alarm": row.alarm,
            "created": row.created or row.timestamp,
        }

    def _full(self, row) -> dict[str, Any]:
        reading_ids, timestamps = self._readings(
            row.charger_id, row.sensor_set, row.input_timestamps
        )
        return {
            "monitor_id": row.service_id,
            "timestamp": row.timestamp,
            "sequence_number": row.sequence_number,
            "device_id": self._ids.device_id(reading_ids),
            "reading_ids": reading_ids,
            "input_timestamps": timestamps,
            "strategy": row.strategy or "static_baseline",
            "model_type": row.model_type,
            "p_value": row.p_value,
            "anomaly_score": row.anomaly_score,
            "e_value": row.e_value,
            "e_value_is_infinite": row.e_value_is_infinite,
            "log_e_value": row.log_e_value,
            "restarted_martingale": row.restarted_martingale,
            "restarted_martingale_is_infinite": row.restarted_martingale_is_infinite,
            "log_restarted_martingale": row.log_restarted_martingale,
            "tracker_results": row.tracker_results or [],
            "detector_results": row.detector_results or [],
            "detector_inputs": row.detector_inputs or [],
            "threshold": row.threshold,
            "alarm": row.alarm,
        }
