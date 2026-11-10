"""Pretrained forecasters behind the forecast service, as Aberrant forecasters."""

import math
import pickle

import numpy as np
import pytest
from aberrant.base.protocols import ForecasterProtocol
from aberrant.forecast import ResidualDetector
from fastapi.testclient import TestClient
from off_key_core.schemas.forecast import QUANTILE_LEVELS
from off_key_forecast.api import create_app
from off_key_forecast.providers import naive_providers
from off_key_forecast.registry import ModelRegistry
from off_key_mqtt_radar.execution_errors import FatalExecutionError, ObservationRejected
from off_key_mqtt_radar.forecasting import (
    ForecastClient,
    ForecastServiceError,
    ServiceForecaster,
    ServiceResidualDetector,
    forecast_from_quantiles,
)
from pydantic import SecretStr

MODEL = "naive/season-4"
TOKEN = "service-token"


@pytest.fixture
def service(tmp_path):
    """The real forecast service in process, with the seasonal-naive baseline."""
    registry = ModelRegistry(naive_providers([4]), tmp_path)
    http = TestClient(create_app(registry, SecretStr(TOKEN)))
    calls = []

    def transport(method, url, body, headers):
        calls.append((method, url))
        response = http.request(method, url, content=body, headers=headers)
        return response.status_code, response.content

    yield (
        lambda token=TOKEN: ForecastClient(
            "http://forecast", token=token, transport=transport
        ),
        calls,
    )
    registry.close()


def _cycle(index: int) -> float:
    return 100.0 + [0.0, 10.0, 0.0, -10.0][index % 4]


def test_client_lists_models_and_forecasts_on_the_shared_grid(service):
    client = service[0]()

    model = client.model(MODEL)
    assert model is not None and model.status == "ready"
    assert client.model("timestral/unknown") is None
    assert client.request_download(MODEL).status == "ready"
    response = client.forecast(MODEL, [[_cycle(i) for i in range(16)]], 4)

    assert response.levels == QUANTILE_LEVELS
    assert np.asarray(response.quantiles).shape == (1, 4, len(QUANTILE_LEVELS))


def test_client_says_why_the_service_refused(service):
    with pytest.raises(ForecastServiceError, match="Invalid service token") as error:
        service[0](token="wrong").models()
    assert error.value.status == 401
    with pytest.raises(ForecastServiceError, match="Unknown model"):
        service[0]().forecast("timestral/unknown", [[1.0, 2.0]], 1)
    with pytest.raises(ValueError, match="not configured"):
        ForecastClient("")


def test_quantiles_become_a_forecast_with_a_median_and_a_spread():
    levels = (0.05, 0.25, 0.5, 0.75, 0.95)
    forecast = forecast_from_quantiles(
        7, levels, [[1.0, 2.0, 3.0, 4.0, 5.0], [3.0, 3.0, 3.0, 3.0, 3.0]], 1e-3
    )

    assert (forecast.origin, forecast.leads) == (7, (1, 2))
    assert forecast.mean == (3.0, 3.0)
    assert forecast.scale == (pytest.approx(2.0 / 1.349), 1e-3)
    assert forecast.quantile(1, 0.95) == 5.0


def test_service_forecaster_is_an_aberrant_forecaster(service):
    forecaster = ServiceForecaster(
        MODEL, horizon=3, context_length=16, minimum_context=8, client=service[0]
    )
    assert isinstance(forecaster, ForecasterProtocol)

    for index in range(7):
        forecaster.learn_one(_cycle(index))
    assert not forecaster.is_ready and forecaster.forecast_one() is None
    # The first value asks the service to have the model ready, and no more.
    assert service[1] == [("POST", "http://forecast/v1/downloads")]

    forecaster.learn_one(_cycle(7))
    forecast = forecaster.forecast_one()

    assert forecast is not None
    assert (forecast.origin, forecast.leads) == (8, (1, 2, 3))
    assert forecast.mean == pytest.approx((_cycle(8), _cycle(9), _cycle(10)))
    assert all(scale > 0 for scale in forecast.scale)
    assert forecast.levels == QUANTILE_LEVELS

    for index in range(8, 40):
        forecaster.learn_one(_cycle(index))
    # The model reads 16 values; two more let a missed forecast be made late.
    assert len(forecaster.context()) == 16
    assert forecaster.context(back=2) == [_cycle(index) for index in range(22, 38)]
    late = forecaster.forecast_from(back=2)
    assert late is not None and late.origin == 38
    assert late.mean == pytest.approx((_cycle(38), _cycle(39), _cycle(40)))
    with pytest.raises(ValueError, match="back"):
        forecaster.forecast_from(back=3)


def test_residual_detector_scores_a_break_in_the_cycle(service):
    detector = ResidualDetector(
        ServiceForecaster(
            MODEL, horizon=2, context_length=32, minimum_context=8, client=service[0]
        ),
        "x",
        lead=2,
    )
    scores = []
    for index in range(40):
        scores.append(detector.score_one({"x": _cycle(index)}))
        detector.learn_one({"x": _cycle(index)})
    spike = detector.score_one({"x": 110.0})

    # Nothing is compared before 8 values and the lead have passed.
    assert scores[:9] == [0.0] * 9
    assert max(scores[12:]) < 0.5
    assert spike > 10 * max(scores[12:]) + 1


_CLIENTS = {}


def _shared_client():
    """A module-level factory, as a checkpoint stores it by reference."""
    return _CLIENTS["service"]()


def test_checkpoint_keeps_the_values_and_reconnects(service, monkeypatch):
    monkeypatch.setitem(_CLIENTS, "service", service[0])
    forecaster = ServiceForecaster(
        MODEL, horizon=1, context_length=16, minimum_context=8, client=_shared_client
    )
    for index in range(12):
        forecaster.learn_one(_cycle(index))
    expected = forecaster.forecast_one()
    assert forecaster._client is not None

    restored = pickle.loads(pickle.dumps(forecaster))

    assert restored._client is None
    assert restored.context() == forecaster.context()
    assert restored.forecast_one() == expected


def test_worker_reads_the_service_address_from_its_environment(monkeypatch):
    from off_key_mqtt_radar.forecasting import service_client

    monkeypatch.delenv("FORECAST_API_URL", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        service_client()
    monkeypatch.setenv("FORECAST_API_URL", "http://forecast:8020/")
    monkeypatch.setenv("FORECAST_API_TOKEN", TOKEN)
    client = service_client()
    assert client.base_url == "http://forecast:8020"
    assert client._headers["Authorization"] == f"Bearer {TOKEN}"


def test_an_outage_gives_no_forecast_and_forecasts_resume(service):
    available = [False]

    def client():
        if not available[0]:
            raise ForecastServiceError("Forecast service is unreachable: refused")
        return service[0]()

    forecaster = ServiceForecaster(
        MODEL, horizon=1, context_length=16, minimum_context=4, client=client
    )
    for index in range(8):
        forecaster.learn_one(_cycle(index))

    assert forecaster.forecast_one() is None
    assert forecaster.forecast_one() is None
    # The first value could not ask for the model either.
    assert forecaster.failures == 3
    assert "unreachable" in forecaster.last_error

    available[0] = True
    forecast = forecaster.forecast_one()
    assert forecast is not None and math.isfinite(forecast.mean[0])
    assert forecaster.last_error is None


_OUTAGE = {"down": False}


def _flaky_client():
    if _OUTAGE["down"]:
        raise ForecastServiceError("Forecast service is unreachable: refused")
    return _CLIENTS["service"]()


@pytest.mark.parametrize("lead", [1, 3])
def test_detector_rejects_what_it_cannot_compare_and_recovers(
    service, monkeypatch, lead
):
    monkeypatch.setitem(_CLIENTS, "service", service[0])
    monkeypatch.setitem(_OUTAGE, "down", False)

    def detector():
        return ServiceResidualDetector(
            ServiceForecaster(
                MODEL,
                horizon=lead,
                context_length=16,
                minimum_context=8,
                client=_flaky_client,
            ),
            "x",
            lead=lead,
        )

    steady, flaky = detector(), detector()
    for index in range(20):
        steady.learn_one({"x": _cycle(index)})
        flaky.learn_one({"x": _cycle(index)})

    # The service is away while the forecasts for the next values are due.
    monkeypatch.setitem(_OUTAGE, "down", True)
    flaky.model._client = None
    for index in range(20, 24):
        steady.learn_one({"x": _cycle(index)})
        flaky.learn_one({"x": _cycle(index)})
    assert flaky.model.failures == 4
    with pytest.raises(ObservationRejected, match="No forecast to compare with"):
        flaky.score_one({"x": 110.0})

    # Back again, the missed forecast is made from the same values as it
    # would have been, so the score is the one an undisturbed detector gives.
    monkeypatch.setitem(_OUTAGE, "down", False)
    assert flaky.score_one({"x": 110.0}) == steady.score_one({"x": 110.0})
    assert flaky.score_one({"x": 110.0}) > 5


def test_detector_scores_zero_before_the_forecaster_is_ready(service):
    detector = ServiceResidualDetector(
        ServiceForecaster(
            MODEL, horizon=2, context_length=16, minimum_context=8, client=service[0]
        ),
        "x",
        lead=2,
    )
    for index in range(9):
        assert detector.score_one({"x": _cycle(index)}) == 0.0
        detector.learn_one({"x": _cycle(index)})
    assert service[1] == [
        ("POST", "http://forecast/v1/downloads"),
        *[("POST", "http://forecast/v1/forecast")] * 2,
    ]
    with pytest.raises(TypeError, match="forecast service"):
        ServiceResidualDetector(object(), "x")


class _Clock:
    """The forecaster's monotonic clock, moved by hand."""

    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(
            "off_key_mqtt_radar.forecasting.time.monotonic", lambda: self.now
        )


def test_first_value_asks_for_the_model_and_asks_again_after_an_outage(
    service, monkeypatch
):
    clock = _Clock(monkeypatch)
    available = [False]

    def client():
        if not available[0]:
            raise ForecastServiceError("Forecast service is unreachable: refused")
        return service[0]()

    forecaster = ServiceForecaster(
        MODEL, horizon=1, context_length=16, minimum_context=8, client=client
    )
    forecaster.learn_one(_cycle(0))
    available[0] = True
    forecaster.learn_one(_cycle(1))
    assert service[1] == []

    # Half a minute later the service is asked again, and then not any more.
    clock.now += 30.0
    forecaster.learn_one(_cycle(2))
    clock.now += 3600.0
    forecaster.learn_one(_cycle(3))
    assert service[1] == [("POST", "http://forecast/v1/downloads")]
    assert forecaster.prepare().status == "ready"

    # A restored worker asks once more: its service may be another one.
    assert forecaster.__getstate__()["_prepare_at"] == 0.0


def test_a_model_the_service_does_not_offer_ends_the_run(service):
    forecaster = ServiceForecaster("timestral/unknown", client=service[0])

    with pytest.raises(FatalExecutionError, match="does not offer timestral/unknown"):
        forecaster.learn_one(1.0)
    with pytest.raises(FatalExecutionError, match="Unknown model"):
        forecaster.prepare()


def test_a_service_that_hangs_is_left_alone_for_a_while(service, monkeypatch):
    clock = _Clock(monkeypatch)
    hanging = [False]
    asked = []

    def transport(method, url, body, headers):
        asked.append(url)
        if hanging[0]:
            clock.now += 10.0
            raise ForecastServiceError("Forecast service is unreachable: timed out")
        return service[0]()._send(method, url, body, headers)

    forecaster = ServiceForecaster(
        MODEL,
        horizon=1,
        context_length=16,
        minimum_context=4,
        client=lambda: ForecastClient(
            "http://forecast", token=TOKEN, transport=transport
        ),
    )
    for index in range(8):
        forecaster.learn_one(_cycle(index))
    hanging[0] = True
    del asked[:]

    # One request waits out the timeout; the next values do not wait again.
    for _ in range(5):
        assert forecaster.forecast_one() is None
    assert len(asked) == 1 and forecaster.failures == 5
    assert "timed out" in forecaster.last_error

    hanging[0] = False
    clock.now += 15.0
    assert forecaster.forecast_one() is not None
    assert forecaster.last_error is None


@pytest.mark.parametrize(
    "params",
    [
        {"horizon": 0},
        {"horizon": 2000},
        {"context_length": 0},
        {"context_length": 40_000},
        {"minimum_context": 0},
        {"context_length": 8, "minimum_context": 9},
        {"min_scale": 0},
    ],
)
def test_service_forecaster_rejects_settings_out_of_range(params):
    with pytest.raises(ValueError):
        ServiceForecaster(MODEL, client=lambda: None, **params)
    with pytest.raises(ValueError):
        ServiceForecaster("", client=lambda: None)


def test_preflight_of_a_timestral_design_names_the_service_without_calling_it(
    monkeypatch,
):
    from off_key_core.schemas.radar import AdaptiveStreamConfig
    from off_key_mqtt_radar.preflight import DetectorConfigurationError, preflight

    from tests.support.form_pipeline import form_radar_config

    monitoring = AdaptiveStreamConfig(
        model_type="forecast.timestral",
        model_params={"context_length": 32, "minimum_context": 16, "lead": 2},
        training_window_size=20,
        calibration_window_size=4,
    )
    execution = form_radar_config(monitoring, ["telemetry/c1/x0"]).pipeline

    # Nothing listens at this address: the target image checks the settings,
    # and the service is asked when values arrive.
    monkeypatch.setenv("FORECAST_API_URL", "http://127.0.0.1:9")
    report = preflight(execution)
    assert report["ok"]
    assert report["capabilities"]["warmup"] == {"minimum": 17, "unit": "events"}

    # A deployment without the service says so on the step, before a run starts.
    monkeypatch.delenv("FORECAST_API_URL")
    with pytest.raises(
        DetectorConfigurationError, match="no forecast service"
    ) as error:
        preflight(execution)
    assert error.value.node_id == "detector"
    assert [issue.code for issue in error.value.error.issues] == ["forecast_service"]
