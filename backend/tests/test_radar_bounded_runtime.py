"""Regressions for admission bounds and the serial model owner."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from off_key_core.schemas.radar import StaticBaselineConfig
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.detector_handle import DetectorHandle
from off_key_mqtt_radar.detector_runtime import DetectorRuntime
from off_key_mqtt_radar.mqtt_client import RadarMQTTClient


async def test_network_thread_burst_is_bounded_while_event_loop_cannot_run():
    client = RadarMQTTClient(MQTTRadarConfig(max_queue_size=8))
    loop = asyncio.get_running_loop()
    client._loop = loop
    client.client = object()
    getter = asyncio.create_task(client.message_queue.get())
    await asyncio.sleep(0)
    ready_before = len(loop._ready)
    message = SimpleNamespace(
        topic="telemetry/test/x", payload=b"1", qos=0, retain=False
    )

    def burst():
        for _ in range(20000):
            client._on_message(client.client, None, message)

    sender = threading.Thread(target=burst)
    sender.start()
    # Intentionally prevent loop callbacks from draining while Paho admits data.
    sender.join(timeout=10)
    assert not sender.is_alive()
    assert client.message_queue.qsize() == 8
    assert len(loop._ready) - ready_before <= 8
    coverage = client.coverage.snapshot()
    assert coverage.received_message_count == 20000
    assert coverage.dropped_by_reason["queue_full"] == 19992
    await getter
    await client._message_bridge.aclose()


async def test_oversized_payload_is_rejected_before_queue_or_loop_notification():
    client = RadarMQTTClient(MQTTRadarConfig(max_payload_bytes=16))
    client._loop = asyncio.get_running_loop()
    client._on_message(
        None,
        None,
        SimpleNamespace(
            topic="telemetry/test/x", payload=b"x" * 17, qos=0, retain=False
        ),
    )
    assert client.message_queue.qsize() == 0
    assert client.coverage.snapshot().dropped_by_reason == {"payload_too_large": 1}
    await client._message_bridge.aclose()


async def test_model_owner_serializes_real_detector_work_and_keeps_loop_responsive():
    detector = StaticConformalDetectionService(
        MQTTRadarConfig(
            monitoring=StaticBaselineConfig(
                model_params={"n_estimators": 8},
                training_window_size=20,
                calibration_window_size=8,
            )
        ),
    )
    wrapped = DetectorHandle(detector)
    runtime = DetectorRuntime(wrapped)
    threads = set()
    ticks = 0
    done = asyncio.Event()

    async def heartbeat():
        nonlocal ticks
        while not done.is_set():
            ticks += 1
            await asyncio.sleep(0.001)

    def process(index):
        threads.add(threading.get_ident())
        return wrapped.process({"x": float(index % 7)})

    ticker = asyncio.create_task(heartbeat())
    try:
        await asyncio.gather(*(runtime.call(process, index) for index in range(40)))
        assert detector.processed_count == 40
        assert len(threads) == 1
        assert threading.get_ident() not in threads
        assert ticks > 1
        assert (
            runtime.get_health_info()["primary_service_stats"]["processed_count"] == 40
        )
    finally:
        done.set()
        await ticker
        await runtime.stop()
        detector.shutdown()


async def test_cancelled_call_finishes_the_model_operation_before_reraising():
    """A thread cannot be interrupted, so cancellation waits for the mutation."""
    runtime = DetectorRuntime(
        SimpleNamespace(
            get_health_info=lambda: {"state": "healthy"}, primary_service=None
        )
    )
    started, release = threading.Event(), threading.Event()
    finished = []

    def mutate():
        started.set()
        release.wait(timeout=10)
        finished.append(True)

    call = asyncio.create_task(runtime.call(mutate))
    try:
        await asyncio.to_thread(started.wait, 10)
        call.cancel()
        await asyncio.sleep(0)
        assert not call.done()
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await call
        assert finished == [True]
    finally:
        release.set()
        await runtime.stop()


@pytest.mark.parametrize("failure_boundary", ["health", "copy"])
async def test_diagnostic_failure_preserves_inference_and_original_exception(
    monkeypatch, failure_boundary
):
    detector = StaticConformalDetectionService(MQTTRadarConfig())
    wrapped = DetectorHandle(detector)
    runtime = DetectorRuntime(wrapped)
    try:
        await runtime.refresh()
        original_health = wrapped.get_health_info

        class UncopyableDiagnostic:
            def __deepcopy__(self, _memo):
                raise RuntimeError("diagnostic refresh failed")

        def broken_health():
            if failure_boundary == "health":
                raise RuntimeError("diagnostic refresh failed")
            return original_health() | {"uncopyable": UncopyableDiagnostic()}

        monkeypatch.setattr(wrapped, "get_health_info", broken_health)
        result = await runtime.call(wrapped.process, {"x": 1.0})
        assert result.context["static_conformal"]["phase"] == "collecting"
        assert detector.processed_count == 1
        health = runtime.get_health_info()
        assert health["state"] == "degraded"
        assert (
            health["health_snapshot_error"] == "RuntimeError: diagnostic refresh failed"
        )
        assert health["health_snapshot_error_count"] == 1
        assert health["primary_service_stats"]["processed_count"] == 0

        original_error = ValueError("original operation failed")

        def failed_operation():
            raise original_error

        with pytest.raises(ValueError) as captured:
            await runtime.call(failed_operation)
        assert captured.value is original_error
        assert runtime.get_health_info()["health_snapshot_error_count"] == 2

        monkeypatch.setattr(wrapped, "get_health_info", original_health)
        await runtime.refresh()
        health = runtime.get_health_info()
        assert health["state"] == "healthy"
        assert health["health_snapshot_error"] is None
        assert health["health_snapshot_error_count"] == 2
        assert health["primary_service_stats"]["processed_count"] == 1
    finally:
        await runtime.stop()
        detector.shutdown()
