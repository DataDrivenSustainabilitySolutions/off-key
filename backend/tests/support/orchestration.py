"""Session and workload fakes shared by RADAR orchestration and reconciliation tests."""

from unittest.mock import AsyncMock, MagicMock


class FakeWorkloads:
    """RadarWorkloadManager whose observed states are given in read order."""

    def __init__(self, statuses, labels=None):
        self.statuses = list(statuses)
        self.labels = labels or {}
        self.remove = AsyncMock(return_value=True)
        self.remove_intent = AsyncMock(return_value=True)
        self.crashes = AsyncMock(return_value=[])

    async def statuses_and_labels(self, workload_ids):
        found = []
        for workload_id in workload_ids:
            if not workload_id:
                found.append(("no_container_id", {}))
            else:
                state = self.statuses.pop(0) if self.statuses else "not_found"
                found.append((state, self.labels))
        return found

    async def get_status_and_labels(self, workload_id):
        return (await self.statuses_and_labels([workload_id]))[0]


def scalars_result(*, all=None, first=None):
    """An execute() result whose scalars() yields ``all`` rows and ``first`` row."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(all or [])
    result.scalars.return_value.first.return_value = first
    return result


def purge_results(lookup, *, deleted=1):
    """Lookup, pipeline-run release, topic delete and service delete results."""
    return [
        lookup,
        MagicMock(rowcount=0),
        MagicMock(rowcount=0),
        MagicMock(rowcount=deleted),
    ]
