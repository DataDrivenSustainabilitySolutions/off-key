"""Session result fakes shared by the RADAR orchestration and reconciliation tests."""

from unittest.mock import MagicMock


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
