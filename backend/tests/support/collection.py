"""Collection catalogue and message builders."""

from datetime import UTC, datetime

from off_key_core.db.catalogue_upgrade import convert_definition
from off_key_core.db.catalogue_v1 import adapt_ambibox_catalog
from off_key_core.db.catalogue_v1_models import (
    AmbiboxCatalog,
    CatalogCharger,
    CatalogSource,
    CollectionPolicy,
    SensorDefinition,
)
from off_key_mqtt_proxy.client.models import MQTTMessage


def catalog(mode="sample", kind="number"):
    return AmbiboxCatalog(
        sources=[
            CatalogSource(
                label="Broker",
                host="charger.ts.net",
                chargers=[
                    CatalogCharger(
                        label="Charger",
                        policy=CollectionPolicy(mode=mode, interval_seconds=10),
                        sensors=[
                            SensorDefinition(
                                key="temperature",
                                label="Temperature",
                                value_type=kind,
                                upstream_topic="device/evCharger/0/temperature",
                            )
                        ],
                    )
                ],
            )
        ]
    )


def runtime_catalog(mode="sample", kind="number"):
    legacy = catalog(mode, kind)
    result = convert_definition(adapt_ambibox_catalog(legacy), legacy)
    result.generation = "test"
    return result


def message(configuration, value, *, retained=False, upstream_retained=False):
    now = datetime.now(UTC)
    return MQTTMessage(
        configuration.streams()[0].ingress_topic,
        {
            "payload": value
            if isinstance(value, str)
            else __import__("json").dumps(value),
            "received_at": int(now.timestamp() * 1000),
            "upstream_retained": upstream_retained,
        },
        now,
        0,
        retained,
    )
