"""Route replacement evidence must retain both sides of the ownership fence."""

import tempfile
import unittest
from pathlib import Path

from swarm_smoke import assert_replaced_stopped_before_successor


class RouteReplacementEvidenceTests(unittest.TestCase):
    def test_rejects_missing_or_reversed_ownership_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.log"
            for events in (
                "2 start offkey-smoke_broker-route\n",
                "2 die offkey-smoke_old-route\n1 start offkey-smoke_broker-route\n",
            ):
                path.write_text(events)
                with self.assertRaises(AssertionError):
                    assert_replaced_stopped_before_successor(path, ["old-route"])
            path.write_text(
                "1 die offkey-smoke_old-route\n2 start offkey-smoke_broker-route\n"
            )
            assert_replaced_stopped_before_successor(path, ["old-route"])
