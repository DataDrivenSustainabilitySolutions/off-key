"""Persistent scope policies, independent of concrete MQTT subscriptions."""

from typing import Literal

from pydantic import Field, model_validator

from .collection_policy import CollectionPolicy
from .system import EntityId, SystemDocument, SystemModel, SystemStream


class CollectionRuleScope(SystemModel):
    kind: Literal["broker", "topic", "reading"]
    connection_id: EntityId
    topic_prefix: str | None = None
    reading_id: EntityId | None = None

    @model_validator(mode="after")
    def valid_target(self):
        if self.kind == "topic":
            if self.topic_prefix is None:
                raise ValueError("A topic scope needs a concrete topic prefix")
            SystemStream.concrete_topic(self.topic_prefix)
        elif self.topic_prefix is not None:
            raise ValueError("Only topic scopes have a topic prefix")
        if (self.kind == "reading") != (self.reading_id is not None):
            raise ValueError("Only reading scopes have a reading ID")
        return self

    @property
    def key(self):
        return (self.kind, self.connection_id, self.topic_prefix, self.reading_id)

    def matches(self, stream):
        if stream.connection_id != self.connection_id:
            return False
        if self.kind == "reading":
            return stream.id == self.reading_id
        if self.kind == "broker":
            return True
        prefix = self.topic_prefix
        if prefix is None:
            return False
        return stream.topic == prefix or stream.topic.startswith(prefix + "/")


class CollectionRule(SystemModel):
    scope: CollectionRuleScope
    policy: CollectionPolicy | None = None
    include_future_readings: bool = False
    admitted_before: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid_policy(self):
        if self.policy is None and self.scope.kind != "reading":
            raise ValueError("Parent rules require a recording policy")
        if self.scope.kind == "reading" and self.include_future_readings:
            raise ValueError("A reading cannot include future readings")
        return self


class CollectionRuleEdit(SystemModel):
    scope: CollectionRuleScope
    operation: Literal["set", "inherit", "include", "restore"] = "set"
    policy: CollectionPolicy | None = None
    include_future_readings: bool = False
    restore_rule: CollectionRule | None = None

    @model_validator(mode="after")
    def valid_edit(self):
        if self.scope.kind == "reading" and self.include_future_readings:
            raise ValueError("A reading cannot include future readings")
        if self.operation == "set" and self.policy is None:
            raise ValueError("Choose a policy for this scope")
        if self.operation != "set" and (
            self.policy is not None or self.include_future_readings
        ):
            raise ValueError("Only set operations supply recording settings")
        if self.operation != "restore" and self.restore_rule is not None:
            raise ValueError("Only restore operations supply a previous rule")
        if self.restore_rule and self.restore_rule.scope != self.scope:
            raise ValueError("The restored rule must have the same scope")
        return self


class SystemCollectionRuleChange(SystemModel):
    expected_revision: int = Field(ge=0)
    expected_collection_revision: int = Field(ge=0)
    rule_changes: list[CollectionRuleEdit] = Field(min_length=1, max_length=4096)
    pause_affected_monitors: bool = False

    @model_validator(mode="after")
    def unique_targets(self):
        keys = [item.scope.key for item in self.rule_changes]
        if len(keys) != len(set(keys)):
            raise ValueError("Change each scope once per request")
        return self


def legacy_rules(document: SystemDocument) -> list[CollectionRule]:
    """Pin each collected reading of a pre-rules definition to its own policy."""
    return [
        CollectionRule(
            scope=CollectionRuleScope(
                kind="reading", connection_id=stream.connection_id, reading_id=stream.id
            ),
            policy=stream.policy or document.default_policy,
        )
        for stream in document.streams
        if (stream.policy or document.default_policy).mode != "off"
    ]
