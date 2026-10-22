"""Validate scope edits and retain admission boundaries across parent changes."""

from off_key_core.schemas.collection_rules import CollectionRule, CollectionRuleScope
from off_key_core.utils.collection_rules import CollectionRuleResolver

from ..domain import ValidationError


def restore_rule(definition, rules, edit):
    if edit.restore_rule is None:
        rules.pop(edit.scope.key, None)
    elif edit.restore_rule.admitted_before > definition.registration_clock:
        raise ValidationError("The restored admission boundary is invalid.")
    else:
        rules[edit.scope.key] = edit.restore_rule


def set_rule(definition, rules, edit):
    previous = rules.get(edit.scope.key)
    cutoff = previous.admitted_before if previous else definition.registration_clock
    if (
        previous
        and previous.include_future_readings
        and not edit.include_future_readings
    ):
        cutoff = definition.registration_clock
    rules[edit.scope.key] = CollectionRule(
        scope=edit.scope,
        policy=edit.policy,
        include_future_readings=edit.include_future_readings,
        admitted_before=cutoff,
    )


def include_readings(definition, rules, selected):
    definition.rules = list(rules.values())
    resolver = CollectionRuleResolver(definition)
    for stream in selected:
        if not resolver.resolve(stream)[1]["needs_review"]:
            continue
        reading_scope = CollectionRuleScope(
            kind="reading",
            connection_id=stream.connection_id,
            reading_id=stream.id,
        )
        rules[reading_scope.key] = CollectionRule(scope=reading_scope)


def apply_rule_edits(definition, edits):
    brokers = {item.id for item in definition.document.connections}
    readings = {
        (stream.connection_id, stream.id): stream
        for stream in definition.document.streams
    }
    rules = {item.scope.key: item for item in definition.rules}
    for edit in edits:
        scope = edit.scope
        if scope.connection_id not in brokers or (
            scope.kind == "reading"
            and (scope.connection_id, scope.reading_id) not in readings
        ):
            raise ValidationError("Select an existing broker or reading.")
        if edit.operation == "restore":
            restore_rule(definition, rules, edit)
        elif edit.operation == "set":
            set_rule(definition, rules, edit)
        elif edit.operation == "inherit":
            if scope.kind == "reading":
                rules[scope.key] = CollectionRule(scope=scope)
            else:
                rules.pop(scope.key, None)
        elif edit.operation == "include":
            selected = (
                [readings[scope.connection_id, scope.reading_id]]
                if scope.kind == "reading"
                else [stream for stream in readings.values() if scope.matches(stream)]
            )
            include_readings(definition, rules, selected)
    if len(rules) > 4096:
        raise ValidationError("The catalogue supports at most 4096 recording rules.")
    definition.rules = sorted(rules.values(), key=lambda item: repr(item.scope.key))
    CollectionRuleResolver(definition).materialize()


def policy_metadata(definition):
    return {
        "rules": sorted(
            (item.model_dump(mode="json") for item in definition.rules), key=repr
        ),
        "registered_at": definition.registered_at,
        "registration_clock": definition.registration_clock,
    }
