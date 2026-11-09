"""The ingress envelope TACTIC publishes and the collection worker admits.

Both sides express ``received_at`` in milliseconds since the Unix epoch.
"""

import json
import time
from datetime import UTC, datetime
from typing import Any

from ..utils.payload_decode import MAX_PAYLOAD_BYTES

# Clock skew tolerated before an observation counts as coming from the future.
FUTURE_TOLERANCE_SECONDS = 300

# JSON escapes one payload byte to at most six characters (a control byte
# becomes \u0000), so this bounds the envelope of any payload TACTIC forwards.
MAX_ENVELOPE_BYTES = 6 * MAX_PAYLOAD_BYTES + 1024


def encode_ingress_envelope(
    payload: str, received_at_ms: float, upstream_retained: bool
) -> str:
    """Wrap one upstream payload with its broker arrival time in milliseconds."""
    return json.dumps(
        {
            "payload": payload,
            "received_at": received_at_ms,
            "upstream_retained": upstream_retained,
        }
    )


def decode_ingress_envelope(envelope: Any) -> tuple[str, datetime, bool]:
    """Validate an envelope; ``received_at`` is milliseconds since the epoch.

    Raises KeyError, TypeError or ValueError for a malformed envelope.
    """
    if not isinstance(envelope, dict):
        raise ValueError("Expected ingress envelope")
    payload = envelope["payload"]
    if not isinstance(payload, str):
        raise TypeError("Expected text payload")
    millis = envelope["received_at"]
    if isinstance(millis, bool) or not isinstance(millis, (int, float)):
        raise ValueError("Expected broker observation time")
    received_at = datetime.fromtimestamp(millis / 1000, UTC)
    if received_at.timestamp() > time.time() + FUTURE_TOLERANCE_SECONDS:
        raise ValueError("Future observation")
    retained = envelope["upstream_retained"]
    if not isinstance(retained, bool):
        raise ValueError("Expected retained flag")
    return payload, received_at, retained


__all__ = [
    "MAX_ENVELOPE_BYTES",
    "decode_ingress_envelope",
    "encode_ingress_envelope",
]
