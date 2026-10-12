"""A clean runtime break must preserve saved user and monitor configuration."""

from datetime import UTC, datetime

from off_key_core.db.catalogue_upgrade import upgrade_topics
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import (
    Charger,
    CollectionConfiguration,
    Favorite,
    MonitoringService,
    Telemetry,
    User,
)
from off_key_core.db.system import SystemCollectionConfiguration, SystemConfiguration
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from sqlalchemy import insert, select, text

from .test_collection import catalog, runtime_catalog


def test_upgrade_converts_inputs_and_preserves_accounts_favourites_and_monitor_settings(
    disposable_database,
):
    old = catalog("original")
    entity = str(old.sources[0].chargers[0].id)
    topic = old.streams()[0].accepted_topic
    configuration = {
        "display_name": "device/evCharger/this/is-a-name",
        "container_name": "saved-monitor",
        "mqtt_topics": [topic],
        "monitoring": {
            "model_type": "pyod_iforest",
            "model_params": {"n_estimators": 32},
        },
        "performance_config": {"sensor_key_strategy": "full_hierarchy"},
    }
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(User).values(
                id=1,
                email="owner@example.test",
                hashed_password="saved-hash",
                is_verified=True,
            )
        )
        connection.execute(
            insert(Charger).values(
                charger_id=entity,
                charger_name="Saved entity",
                manufacturer_name="Saved manufacturer",
            )
        )
        connection.execute(
            insert(Favorite).values(favorite_id=1, user_id=1, charger_id=entity)
        )
        connection.execute(
            insert(CollectionConfiguration).values(
                id=1,
                revision=7,
                document=old.model_dump(mode="json"),
                updated_by="owner@example.test",
            )
        )
        connection.execute(
            insert(MonitoringService).values(
                id="saved-monitor",
                container_name="saved-monitor",
                mqtt_topic=[topic],
                status=False,
                launch_config=configuration,
            )
        )
        connection.execute(
            insert(Telemetry).values(
                charger_id=entity,
                type="temperature",
                timestamp=datetime.now(UTC),
                value=24.5,
                data_source="mqtt",
            )
        )
        connection.execute(
            text(
                "DELETE FROM off_key_schema_migrations "
                "WHERE version='005_generic_runtime.sql'"
            )
        )
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        saved = SystemDocument.model_validate(
            connection.scalar(select(SystemConfiguration.document))
        )
        runtime = SystemCollectionDefinition.model_validate(
            connection.scalar(select(SystemCollectionConfiguration.document))
        )
        assert saved.connections[0].label == old.sources[0].label
        assert (
            saved.streams[0].topic
            == old.sources[0].chargers[0].sensors[0].upstream_topic
        )
        binding = runtime.bindings[saved.streams[0].id]
        assert binding.entity_id == entity and binding.telemetry_key == "temperature"
        assert binding.accepted_topic == f"telemetry/{entity}/temperature"
        assert runtime.streams()[0].policy.mode == "original"
        assert connection.scalar(select(User.hashed_password)) == "saved-hash"
        assert connection.scalar(select(Favorite.charger_id)) == entity
        assert (
            connection.scalar(select(Charger.manufacturer_name)) == "Saved manufacturer"
        )
        assert connection.scalar(
            select(CollectionConfiguration.document)
        ) == old.model_dump(mode="json")
        assert connection.scalar(select(MonitoringService.launch_config)) == {
            **configuration,
            "mqtt_topics": [binding.accepted_topic],
        }
        assert connection.scalar(select(Telemetry.value)) == 24.5
        revision = connection.scalar(select(SystemConfiguration.revision))
        connection.execute(
            insert(Telemetry).values(
                charger_id=entity,
                type="temperature",
                timestamp=datetime.now(UTC),
                value=30,
                data_source="mqtt",
            )
        )
        assert apply_migrations(connection)["applied"] == []
        assert connection.scalar(select(SystemConfiguration.revision)) == revision
        assert sorted(connection.scalars(select(Telemetry.value))) == [24.5, 30]


def test_topic_conversion_does_not_change_labels_or_sensor_schema():
    before = {
        "display_name": "device/evCharger/a/b",
        "mqtt_topics": ["device/evCharger/a/b"],
        "monitoring": {"required_sensors": ["b", "device/evCharger/a/b"]},
    }
    assert upgrade_topics(before) == {**before, "mqtt_topics": ["telemetry/a/b"]}


def test_upgrade_preserves_a_runtime_without_a_separate_saved_document(
    disposable_database,
):
    definition = runtime_catalog("original")
    stream = definition.document.streams[0]
    binding = definition.bindings[stream.id]
    binding.accepted_topic = (
        f"device/evCharger/{binding.entity_id}/{binding.telemetry_key}"
    )
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(SystemCollectionConfiguration).values(
                id=1,
                revision=11,
                document=definition.model_dump(mode="json"),
                updated_by="owner@example.test",
            )
        )
        connection.execute(
            text(
                "DELETE FROM off_key_schema_migrations "
                "WHERE version='005_generic_runtime.sql'"
            )
        )
        apply_migrations(connection)
        result = SystemCollectionDefinition.model_validate(
            connection.scalar(select(SystemCollectionConfiguration.document))
        )
        assert result.document == definition.document
        assert result.bindings[stream.id].entity_id == binding.entity_id
        assert result.bindings[stream.id].telemetry_key == binding.telemetry_key
        assert result.bindings[stream.id].accepted_topic.startswith("telemetry/")
        assert (
            connection.scalar(select(SystemConfiguration.updated_by))
            == "owner@example.test"
        )
        assert connection.scalar(select(SystemCollectionConfiguration.revision)) == 12


def test_upgrade_monitor_topics_even_without_catalogue_configuration(
    disposable_database,
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="standalone",
                container_name="standalone",
                mqtt_topic=["device/#"],
                status=False,
                launch_config={
                    "mqtt_topics": ["device/#"],
                    "display_name": "Keep this name",
                },
            )
        )
        connection.execute(
            text(
                "DELETE FROM off_key_schema_migrations "
                "WHERE version='005_generic_runtime.sql'"
            )
        )
        apply_migrations(connection)
        assert connection.scalar(select(MonitoringService.mqtt_topic)) == [
            "telemetry/#"
        ]
        assert connection.scalar(select(MonitoringService.launch_config)) == {
            "mqtt_topics": ["telemetry/#"],
            "display_name": "Keep this name",
        }
