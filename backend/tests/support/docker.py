"""In-memory Docker facade for orchestration tests that never reach an engine."""

from types import SimpleNamespace
from unittest.mock import MagicMock


class FakeAsyncDocker:
    """Runs facade calls inline against attribute-configurable client mocks."""

    def __init__(self):
        self.client = SimpleNamespace(
            api=SimpleNamespace(tasks=MagicMock(return_value=[])),
            services=SimpleNamespace(),
            containers=SimpleNamespace(),
        )

    async def run(self, func, *args, **kwargs):
        return func(*args, **kwargs)
