"""Explicit collection actions and safe runtime reconciliation of catalogue edits."""

from datetime import UTC, datetime
from math import ceil
from uuid import uuid4

from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import Charger, CollectionBinding, MonitoringService
from off_key_core.db.system import SystemCollectionConfiguration, SystemConfiguration
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.collection_rules import (
    CollectionRuleEdit,
    CollectionRuleScope,
    SystemCollectionRuleChange,
)
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    SystemCollectionPreview,
    build_bindings,
    runtime_fingerprint,
)
from off_key_core.utils.collection_rules import CollectionRuleResolver
from sqlalchemy import select

from ..config.collection import get_ambibox_settings
from ..config.system_live import get_system_live_settings
from ..domain import ConflictError, ValidationError
from .ambibox_live_access import AmbiboxLiveAccess
from .collection_monitors import CollectionMonitorService
from .collection_rule_edits import apply_rule_edits, policy_metadata


class SystemCollectionService:
    def __init__(self, session):
        self.session = session

    async def current(self, document):
        runtime = await read_collection_runtime(self.session)
        previous = runtime.catalog
        bindings = build_bindings(document, previous.bindings)
        known = {stream.id for stream in document.streams}
        reading_ids = {(stream.connection_id, stream.id) for stream in document.streams}
        brokers = {broker.id for broker in document.connections}
        old_inputs = {
            stream.id: (stream.connection_id, stream.topic)
            for stream in previous.document.streams
        }
        new = {
            stream.id
            for stream in document.streams
            if old_inputs.get(stream.id) != (stream.connection_id, stream.topic)
        }
        clock = previous.registration_clock + bool(new)
        proposed = SystemCollectionDefinition(
            document=document.model_copy(deep=True),
            bindings=bindings,
            generation=previous.generation,
            rules_version=1,
            # Admissions acknowledge an input; explicit policies follow stable IDs.
            rules=[
                rule
                for rule in previous.rules
                if rule.scope.connection_id in brokers
                and (
                    rule.scope.kind != "reading"
                    or (
                        (rule.scope.connection_id, rule.scope.reading_id) in reading_ids
                        and (
                            rule.policy is not None or rule.scope.reading_id not in new
                        )
                    )
                )
            ],
            registration_clock=clock,
            registered_at={
                key: clock if key in new else previous.registered_at[key]
                for key in known
            },
        )
        proposed.document.default_policy = CollectionPolicy()
        CollectionRuleResolver(proposed).materialize()
        return runtime, proposed

    async def prepare(self, snapshot, change):
        runtime, proposed = await self.current(snapshot.document)
        revision = runtime.revision
        if (
            snapshot.revision != change.expected_revision
            or revision != change.expected_collection_revision
        ):
            raise ConflictError(
                "The catalogue or collection changed. "
                "Reload before applying this change."
            )
        if isinstance(change, SystemCollectionRuleChange):
            apply_rule_edits(proposed, change.rule_changes)
        else:
            selected = set(change.stream_ids)
            known = {stream.id for stream in proposed.document.streams}
            if not selected <= known:
                raise ValidationError("Select existing catalogue readings.")
            apply_rule_edits(
                proposed,
                [
                    CollectionRuleEdit(
                        scope=CollectionRuleScope(
                            kind="reading",
                            connection_id=stream.connection_id,
                            reading_id=stream.id,
                        ),
                        policy=change.policy,
                    )
                    for stream in proposed.document.streams
                    if stream.id in selected
                ],
            )
        previous_inputs = {
            item.accepted_topic: item.signature
            for item in runtime.catalog.streams(selected_only=True)
        }
        if any(
            previous_inputs.get(item.accepted_topic) != item.signature
            for item in proposed.streams(selected_only=True)
        ):
            self._validate_access(proposed)
        affected = await self.affected(runtime.catalog, proposed)
        streams = proposed.streams(selected_only=True)
        numeric = [item for item in streams if item.value_type == "number"]
        before = {
            stream.id: stream.policy or runtime.catalog.document.default_policy
            for stream in runtime.catalog.document.streams
        }
        resolver = CollectionRuleResolver(proposed)
        starts = stops = rates = 0
        preview_bindings = {}
        connections = (
            {edit.scope.connection_id for edit in change.rule_changes}
            if isinstance(change, SystemCollectionRuleChange)
            else None
        )
        for stream in proposed.document.streams:
            old = before.get(stream.id, CollectionPolicy())
            policy, origin = resolver.resolve(stream)
            starts += old.mode == "off" and policy.mode != "off"
            stops += old.mode != "off" and policy.mode == "off"
            rates += old.mode != "off" and policy.mode != "off" and old != policy
            if connections is None or stream.connection_id in connections:
                preview_bindings[stream.id] = {
                    "policy": policy.model_dump(mode="json"),
                    "policy_origin": origin,
                }
        preview = SystemCollectionPreview(
            revision=snapshot.revision,
            collection_revision=revision,
            selected_readings=len(streams),
            sampled_rows_per_day_ceiling=sum(
                ceil(86400 / item.policy.interval_seconds)
                for item in numeric
                if item.policy.mode == "sample"
            ),
            original_rate_readings=sum(
                item.policy.mode == "original" for item in numeric
            ),
            affected_monitors=affected,
            changed_readings=starts + stops + rates,
            starting_readings=starts,
            stopping_readings=stops,
            rate_changed_readings=rates,
            bindings=preview_bindings,
            rules=proposed.rules,
        )
        return proposed, preview

    @staticmethod
    def _validate_access(definition):
        if not definition.streams(selected_only=True):
            return
        settings = get_system_live_settings()
        if not settings.SYSTEM_COLLECTION_ENABLED:
            raise ValidationError("Collection is disabled by the operator.")
        access = AmbiboxLiveAccess(get_ambibox_settings())
        selected = {item.source_id for item in definition.streams(selected_only=True)}
        for connection in definition.document.connections:
            if connection.id not in selected:
                continue
            if not settings.allows_host(connection.host) and access(connection) is None:
                raise ValidationError(
                    "A selected broker is outside the operator's broker allowlist."
                )
            if (
                connection.credential_ref
                and connection.credential_ref not in settings.SYSTEM_LIVE_CREDENTIALS
            ):
                raise ValidationError(
                    "A selected broker's credential reference "
                    "is not configured by the operator."
                )

    @staticmethod
    def _changed_inputs(before, after):
        def signatures(catalog):
            return {
                item.accepted_topic: item.signature
                for item in catalog.streams(selected_only=True)
            }

        old, new = signatures(before), signatures(after)
        return {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}

    async def affected(self, before, after):
        changed = self._changed_inputs(before, after)
        if not changed:
            return []
        from off_key_core.db.pipeline_claims import (
            monitor_claim_condition,
            pending_activations,
        )

        if any(
            changed.intersection(item.claim_topics)
            for item in await pending_activations(self.session)
        ):
            raise ConflictError(
                "A pending pipeline activation reserves these inputs. "
                "Finish or cancel it before changing their collection."
            )
        monitors = await self.session.scalars(
            select(MonitoringService).where(monitor_claim_condition())
        )
        return [
            {"id": item.id, "name": item.container_name}
            for item in monitors
            if changed.intersection(item.mqtt_topic or [])
        ]

    async def apply(self, change, *, actor):
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        from off_key_core.schemas.system import SystemChange

        from .system import SystemService

        snapshot = await SystemService(self.session).read()
        proposed, preview = await self.prepare(snapshot, change)
        await self._protect_monitors(
            preview.affected_monitors, change.pause_affected_monitors, proposed
        )
        await self.persist(proposed, actor=actor)
        return await SystemService(self.session).save(
            SystemChange(
                expected_revision=snapshot.revision, document=proposed.document
            ),
            actor=actor,
        )

    async def sync_structure(self, document, *, actor, pause_monitors=False):
        runtime, proposed = await self.current(document)
        if runtime_fingerprint(runtime.catalog) != runtime_fingerprint(proposed):
            self._validate_access(proposed)
        affected = await self.affected(runtime.catalog, proposed)
        await self._protect_monitors(affected, pause_monitors, proposed)
        await self.persist(proposed, actor=actor)
        return proposed.document

    async def _protect_monitors(self, affected, pause, proposed):
        if affected and not pause:
            raise ConflictError(
                "This change affects running monitors. "
                "Pause them in Services before changing their inputs."
            )
        if not affected:
            return
        before = await self._revision_guard()
        await CollectionMonitorService(self.session).pause_monitors(affected)
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        if await self._revision_guard() != before:
            raise ConflictError(
                "The catalogue or collection changed while monitors stopped. "
                "Reload before applying this change."
            )
        runtime = await read_collection_runtime(self.session)
        stopped_ids = {item["id"] for item in affected}
        current = await self.affected(runtime.catalog, proposed)
        if any(item["id"] not in stopped_ids for item in current):
            raise ConflictError(
                "A new monitor started while inputs were changing. "
                "Reload before applying this change."
            )

    async def _revision_guard(self):
        system = await self.session.scalar(
            select(SystemConfiguration.revision).where(SystemConfiguration.id == 1)
        )
        collection = await self.session.scalar(
            select(SystemCollectionConfiguration.revision).where(
                SystemCollectionConfiguration.id == 1
            )
        )
        return system or 0, collection or 0

    async def persist(self, definition, *, actor):
        row = await self.session.scalar(
            select(SystemCollectionConfiguration).where(
                SystemCollectionConfiguration.id == 1
            )
        )
        previous = (
            SystemCollectionDefinition.model_validate(row.document) if row else None
        )
        changed = previous is None or runtime_fingerprint(
            previous
        ) != runtime_fingerprint(definition)
        if changed:
            definition.generation = uuid4().hex
        if row is None:
            row = SystemCollectionConfiguration(id=1, revision=0)
            self.session.add(row)
        row.document = definition.model_dump(mode="json")
        row.updated_by = actor
        row.updated_at = datetime.now(UTC)
        if (
            changed
            or previous is None
            or policy_metadata(previous) != policy_metadata(definition)
        ):
            row.revision += 1
            row.ingress_status = {}
            row.collection_status = {}
        devices = {item.id: item.label for item in definition.document.devices}
        connections = {item.id: item.label for item in definition.document.connections}
        identities = {binding.entity_id for binding in definition.bindings.values()}
        existing = {
            item.charger_id: item
            for item in await self.session.scalars(
                select(Charger).where(Charger.charger_id.in_(identities))
            )
        }
        bound = set(
            await self.session.scalars(
                select(CollectionBinding.charger_id).where(
                    CollectionBinding.charger_id.in_(identities)
                )
            )
        )
        new_bindings = []
        for stream in definition.document.streams:
            binding = definition.bindings[stream.id]
            entity = existing.get(binding.entity_id)
            label = devices.get(stream.device_id) or connections[stream.connection_id]
            if entity is None:
                entity = Charger(
                    charger_id=binding.entity_id,
                    charger_name=label,
                    manufacturer_name="",
                    online=False,
                    mqtt_connected=False,
                )
                self.session.add(entity)
                existing[binding.entity_id] = entity
            else:
                entity.charger_name = label
            if binding.entity_id not in bound:
                new_bindings.append(
                    CollectionBinding(
                        charger_id=binding.entity_id,
                        source_id=stream.connection_id,
                        local_id=binding.entity_id,
                    )
                )
                bound.add(binding.entity_id)
        await self.session.flush()
        for binding in new_bindings:
            self.session.add(binding)
        await self.session.flush()
