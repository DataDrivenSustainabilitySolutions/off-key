"""Every MQTT_* proxy setting reaches its runtime config field."""

from off_key_mqtt_proxy.config.config import MQTTConfig, MQTTSettings

OVERRIDES = {
    "MQTT_TELEMETRY_ENABLED": False,
    "MQTT_BROKER_HOST": "broker.example",
    "MQTT_BROKER_PORT": 8883,
    "MQTT_USE_TLS": True,
    "MQTT_CA_FILE": "/run/secrets/ca.pem",
    "MQTT_TRANSPORT": "websockets",
    "MQTT_CONNECTION_TIMEOUT": 40.0,
    "MQTT_CLIENT_ID_PREFIX": "snapshot",
    "MQTT_USE_AUTH": True,
    "MQTT_USERNAME": "proxy",
    "MQTT_APIKEY": "snapshot-key-0123",
    "MQTT_TOPIC_REGEX": r"^(?P<charger_id>[^/]+)/(?P<telemetry_type>.+)$",
    "MQTT_BATCH_SIZE": 7,
    "MQTT_BATCH_TIMEOUT": 1.5,
    "MQTT_MAX_MESSAGE_QUEUE_SIZE": 500,
    "MQTT_RETRY_BASE_DELAY": 0.2,
    "MQTT_RETRY_MAX_DELAY": 6.0,
    "MQTT_RETRY_EXPONENTIAL_BASE": 3.0,
    "MQTT_RETRY_JITTER_ENABLED": False,
    "MQTT_RETRY_JITTER_MAGNITUDE": 0.1,
    "MQTT_HEALTH_MONITOR_INTERVAL": 10.0,
    "MQTT_GRACEFUL_SHUTDOWN_TIMEOUT": 12.0,
}


def test_settings_snapshot_maps_every_config_field():
    config = MQTTSettings(**OVERRIDES).config
    assert config.model_dump() == {
        "enabled": False,
        "broker_host": "broker.example",
        "broker_port": 8883,
        "use_tls": True,
        "ca_file": "/run/secrets/ca.pem",
        "transport": "websockets",
        "connection_timeout": 40.0,
        "client_id_prefix": "snapshot",
        "use_auth": True,
        "mqtt_username": "proxy",
        "mqtt_api_key": "snapshot-key-0123",
        "topic_regex": OVERRIDES["MQTT_TOPIC_REGEX"],
        "batch_size": 7,
        "batch_timeout": 1.5,
        "max_message_queue_size": 500,
        "retry_base_delay": 0.2,
        "retry_max_delay": 6.0,
        "retry_exponential_base": 3.0,
        "retry_jitter_enabled": False,
        "retry_jitter_magnitude": 0.1,
        "health_monitor_interval": 10.0,
        "graceful_shutdown_timeout": 12.0,
    }
    assert set(config.model_dump()) == set(MQTTConfig.model_fields)
