"""The detector catalogue the setup forms read."""

import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...models.catalog import available_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


# Request/Response models
class ModelInfo(BaseModel):
    """Model information response."""

    model_type: str = Field(..., description="Model type identifier")
    family: str = Field(
        ...,
        description="Model family (e.g., 'distance', 'forest', 'svm')",
    )
    name: str = Field(..., description="Human-readable model name")
    description: str | None = Field(None, description="Model description")
    complexity: str | None = Field(None, description="Computational complexity")
    memory_usage: str | None = Field(None, description="Memory usage level")
    strategy: str = Field(
        default="static_baseline",
        description="Executable static monitoring lane",
    )
    catalog_id: str | None = None
    algorithm_family: str | None = None
    available: bool = True
    default_capabilities: dict[str, Any] | None = None
    import_paths: list[str] = Field(..., description="Python import paths to try")
    parameter_schema: dict[str, Any] = Field(
        ..., description="JSON schema for parameters"
    )
    default_parameters: dict[str, Any] = Field(
        ..., description="Default parameter values"
    )
    version: str = Field(..., description="Model version")
    requires_special_handling: bool = Field(
        ..., description="Requires custom instantiation logic"
    )


@router.get("/", response_model=list[ModelInfo])
async def list_models(
    strategy: str | None = Query(default=None),
) -> list[ModelInfo]:
    """
    Get list of all available models.

    Returns comprehensive information about each model including
    parameter schemas and metadata.
    """
    models = available_models()
    if strategy:
        models = [model for model in models if model["strategy"] == strategy]
    return [ModelInfo(**model) for model in models]
