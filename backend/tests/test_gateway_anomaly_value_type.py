"""Tests for gateway anomaly value_type forwarding semantics."""

from datetime import datetime, timezone
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from off_key_api_gateway.api.v1.anomalies import AnomalyCreatePayload, create_anomaly


@pytest.mark.asyncio
async def test_create_anomaly_forwards_explicit_value_type():
    payload = AnomalyCreatePayload(
        charger_id="charger-1",
        timestamp=datetime.now(timezone.utc),
        telemetry_type="voltage",
        anomaly_type="ml_tailprob_univariate",
        anomaly_value=0.0011,
        value_type="tail_pvalue",
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
    assert forwarded["value_type"] == "tail_pvalue"


@pytest.mark.asyncio
async def test_create_anomaly_forwards_none_when_value_type_omitted():
    payload = AnomalyCreatePayload(
        charger_id="charger-2",
        timestamp=datetime.now(timezone.utc),
        telemetry_type="temperature",
        anomaly_type="ml_tailprob_multivariate",
        anomaly_value=0.0045,
    )
    mock_create = AsyncMock(
        return_value={"message": "Anomaly created", "anomaly_id": "a-2"}
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
        await handler(payload=payload)

    forwarded = mock_create.await_args.args[0]
    assert "value_type" in forwarded
    assert forwarded["value_type"] is None


@pytest.mark.asyncio
async def test_create_anomaly_query_params_forward_value_type():
    timestamp = datetime.now(timezone.utc)
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
        )

    forwarded = mock_create.await_args.args[0]
    assert forwarded["value_type"] == "zscore"
