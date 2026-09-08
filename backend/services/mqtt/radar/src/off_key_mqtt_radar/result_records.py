"""Project detector results into database records without database I/O."""

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_core.utils.timestamps import parse_utc_timestamp

from .config.runtime import get_radar_checkpoint_settings
from .models import AnomalyResult

logger = logging.getLogger(__name__)
MULTIVARIATE_TELEMETRY_TYPE = "__multivariate__"


def _optional_finite_float(value: Any) -> float | None:
    """Return a JSON/database-safe finite float or ``None``."""
    if not isinstance(value, int | float):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def _nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return max(value, 0)


def _optional_nonnegative_int(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _normalize_tracker_results(value: Any) -> list[dict[str, Any]]:
    """Return a bounded, JSON-safe projection of runtime tracker evidence."""
    if not isinstance(value, list):
        return []

    normalized_results: list[dict[str, Any]] = []
    for candidate in value[:16]:
        if not isinstance(candidate, dict):
            continue
        tracker_id = candidate.get("tracker_id")
        betting_function = candidate.get("betting_function")
        alarm_statistic = candidate.get("alarm_statistic")
        threshold = _optional_finite_float(candidate.get("threshold"))
        if (
            not all(
                isinstance(item, str)
                for item in (tracker_id, betting_function, alarm_statistic)
            )
            or threshold is None
        ):
            continue

        raw_statistics = candidate.get("statistics")
        statistics: dict[str, dict[str, Any]] = {}
        if isinstance(raw_statistics, dict):
            for name in (
                "martingale",
                "restarted_martingale",
                "cusum",
                "shiryaev_roberts",
            ):
                statistic = raw_statistics.get(name)
                if not isinstance(statistic, dict):
                    continue
                statistics[name] = {
                    "value": _optional_finite_float(statistic.get("value")),
                    "is_infinite": bool(statistic.get("is_infinite", False)),
                    "log_value": _optional_finite_float(statistic.get("log_value")),
                }

        parameters = candidate.get("betting_parameters")
        normalized_results.append(
            {
                "tracker_id": tracker_id,
                "betting_function": betting_function,
                "betting_parameters": parameters
                if isinstance(parameters, dict)
                else {},
                "alarm_statistic": alarm_statistic,
                "statistic_value": _optional_finite_float(
                    candidate.get("statistic_value")
                ),
                "statistic_is_infinite": bool(
                    candidate.get("statistic_is_infinite", False)
                ),
                "log_statistic_value": _optional_finite_float(
                    candidate.get("log_statistic_value")
                ),
                "statistics": statistics,
                "e_value": _optional_finite_float(candidate.get("e_value")),
                "e_value_is_infinite": bool(
                    candidate.get("e_value_is_infinite", False)
                ),
                "log_e_value": _optional_finite_float(candidate.get("log_e_value")),
                "threshold": threshold,
                "threshold_horizon": _optional_nonnegative_int(
                    candidate.get("threshold_horizon")
                ),
                "threshold_window_position": _optional_nonnegative_int(
                    candidate.get("threshold_window_position")
                ),
                "threshold_window_reset": bool(
                    candidate.get("threshold_window_reset", False)
                ),
                "alarm_fired": bool(candidate.get("alarm_fired", False)),
                "alarm_active": bool(candidate.get("alarm_active", False)),
                "alarm_count": _nonnegative_int(candidate.get("alarm_count")),
                "tested_count": _nonnegative_int(candidate.get("tested_count")),
            }
        )
    return normalized_results


@dataclass(frozen=True)
class PreparedResult:
    result: AnomalyResult
    anomalies: list[dict[str, Any]]
    identities: list[dict[str, Any]]
    evidence: list[dict[str, Any]]


class ResultProjector:
    def __init__(self):
        self.topic_extractor = TopicMetadataExtractor()

    def prepare(self, result: AnomalyResult) -> PreparedResult:
        anomalies, identities = self._build_records(
            [result] if result.is_anomaly else []
        )
        evidence = self._build_evidence_records([result])
        if (
            self._is_static_ready_result(result)
            or self._is_adaptive_operational_result(result)
        ) and not evidence:
            raise ValueError("Operational result is missing valid evidence references")
        return PreparedResult(result, anomalies, identities, evidence)

    def _extract_telemetry_type(
        self, topic: str, payload: dict[str, Any] | None = None
    ) -> str:
        """Extract telemetry type from MQTT topic."""
        metadata = self.topic_extractor.extract(topic=topic, payload=payload)
        return metadata.telemetry_type if metadata else "unknown"

    def _derive_telemetry_type(self, result: AnomalyResult) -> str:
        """Resolve canonical telemetry type for anomaly persistence."""
        alignment_context = (result.context or {}).get("alignment", {})
        if bool(alignment_context.get("aligned_vector")):
            return MULTIVARIATE_TELEMETRY_TYPE
        return self._extract_telemetry_type(result.topic, result.raw_data)

    @staticmethod
    def _is_static_conformal_result(result: AnomalyResult) -> bool:
        return isinstance((result.context or {}).get("static_conformal"), dict)

    @staticmethod
    def _is_static_ready_result(result: AnomalyResult) -> bool:
        static_context = (result.context or {}).get("static_conformal")
        return (
            isinstance(static_context, dict) and static_context.get("phase") == "ready"
        )

    @staticmethod
    def _is_adaptive_operational_result(result: AnomalyResult) -> bool:
        adaptive_context = (result.context or {}).get("adaptive_stream")
        return (
            isinstance(adaptive_context, dict)
            and adaptive_context.get("phase") == "operational"
        )

    @staticmethod
    def _derive_anomaly_type(result: AnomalyResult) -> str:
        """Map detector output to stored anomaly semantics."""
        alignment_context = (result.context or {}).get("alignment", {})
        if ResultProjector._is_static_conformal_result(result):
            if bool(alignment_context.get("aligned_vector")):
                return "ml_conformal_static_multivariate"
            return "ml_conformal_static_univariate"
        if isinstance((result.context or {}).get("adaptive_stream"), dict):
            if bool(alignment_context.get("aligned_vector")):
                return "ml_adaptive_stream_multivariate"
            return "ml_adaptive_stream_univariate"
        if bool(alignment_context.get("aligned_vector")):
            return "ml_tailprob_multivariate"
        return "ml_tailprob_univariate"

    @staticmethod
    def _derive_anomaly_value(result: AnomalyResult) -> float:
        """Persist the p-value used by the active detector when available."""
        static_context = (result.context or {}).get("static_conformal", {})
        conformal_pvalue = static_context.get("p_value")
        if isinstance(conformal_pvalue, int | float):
            conformal_pvalue = float(conformal_pvalue)
            if math.isfinite(conformal_pvalue):
                return conformal_pvalue

        score_window = (result.context or {}).get("score_window", {})
        tail_pvalue = score_window.get("tail_pvalue")
        if isinstance(tail_pvalue, int | float):
            tail_pvalue = float(tail_pvalue)
            if math.isfinite(tail_pvalue):
                return tail_pvalue
        return float(result.anomaly_score)

    @staticmethod
    def _normalize_sensor_set(value: Any) -> list[str] | None:
        if isinstance(value, dict):
            iterable = value.keys()
        elif isinstance(value, set):
            iterable = sorted(value)
        elif isinstance(value, Iterable) and not isinstance(value, str | bytes):
            iterable = value
        else:
            return None

        sensors = []
        seen = set()
        for item in iterable:
            sensor = str(item).strip() if item is not None else ""
            if sensor and sensor not in seen:
                sensors.append(sensor)
                seen.add(sensor)
        return sensors or None

    def _derive_sensor_set(self, result: AnomalyResult) -> list[str] | None:
        """Resolve the exact telemetry streams involved in a stored anomaly."""
        alignment_context = (result.context or {}).get("alignment", {})
        required_sensors = self._normalize_sensor_set(
            alignment_context.get("required_sensors")
        )
        if required_sensors and (
            bool(alignment_context.get("aligned_vector")) or len(required_sensors) == 1
        ):
            return required_sensors

        feature_source = result.raw_data if isinstance(result.raw_data, dict) else {}
        feature_sensors = self._normalize_sensor_set(feature_source.keys())
        if bool(alignment_context.get("aligned_vector")) and feature_sensors:
            return feature_sensors

        telemetry_type = self._extract_telemetry_type(result.topic, result.raw_data)
        if telemetry_type and telemetry_type != "unknown":
            return [telemetry_type]

        return feature_sensors

    @staticmethod
    def _derive_input_timestamps(
        result: AnomalyResult,
        sensor_set: list[str],
    ) -> dict[str, str] | None:
        """Normalize exact telemetry references for one inference result."""
        alignment_context = (result.context or {}).get("alignment", {})
        raw_timestamps = alignment_context.get("input_timestamps")
        if not isinstance(raw_timestamps, dict) or not raw_timestamps:
            return None

        normalized: dict[str, str] = {}
        for sensor in sensor_set:
            value = raw_timestamps.get(sensor)
            try:
                timestamp = parse_utc_timestamp(value)
            except (TypeError, ValueError, OSError, OverflowError):
                logger.error(
                    "event=radar.evidence_input_timestamp_invalid "
                    "sensor=%s service_result_timestamp=%s",
                    sensor,
                    result.timestamp,
                )
                return None
            normalized[sensor] = timestamp.isoformat()

        return normalized if len(normalized) == len(sensor_set) else None

    def _build_records(
        self,
        results: list[AnomalyResult],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        anomaly_records = [
            {
                "charger_id": result.charger_id or "unknown",
                "timestamp": result.timestamp,
                "telemetry_type": self._derive_telemetry_type(result),
                "anomaly_type": self._derive_anomaly_type(result),
                "anomaly_value": self._derive_anomaly_value(result),
                "value_type": (
                    "conformal_pvalue"
                    if self._is_static_conformal_result(result)
                    else (
                        "anomaly_score"
                        if isinstance(
                            (result.context or {}).get("adaptive_stream"), dict
                        )
                        else "tail_pvalue"
                    )
                ),
                "sensor_set": self._derive_sensor_set(result),
            }
            for result in results
        ]
        identity_records = [
            {
                "charger_id": record["charger_id"],
                "timestamp": record["timestamp"],
                "telemetry_type": record["telemetry_type"],
            }
            for record in anomaly_records
        ]
        return anomaly_records, identity_records

    def _build_evidence_records(
        self, results: list[AnomalyResult]
    ) -> list[dict[str, Any]]:
        service_id = get_radar_checkpoint_settings().SERVICE_ID
        if not service_id:
            return []

        records = []
        for result in results:
            is_static = self._is_static_ready_result(result)
            is_adaptive = self._is_adaptive_operational_result(result)
            if not is_static and not is_adaptive:
                continue
            context_key = "static_conformal" if is_static else "adaptive_stream"
            context = (result.context or {}).get(context_key, {})
            p_value = context.get("p_value")
            sequence_number = context.get(
                "tested_count", context.get("sequence_number")
            )
            threshold = context.get("restarted_ville_threshold")
            tracker_results = _normalize_tracker_results(context.get("tracker_results"))
            threshold = context.get("threshold", threshold)
            anomaly_score = context.get("anomaly_score", result.anomaly_score)
            if is_static and (
                not isinstance(p_value, int | float) or not math.isfinite(p_value)
            ):
                continue
            if is_adaptive and (
                not isinstance(anomaly_score, int | float)
                or not math.isfinite(anomaly_score)
            ):
                continue
            if not isinstance(sequence_number, int) or sequence_number < 1:
                continue
            if not isinstance(threshold, int | float) or not math.isfinite(threshold):
                continue

            sensor_set = self._derive_sensor_set(result) or []
            input_timestamps = self._derive_input_timestamps(result, sensor_set)
            if input_timestamps is None:
                logger.error(
                    "event=radar.evidence_input_timestamps_missing "
                    "service_id=%s sensor_set=%s result_timestamp=%s",
                    service_id,
                    sensor_set,
                    result.timestamp,
                )
                continue
            canonical_timestamp = max(
                parse_utc_timestamp(value) for value in input_timestamps.values()
            )

            records.append(
                {
                    "service_id": service_id,
                    "timestamp": canonical_timestamp,
                    "sequence_number": sequence_number,
                    "charger_id": result.charger_id or "unknown",
                    "sensor_set": sensor_set,
                    "input_timestamps": input_timestamps,
                    "strategy": ("static_baseline" if is_static else "adaptive_stream"),
                    "model_type": (
                        (result.context or {}).get("model_type")
                        or result.model_info.get("model_type")
                    ),
                    "p_value": float(p_value) if is_static else None,
                    "anomaly_score": (float(anomaly_score) if is_adaptive else None),
                    "e_value": _optional_finite_float(context.get("e_value")),
                    "e_value_is_infinite": bool(
                        context.get("e_value_is_infinite", False)
                    ),
                    "log_e_value": _optional_finite_float(context.get("log_e_value")),
                    "restarted_martingale": _optional_finite_float(
                        context.get("restarted_martingale")
                    ),
                    "restarted_martingale_is_infinite": bool(
                        context.get("restarted_martingale_is_infinite", False)
                    ),
                    "log_restarted_martingale": _optional_finite_float(
                        context.get("log_restarted_martingale")
                    ),
                    "tracker_results": tracker_results,
                    "threshold": float(threshold),
                    "alarm": bool(context.get("alarm_fired", False)),
                }
            )
        return records
