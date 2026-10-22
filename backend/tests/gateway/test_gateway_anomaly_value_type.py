"""Tests for gateway anomaly value_type forwarding semantics."""

import inspect
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from off_key_api_gateway.api.v1.anomalies import AnomalyCreatePayload, create_anomaly


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("optional", "forwarded_value_type", "forwarded_sensor_set"),
    [
        (
            {"value_type": "tail_pvalue", "sensor_set": ["voltage"]},
            "tail_pvalue",
            ["voltage"],
        ),
        ({}, None, None),
    ],
)
async def test_create_anomaly_forwards_value_type_and_sensor_set_even_when_omitted(
    optional, forwarded_value_type, forwarded_sensor_set
):
    payload = AnomalyCreatePayload(
        charger_id="charger-1",
        timestamp=datetime.now(UTC),
        telemetry_type="voltage",
        anomaly_type="ml_tailprob_univariate",
        anomaly_value=0.0011,
        **optional,
    )
    mock_create = AsyncMock(
        return_value={"message": "Anomaly created", "anomaly_id": "a-1"}
    )

    with (
        patch(
            "off_key_api_gateway.api.v1.anomalies.tactic.create_anomaly", mock_create
        ),
        patch(
            "off_key_api_gateway.api.v1.anomalies.send_anomaly_alert_email",
            AsyncMock(return_value=None),
        ),
    ):
        handler = inspect.unwrap(create_anomaly)
        response = await handler(payload=payload)

    assert response["anomaly_id"] == "a-1"
    forwarded = mock_create.await_args.args[0]
    assert forwarded["value_type"] == forwarded_value_type
    assert forwarded["sensor_set"] == forwarded_sensor_set


@pytest.mark.asyncio
async def test_create_anomaly_query_params_forward_value_type():
    timestamp = datetime.now(UTC)
    mock_create = AsyncMock(
        return_value={"message": "Anomaly created", "anomaly_id": "a-3"}
    )

    with (
        patch(
            "off_key_api_gateway.api.v1.anomalies.tactic.create_anomaly", mock_create
        ),
        patch(
            "off_key_api_gateway.api.v1.anomalies.send_anomaly_alert_email",
            AsyncMock(return_value=None),
        ),
    ):
        handler = inspect.unwrap(create_anomaly)
        await handler(
            payload=None,
            charger_id="charger-3",
            timestamp=timestamp,
            telemetry_type="current",
            anomaly_type="ml_detected",
            anomaly_value=3.14,
            value_type="zscore",
            sensor_set=["current"],
        )

    forwarded = mock_create.await_args.args[0]
    assert forwarded["value_type"] == "zscore"
    assert forwarded["sensor_set"] == ["current"]
