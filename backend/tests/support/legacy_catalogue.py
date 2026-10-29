"""Catalogues in the retired v1 format that migration 005 converts.

The v1 models are frozen with migration 005, so the provider-specific names
they carry stay; only historical-upgrade tests use this module.
"""

from off_key_core.db.catalogue_v1_models import (
    AmbiboxCatalog,
    CatalogCharger,
    CatalogSource,
    CollectionPolicy,
    SensorDefinition,
)

LegacyCatalog = AmbiboxCatalog


def legacy_catalog(mode="sample", kind="number"):
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
