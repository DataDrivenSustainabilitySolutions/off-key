"""Resolve policy inheritance without allocating descendant lists per topic."""

from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.collection_rules import CollectionRule, CollectionRuleScope


class CollectionRuleResolver:
    def __init__(self, definition):
        self.definition = definition
        self.rules = {rule.scope.key: rule for rule in definition.rules}

    def resolve(self, stream):
        scope = CollectionRuleScope(
            kind="reading", connection_id=stream.connection_id, reading_id=stream.id
        )
        reading = self.rules.get(scope.key)
        if reading and reading.policy is not None:
            return reading.policy, {
                "scope": scope.model_dump(mode="json"),
                "inherited": False,
                "needs_review": False,
            }
        segments = stream.topic.split("/")
        scopes = [
            CollectionRuleScope(
                kind="topic",
                connection_id=stream.connection_id,
                topic_prefix="/".join(segments[:depth]),
            )
            for depth in range(len(segments), 0, -1)
        ]
        scopes.append(
            CollectionRuleScope(kind="broker", connection_id=stream.connection_id)
        )
        for candidate in scopes:
            rule = self.rules.get(candidate.key)
            if rule is None:
                continue
            admitted = (
                reading is not None
                or rule.include_future_readings
                or self.definition.registered_at.get(stream.id, 0)
                <= rule.admitted_before
            )
            return (rule.policy if admitted else CollectionPolicy()), {
                "scope": candidate.model_dump(mode="json"),
                "inherited": True,
                "needs_review": not admitted,
            }
        return CollectionPolicy(), {
            "scope": None,
            "inherited": True,
            "needs_review": False,
        }

    def materialize(self):
        for stream in self.definition.document.streams:
            stream.policy = self.resolve(stream)[0]


def legacy_rules(document):
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
