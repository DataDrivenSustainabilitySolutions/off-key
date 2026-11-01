"""Resolve policy inheritance without allocating descendant lists per topic."""

from off_key_core.schemas.collection_policy import CollectionPolicy


class CollectionRuleResolver:
    def __init__(self, definition):
        self.definition = definition
        self.rules = {rule.scope.key: rule for rule in definition.rules}

    def resolve(self, stream):
        # Scope keys are plain tuples (CollectionRuleScope.key), so candidates are
        # looked up without building and validating a scope model per depth.
        connection_id = stream.connection_id
        reading = self.rules.get(("reading", connection_id, None, stream.id))
        if reading and reading.policy is not None:
            return reading.policy, {
                "scope": reading.scope.model_dump(mode="json"),
                "inherited": False,
                "needs_review": False,
            }
        segments = stream.topic.split("/")
        candidates = [
            ("topic", connection_id, "/".join(segments[:depth]), None)
            for depth in range(len(segments), 0, -1)
        ]
        candidates.append(("broker", connection_id, None, None))
        for candidate in candidates:
            rule = self.rules.get(candidate)
            if rule is None:
                continue
            admitted = (
                reading is not None
                or rule.include_future_readings
                or self.definition.registered_at.get(stream.id, 0)
                <= rule.admitted_before
            )
            return (rule.policy if admitted else CollectionPolicy()), {
                "scope": rule.scope.model_dump(mode="json"),
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
