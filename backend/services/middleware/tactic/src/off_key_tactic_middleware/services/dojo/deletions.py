"""Several Dojo items deleted in one request."""

from collections.abc import Awaitable, Callable
from typing import Literal

from off_key_core.db.models import Agent, User
from off_key_core.schemas.dojo import DeletionRefusal, DojoDeletion, DojoDeletionResult
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import DomainError
from .datasets import DojoDatasets
from .suites import DojoSuites


Kind = Literal["suite", "study", "dataset"]


class DojoDeletions:
    """Suites, then studies, then datasets, each with the rules of its own delete."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def remove(
        self, request: DojoDeletion, caller: User | Agent | None = None
    ) -> DojoDeletionResult:
        suites = DojoSuites(self.session)
        datasets = DojoDatasets(self.session)
        steps: list[tuple[Kind, str, Callable[[], Awaitable[None]]]] = [
            *(
                ("suite", id, lambda id=id: suites.remove_suite(id, caller))
                for id in dict.fromkeys(request.suite_ids)
            ),
            *(
                ("study", id, lambda id=id: suites.remove_study(id, caller))
                for id in dict.fromkeys(request.study_ids)
            ),
            *(
                ("dataset", id, lambda id=id: datasets.remove(id, caller))
                for id in dict.fromkeys(request.dataset_ids)
            ),
        ]
        deleted = 0
        refused: list[DeletionRefusal] = []
        for kind, id, delete in steps:
            try:
                await delete()
            except DomainError as error:
                await self.session.rollback()
                refused.append(DeletionRefusal(kind=kind, id=id, reason=str(error)))
            else:
                deleted += 1
        return DojoDeletionResult(deleted=deleted, refused=refused)
