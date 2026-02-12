"""Repository for model-registry admin persistence operations."""

from typing import Optional

from sqlalchemy.orm import Session

from off_key_core.db.models import ModelRegistry


class ModelRegistryAdminRepository:
    """Persistence operations for model-registry admin use cases."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_model_type(self, *, model_type: str) -> Optional[ModelRegistry]:
        return (
            self._session.query(ModelRegistry)
            .filter(ModelRegistry.model_type == model_type)
            .first()
        )

    def list_models(
        self,
        *,
        include_inactive: bool,
        category: Optional[str],
    ) -> list[ModelRegistry]:
        query = self._session.query(ModelRegistry)

        if not include_inactive:
            query = query.filter(ModelRegistry.is_active)

        if category:
            query = query.filter(ModelRegistry.category == category)

        return list(query.all())

    def add(self, model: ModelRegistry) -> None:
        self._session.add(model)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def refresh(self, model: ModelRegistry) -> None:
        self._session.refresh(model)
