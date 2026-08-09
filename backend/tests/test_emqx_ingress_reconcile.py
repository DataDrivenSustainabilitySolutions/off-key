from dev.emqx.reconcile_ingress import (
    EmqxClient,
    ReconcileSettings,
    desired_resources,
)


def _settings(**overrides) -> ReconcileSettings:
    return ReconcileSettings(
        api_key="key",
        api_secret="secret",
        upstream_server="mqtt-tailscale-bridge:1883",
        **overrides,
    )


def test_desired_ingress_uses_device_filter_and_bridge_only_rule():
    connector, source, rule = desired_resources(_settings())

    assert connector.payload["server"] == "mqtt-tailscale-bridge:1883"
    assert source.payload["parameters"]["topic"] == "device/#"
    assert rule.payload["sql"] == ('SELECT * FROM "$bridges/mqtt:ambibox-wildcard"')
    assert "t/#" not in rule.payload["sql"]
    assert rule.payload["actions"] == [
        {
            "function": "republish",
            "args": {
                "topic": "${topic}",
                "payload": "${payload}",
                "qos": "${qos}",
                "retain": False,
                "direct_dispatch": True,
            },
        }
    ]
    assert connector.item_path == "connectors/mqtt%3Aambibox"
    assert source.item_path == "sources/mqtt%3Aambibox-wildcard"


def test_reconcile_creates_missing_resource(monkeypatch):
    client = EmqxClient(_settings())
    calls = []
    resource = desired_resources(client.settings)[0]
    get_count = 0

    def request(method, path, payload=None):
        nonlocal get_count
        calls.append((method, path, payload))
        if method == "GET":
            get_count += 1
            if get_count == 1:
                return 404, None
            return 200, {**resource.verification_payload, "status": "connected"}
        return 201, {}

    monkeypatch.setattr(client, "request", request)

    assert client.reconcile(resource) == "created"
    assert [call[0] for call in calls] == ["GET", "POST", "GET"]


def test_reconcile_updates_existing_resource_without_identity_fields(monkeypatch):
    client = EmqxClient(_settings())
    calls = []
    resource = desired_resources(client.settings)[1]
    get_count = 0

    def request(method, path, payload=None):
        nonlocal get_count
        calls.append((method, path, payload))
        if method == "GET":
            get_count += 1
            if get_count == 1:
                return 200, {"name": "stale"}
            return 200, {**resource.verification_payload, "status": "connected"}
        return 200, {}

    monkeypatch.setattr(client, "request", request)

    assert client.reconcile(resource) == "updated"
    put_call = next(call for call in calls if call[0] == "PUT")
    assert "type" not in put_call[2]
    assert "name" not in put_call[2]
    assert [call[0] for call in calls] == ["GET", "PUT", "GET"]


def test_reconcile_waits_for_connected_runtime_status(monkeypatch):
    client = EmqxClient(_settings(verification_poll_seconds=0.001))
    resource = desired_resources(client.settings)[1]
    responses = iter(
        [
            (200, {"name": "stale"}),
            (200, {}),
            (200, {**resource.verification_payload, "status": "connecting"}),
            (200, {**resource.verification_payload, "status": "connected"}),
        ]
    )
    monkeypatch.setattr(client, "request", lambda *_args, **_kwargs: next(responses))

    assert client.reconcile(resource) == "updated"


def test_check_only_fails_when_resource_is_missing(monkeypatch):
    client = EmqxClient(_settings(check_only=True))
    monkeypatch.setattr(client, "request", lambda *_args, **_kwargs: (404, None))

    try:
        client.reconcile(desired_resources(client.settings)[0])
    except RuntimeError as error:
        assert "Missing EMQX resource" in str(error)
    else:
        raise AssertionError("Expected a missing-resource failure")


def test_check_only_rejects_stale_source_topic(monkeypatch):
    client = EmqxClient(_settings(check_only=True))
    resource = desired_resources(client.settings)[1]
    stale = {
        **resource.verification_payload,
        "parameters": {"topic": "t/#", "qos": 1},
        "status": "connected",
    }
    monkeypatch.setattr(client, "request", lambda *_args, **_kwargs: (200, stale))

    try:
        client.reconcile(resource)
    except RuntimeError as error:
        assert "resource.parameters.topic" in str(error)
    else:
        raise AssertionError("Expected a stale-configuration failure")


def test_check_only_rejects_disconnected_source(monkeypatch):
    client = EmqxClient(_settings(check_only=True))
    resource = desired_resources(client.settings)[1]
    disconnected = {**resource.verification_payload, "status": "disconnected"}
    monkeypatch.setattr(
        client, "request", lambda *_args, **_kwargs: (200, disconnected)
    )

    try:
        client.reconcile(resource)
    except RuntimeError as error:
        assert "expected 'connected'" in str(error)
    else:
        raise AssertionError("Expected a disconnected-resource failure")


def test_check_only_rejects_extra_rule_action(monkeypatch):
    client = EmqxClient(_settings(check_only=True))
    resource = desired_resources(client.settings)[2]
    stale = {
        **resource.verification_payload,
        "actions": [
            *resource.verification_payload["actions"],
            {"function": "console", "args": {}},
        ],
    }
    monkeypatch.setattr(client, "request", lambda *_args, **_kwargs: (200, stale))

    try:
        client.reconcile(resource)
    except RuntimeError as error:
        assert "resource.actions has 2 entries; expected 1" in str(error)
    else:
        raise AssertionError("Expected an extra-action failure")
