"""Execution failures whose handling must survive every ingestion boundary."""


class ObservationRejected(ValueError):
    """One observation was rejected before any uncertain state mutation.

    This is lost coverage, not a substitute anomaly score. The next independent
    observation may still be processed by the same healthy execution.
    """


class StepRejected(ObservationRejected):
    """One step could not process this observation, and the run stays healthy.

    The reason is a short key the diagnostics count, such as non_finite.
    """

    def __init__(self, node_id: str, reason: str, message: str):
        super().__init__(message)
        self.node_id = node_id
        self.reason = reason


class FatalExecutionError(RuntimeError):
    """Execution cannot continue or export its current state safely.

    In particular a terminal model may have mutated before raising. Upstream
    transformer rollback cannot make that model safe. Preserve the last durable
    checkpoint and fence this execution rather than producing fallback results.
    """

    def __init__(self, message: str, *, node_id: str | None = None):
        self.node_id = node_id
        super().__init__(message)
